"""Prospective Fibonacci ablation; checkpointed shadow portfolios, no promotion."""
from dataclasses import replace
from datetime import timedelta
import copy
import math

from .agent_model import fingerprint
from .agent_research import request_for
from .historical.core import utc
from .structure import analyze_structure


ARMS = {'reference': 'Estratégia atual', 'retracement': 'Contexto de retração',
        'extension': 'Saída por extensão', 'extension_reference': 'Controle da saída'}
SPEC = dict(version='fibonacci-shadow-v1', execution='M5', pivot_window=2,
    history_bars=300, minimum_impulse_atr=1., maximum_anchor_age_bars=96,
    retracement_min=.382, retracement_max=.786, extension=1.272,
    measurement='signal_close', minimum_closed=30,
    discovery_days=14, validation_days=30, minimum_paired_days=7,
    scope='independent_costed_shadow_portfolios', automatic_activation=False)
SPEC['exit_comparison'] = 'same_anchor_eligible_stream_with_original_exit_control'
SPEC_HASH = fingerprint(SPEC)


def initialize(parent, at):
    from .continual_learning import profile_for
    from .agent_strategy import strategy_hash
    profile = profile_for(parent)
    expected = fingerprint(dict(spec=SPEC_HASH, reference_strategy=strategy_hash(profile), profile=parent.get('profile_id'),
                                units=parent['units']))
    fresh = dict(spec_hash=expected,
        symbol=parent.get('symbol', 'EURUSD'), profile_id=parent.get('profile_id'),
        registered_at=utc(at).isoformat(), last_signal=None, last_bar=None,
        observations=[], outcomes=[], portfolios={}, counts={}, censored=0,
        errors=0, last_error=None)
    state = parent.setdefault('fibonacci_research', fresh)
    if state['spec_hash'] != expected:
        if (state['observations'] or state['outcomes'] or
                any(p.get('request') or p.get('position') for p in state['portfolios'].values())):
            raise ValueError('FIBONACCI_PROTOCOL_SCOPE_MISMATCH')
        fresh['previous_empty_protocol'] = state['spec_hash']
        parent['fibonacci_research'] = state = fresh
    return state, profile


def measure(history, setup, *, profile=None):
    """Two confirmed alternating pivots strictly before the signal bar.

    Confirmation timestamps, not pivot timestamps, determine availability.
    The latest pair is selected mechanically; no searching for a prettier leg.
    """
    signal = utc(setup['signal_at'])
    bars = list(history)[-SPEC['history_bars']:]
    if (not bars or bars[-1].timestamp + timedelta(minutes=5) != signal
            or any(b.timestamp + timedelta(minutes=5) > signal for b in bars)):
        return dict(available=False, reason='HISTORY_NOT_CAUSAL')
    atr = setup['atr']
    if not math.isfinite(atr) or atr <= 0:
        return dict(available=False, reason='ATR_UNAVAILABLE')
    # A gap invalidates this impulse context, without changing live entries.
    tail = bars[-(SPEC['maximum_anchor_age_bars'] + 5):]
    from .broker_calendar import unexpected_broker_gap
    gap = profile.calendar.unexpected_gap if profile else unexpected_broker_gap
    if any(gap(a, b, 300) for a, b in zip(tail, tail[1:])):
        return dict(available=False, reason='CONTEXT_DATA_GAP')
    swings = [s for s in analyze_structure(bars, window=2, bar_seconds=300).swings
              if utc(s.confirmed_at) <= signal and s.index < len(bars)-1]
    alternating = []
    for swing in swings:
        if alternating and alternating[-1].index == swing.index:
            return dict(available=False, reason='AMBIGUOUS_OUTSIDE_BAR')
        if alternating and alternating[-1].kind == swing.kind:
            old = alternating[-1]
            if (swing.price > old.price) == (swing.kind == 'high'):
                alternating[-1] = swing
        else:
            alternating.append(swing)
    if len(alternating) < 2:
        return dict(available=False, reason='CONFIRMED_ANCHORS_UNAVAILABLE')
    a, b = alternating[-2:]
    long = setup['candidate'].side == 'long'
    if (a.kind, b.kind) != (('low', 'high') if long else ('high', 'low')):
        return dict(available=False, reason='IMPULSE_DIRECTION_MISMATCH')
    length = (b.price-a.price) * (1 if long else -1)
    if length < atr or len(bars)-1-a.index > SPEC['maximum_anchor_age_bars']:
        return dict(available=False, reason='IMPULSE_SMALL_OR_OLD')
    after = bars[b.index+1:]
    if any(c.high > b.price if long else c.low < b.price for c in after):
        return dict(available=False, reason='IMPULSE_EXTREME_SUPERSEDED')
    if any(c.low <= a.price if long else c.high >= a.price for c in after):
        return dict(available=False, reason='IMPULSE_ORIGIN_INVALIDATED')
    close = bars[-1].close
    depth = (b.price-close if long else close-b.price)/length
    sign = 1 if long else -1
    levels = {str(r): b.price-sign*r*length for r in (.382, .5, .618, .786)}
    return dict(available=True, anchor_start=dict(price=a.price, at=a.timestamp,
        confirmed_at=a.confirmed_at), anchor_end=dict(price=b.price, at=b.timestamp,
        confirmed_at=b.confirmed_at), depth=depth, measurement='signal_close',
        impulse_atr=length/atr, levels=levels,
        distances_atr={k: abs(close-v)/atr for k, v in levels.items()},
        extension_target=a.price+sign*SPEC['extension']*length)


