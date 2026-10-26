"""Read-only learning diagnostics; no strategy, risk or promotion decisions."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import math

from .historical.core import utc, trading_age_seconds
from .broker_calendar import instant_open
from .hypothesis_review import SPEC as REVIEW_SPEC


def metrics(rows):
    ordered = sorted(rows, key=lambda r: (r['exit_at'], r.get('event_id', '')))
    values = [r['net_pnl'] for r in ordered]
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError('Invalid diagnostic financial result')
    gains = [v for v in values if v > 0]
    losses = [v for v in values if v < 0]
    balance = peak = drawdown = 0.
    for value in values:
        balance += value
        peak = max(peak, balance)
        drawdown = max(drawdown, peak-balance)
    return dict(closed=len(values), wins=len(gains), losses=len(losses),
        net_pnl=sum(values), average_gain=sum(gains)/len(gains) if gains else None,
        average_loss=sum(losses)/len(losses) if losses else None,
        realized_drawdown=drawdown if values else None,
        first_exit=ordered[0]['exit_at'] if ordered else None,
        last_exit=ordered[-1]['exit_at'] if ordered else None)


def context_label(key):
    parts = key.split('|')
    if len(parts) < 4:
        return key
    regime, side, session, volatility = parts[-4:]
    return ' · '.join((regime, {'long': 'Compra', 'short': 'Venda'}.get(side, side),
                        session or 'Sem sessão', volatility.replace('vol:', 'Vol. ')))


def review_progress(review):
    review = review or {}
    proposal = review.get('proposal')
    if proposal:
        end = utc(proposal['ends_at'])
        return dict(stage=proposal['status'], samples=len(proposal.get('validation', [])),
            minimum=proposal['minimum_samples'], collection_ends_at=end.isoformat(),
            evaluation_not_before=(end+timedelta(days=1)).isoformat(),
            rule=proposal['rule'], context=context_label(proposal['context']),
            automatic_activation=False)
    counts = Counter(r['context'] for r in review.get('reviews', []))
    return dict(stage='DISCOVERY', samples=max(counts.values(), default=0), minimum=REVIEW_SPEC['discovery_min'],
        collection_ends_at=None, evaluation_not_before=None, automatic_activation=False)


def summary(state, variants):
    rows = state.get('outcomes', [])
    baseline = metrics([r for r in rows if r['variant'] == 'baseline'])
    portfolios = []
    for key, spec in variants.items():
        result = metrics([r for r in rows if r['variant'] == key])
        portfolios.append(dict(id=key, name=spec['name'], **result,
            delta_baseline=result['net_pnl']-baseline['net_pnl'] if result['closed'] and baseline['closed'] else None,
            active=key == state['champion']))
    contexts = []
    for key, context in sorted({(r['variant'], r['context']) for r in rows}):
        contexts.append(dict(strategy=variants[key]['name'], context=context_label(context),
            context_id=context, **metrics([r for r in rows if r['variant'] == key and r['context'] == context])))
    exploration = state.get('exploratory') or {}
    erows = (exploration.get('hypothesis_review') or {}).get('reviews', [])
    exploratory_contexts = [dict(strategy='Pullback exploratório', context=context_label(key), context_id=key,
        **metrics([r for r in erows if r['context'] == key])) for key in sorted({r['context'] for r in erows})]
    return dict(portfolios=portfolios, contexts=contexts, exploratory_contexts=exploratory_contexts,
        exploratory_metrics=metrics(erows),
        coverage='Últimos 90 dias e até 2.000 resultados das variantes; pesquisa exploratória: até 1.000 revisões válidas retidas. Não é o histórico completo da conta.',
        comparison='Diferença descritiva entre carteiras simuladas na janela retida; não é prova de melhoria nem comparação pareada.',
        drawdown_basis='Maior queda acumulada dos resultados encerrados na janela, em USD; não inclui perda flutuante.',
        last_bar=state.get('last_bar'), diagnostics=state.get('diagnostics'),
        production_review=review_progress(state.get('hypothesis_review')),
        exploratory_review=review_progress(exploration.get('hypothesis_review')),
        variant_minimum=20,
        variant_evaluation_not_before=(utc(state['registered_at'])+timedelta(days=7)).isoformat())


def record_decision(state, candle, decision):
    """Telemetry only. A repeated checkpoint never counts a candle twice."""
    data = state.setdefault('diagnostics', dict(since=candle, last_candle=None, analyzed=0, reasons={}))
    if data['last_candle'] and utc(candle) <= utc(data['last_candle']):
        return
    data['last_candle'] = candle
    data['analyzed'] += 1
    # A single final outcome per analyzed candle, not a count of every predicate.
    code = 'ENTRY_SENT' if decision['action'] in {'BUY', 'SELL'} else decision.get('reason') or 'WAIT'
    if len(code) > 100 or ' ' in code:
        code = 'OTHER_WAIT'
    data['reasons'][code] = data['reasons'].get(code, 0)+1


def collection_health(state, worker, now=None):
    now = utc(now or datetime.now(timezone.utc))
    evolution = (((state.get('autonomy') or {}).get('continual') or {}).get('evolution') or {})
    last = evolution.get('last_bar') or (state.get('last_decision') or {}).get('candle')
    result = dict(checked_at=now.isoformat(), last_closed_bar=last, alerts=[], status='OK')
    if state.get('desired') != 'running':
        result.update(status='PAUSED', message='Coleta pausada ou agente parado por solicitação.')
    elif not worker.get('available'):
        result.update(status='ERROR', message='O serviço Windows não confirma atividade. A coleta pode estar interrompida.')
    elif state.get('state') in {'WAITING_SOURCE', 'ERROR', 'INSUFFICIENT_DATA'}:
        result.update(status='ERROR', message='A coleta está aguardando fonte ou dados válidos. Verifique a conexão com o MT5.')
    elif state.get('state') in {'CONNECTING', 'QUEUED', 'LOADING_HISTORY', 'ANALYSIS_WARMUP', 'RECOVERING'}:
        result.update(status='PREPARING', message='Preparando o contexto. Ainda não é ausência de oportunidades.')
    elif not instant_open(now):
        result.update(status='MARKET_CLOSED', message='Mercado fechado pelo calendário semanal; ausência de novos candles é esperada.')
    elif state.get('state') == 'WAITING_QUOTE':
        result.update(status='ERROR', message='Aguardando cotações válidas do MT5 durante o mercado aberto.')
    elif not last:
        result.update(status='WARNING', message='Ainda não há candle analisado registrado para confirmar a coleta.')
    else:
        closed_at = utc(last)+timedelta(minutes=5)
        if closed_at > now+timedelta(seconds=60):
            result.update(status='WARNING', message='Horário do candle está no futuro; verifique o relógio da fonte.')
        elif closed_at < now and trading_age_seconds(max(closed_at, now-timedelta(days=7)), now) > 15*60:
            result.update(status='ERROR', message='Sem avanço da análise há mais de 15 minutos de mercado aberto. Isso não significa falta de oportunidade.')
        else:
            result['message'] = 'Coleta recente. Aguardar um gatilho não representa falha do agente.'
    learning = (state.get('autonomy') or {}).get('continual') or {}
    exploration = learning.get('exploratory') or {}
    if exploration.get('forecast_errors'):
        result['alerts'].append('Houve falhas de previsão na pesquisa exploratória. Nessas amostras, Timestral foi marcado como ausente.')
    if learning.get('censored', 0) or exploration.get('censored', 0):
        result['alerts'].append('Há simulações excluídas por dados incompletos. Elas não contam como ganho ou perda.')
    return result