def _consider(parent, setup, history):
    from .continual_learning import decode_sim, encode_sim, check_scope, context
    check_scope(parent, setup)
    state, profile = initialize(parent, setup['signal_at'])
    signal = utc(setup['signal_at'])
    if (signal <= utc(state['registered_at']) or
            state['last_signal'] and signal <= utc(state['last_signal'])):
        return
    facts = measure(history, setup, profile=profile)
    candidate = setup['candidate']
    cohort = ('discovery' if signal < utc(state['registered_at']) +
              timedelta(days=SPEC['discovery_days']) else 'validation')
    end = utc(state['registered_at']) + timedelta(days=SPEC['discovery_days']+SPEC['validation_days'])
    if signal >= end:
        return
    observation = dict(signal_at=signal.isoformat(), symbol=state['symbol'],
        opportunity_id=fingerprint(dict(spec=state['spec_hash'],start=state['registered_at'],signal=signal.isoformat())),
        profile_id=state['profile_id'], timeframe='M5', cohort=cohort,
        regime=setup['snapshot'].get('regime'), side=candidate.side,
        context=context(setup), sessions=setup['snapshot'].get('session'),
        model_configuration=setup.get('learning_model'), source=setup.get('learning_source'),
        evidence=list(candidate.evidence), contradictions=list(candidate.contradictions),
        entry=candidate.entry, stop=candidate.stop, original_target=candidate.target,
        anchors=facts, arms={})
    for arm in ARMS:
        sim = decode_sim(state['portfolios'].get(arm), parent['units'], profile=profile)
        reason = None
        modified = candidate
        if sim.busy or sim.account_locked:
            reason = 'PORTFOLIO_BUSY_OR_LOCKED'
        elif arm != 'reference' and not facts['available']:
            reason = facts['reason']
        elif arm == 'retracement' and not SPEC['retracement_min'] <= facts['depth'] <= SPEC['retracement_max']:
            reason = 'OUTSIDE_RETRACEMENT_ZONE'
        elif arm in {'extension', 'extension_reference'}:
            target = facts['extension_target']
            if (target-candidate.entry)*(1 if candidate.side == 'long' else -1) <= 0:
                reason = 'EXTENSION_BEHIND_ENTRY'
            elif arm == 'extension':
                modified = replace(candidate, target=target)
        if reason is None:
            payload = {**setup, 'candidate': modified, 'snapshot': {**setup['snapshot'],
                'fibonacci': observation | dict(arms={}), 'fibonacci_arm': arm}}
            sim.submit(request_for(payload, fingerprint(dict(spec=state['spec_hash'],
                start=state['registered_at'], signal=signal.isoformat(), arm=arm))))
        observation['arms'][arm] = reason or 'SUBMITTED'
        state['counts'][arm+':'+(reason or 'SUBMITTED')] = state['counts'].get(arm+':'+(reason or 'SUBMITTED'), 0)+1
        state['portfolios'][arm] = encode_sim(sim)
    state['observations'] = (state['observations']+[observation])[-1000:]
    state.setdefault('pending_records', []).append(dict(kind='observation', payload=observation))
    state['last_signal'] = signal.isoformat()


def _advance(parent, bar, at, valid, active, closing):
    from .continual_learning import decode_sim, encode_sim
    state, profile = initialize(parent, at)
    if (bar.timestamp+timedelta(minutes=5) > utc(at) or
            bar.timestamp+timedelta(minutes=5) <= utc(state['registered_at']) or
            state['last_bar'] and bar.timestamp <= utc(state['last_bar'])):
        return
    for arm in ARMS:
        sim = decode_sim(state['portfolios'].get(arm), parent['units'], profile=profile)
        for event in sim.advance(bar, data_valid=valid, active_sessions=active, force_close_reason=closing):
            if event['status'] == 'closed':
                facts = event['intelligence_context']['fibonacci']
                financial = event['financial_result']
                state['outcomes'].append(dict(variant=arm, event_id=event['event_id'],
                    opportunity_id=facts['opportunity_id'],
                    signal_at=facts['signal_at'], cohort=facts['cohort'],
                    context=facts['context'], depth=facts['anchors'].get('depth'),
                    symbol=state['symbol'], profile_id=state['profile_id'],
                    entry_at=event['entry_at'], exit_at=event['observed_at'],
                    net_pnl=financial['net_pnl'], result_in_r=financial['result_in_r'],
                    gross_pnl=financial['gross_pnl'],
                    costs=financial['gross_pnl']-financial['net_pnl']))
                state.setdefault('pending_records', []).append(dict(kind='result', payload=state['outcomes'][-1]))
            elif event['status'] in {'rejected', 'censored'}:
                code=arm+':'+event['status']+':'+event.get('reason', 'UNKNOWN')
                state['counts'][code]=state['counts'].get(code, 0)+1
                state['censored'] += int(event['status'] == 'censored')
        sim.events.clear()
        # Risk locks terminate this research cohort, not the broker account.
        state['portfolios'][arm] = encode_sim(sim)
    state['outcomes'] = state['outcomes'][-2000:]
    state['last_bar'] = bar.timestamp.isoformat()


def guarded(parent, action, *args):
    """An auxiliary experiment cannot abort trading or partially persist a step."""
    old = copy.deepcopy(parent.get('fibonacci_research'))
    try:
        {'consider': _consider, 'advance': _advance}[action](parent, *args)
    except Exception as exc:
        if old is None:
            parent.pop('fibonacci_research', None)
        else:
            parent['fibonacci_research'] = old
        failure = parent.setdefault('fibonacci_failure', dict(count=0))
        failure.update(count=failure['count']+1, error=type(exc).__name__,
                       reason=str(exc)[:120], action=action)


def summary(parent):
    from .learning_evolution import metrics
    state = parent.get('fibonacci_research')
    if not state:
        return dict(status='WAITING', failure=parent.get('fibonacci_failure'), arms=[],
                    message='Aguardando o próximo ciclo do agente para iniciar a pesquisa.')
    start = utc(state['registered_at'])
    cutoff = start+timedelta(days=SPEC['discovery_days'])
    end = cutoff+timedelta(days=SPEC['validation_days'])
    now = utc(state['last_bar'])+timedelta(minutes=5) if state['last_bar'] else start
    rows = [r for r in state['outcomes'] if r['cohort'] == 'validation']
    base = [r for r in rows if r['variant'] == 'reference']
    base_metrics = metrics(base)
    arms=[]
    for arm, name in ARMS.items():
        if arm=='extension_reference':
            continue
        comparison='extension_reference' if arm=='extension' else 'reference'
        base=[r for r in rows if r['variant']==comparison]
        base_metrics=metrics(base)
        selected = [r for r in rows if r['variant'] == arm]
        m=metrics(selected)
        days=sorted({r['exit_at'][:10] for r in selected+base})
        differences=[sum(r['net_pnl'] for r in selected if r['exit_at'].startswith(d))-
                     sum(r['net_pnl'] for r in base if r['exit_at'].startswith(d)) for d in days]
        lower=None
        if len(days)>=SPEC['minimum_paired_days']:
            mean=sum(differences)/len(days)
            variance=sum((x-mean)**2 for x in differences)/(len(days)-1)
            lower=mean-2.58*math.sqrt(variance/len(days))
        enough=min(len(selected),len(base))>=SPEC['minimum_closed'] and len(days)>=SPEC['minimum_paired_days']
        label='REFERENCE' if arm=='reference' else 'COLLECTING'
        if arm!='reference' and now>=end+timedelta(minutes=65):
            label='INCONCLUSIVE'
            if enough and not state['censored'] and not parent.get('fibonacci_failure'):
                label=('CANDIDATE' if m['net_pnl']>0 and lower is not None and lower>0
                       and m['realized_drawdown']<=base_metrics['realized_drawdown'] else 'REJECTED')
        arms.append(dict(id=arm,name=name,status=label,**m,
            comparison_reference=ARMS[comparison], comparison_closed=len(base),
            delta_baseline=m['net_pnl']-base_metrics['net_pnl'] if selected and base else None,
            daily_difference_lower_bound=lower, discovery=metrics([r for r in state['outcomes']
                if r['cohort']=='discovery' and r['variant']==arm])))
    return dict(status='DISCOVERY' if now<cutoff else 'VALIDATION' if now<end else 'EVALUATING',
        spec_hash=state['spec_hash'], symbol=state['symbol'], automatic_activation=False,
        registered_at=state['registered_at'], validation_starts_at=cutoff.isoformat(),
        collection_ends_at=end.isoformat(), minimum_closed=SPEC['minimum_closed'],
        observations=len(state['observations']), last_observation=state['observations'][-1] if state['observations'] else None,
        censored=state['censored'], failure=parent.get('fibonacci_failure'), counts=state['counts'], arms=arms,
        contexts=[dict(arm=arm, context=key, **metrics([r for r in rows
            if r['variant']==arm and r['context']==key])) for arm,key in
            sorted({(r['variant'],r['context']) for r in rows})],
        message='Descoberta e validação futura separadas; carteiras independentes após custos. '
        'Candidata exige confirmação independente. Não modifica o Timestral nem envia ordens. '
        'Até 1.000 observações e 2.000 resultados retidos; drawdown realizado, sem perda flutuante.')
