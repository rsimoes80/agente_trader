"""One-variable trigger/holding comparisons on sealed correction candidates."""
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from statistics import mean

from .agent_research import SESSIONS,request_for,simulator
from .broker_calendar import unexpected_broker_gap
from .domain import Candidate
from .historical.core import utc
from .sessions import SessionEngine
from .trend_experiment import wilson


ARMS={
    'reference':dict(group='reference',filter='all',holding_bars=12),
    'body_05atr':dict(group='trigger',filter='body_05atr',holding_bars=12),
    'close_75pct':dict(group='trigger',filter='close_75pct',holding_bars=12),
    'break_previous3':dict(group='trigger',filter='break_previous3',holding_bars=12),
    'holding_30min':dict(group='exit',filter='all',holding_bars=6),
    'holding_120min':dict(group='exit',filter='all',holding_bars=24),
}

PROTOCOL=dict(version='trigger-exit-isolated-v1',arms=ARMS,
    source_report='6ba3f9946d64314f98f0d1181967b64e9a9ec2d675fe1967f37d78152caf392f',
    source_scope='107 sealed strict-or-guarded-correction signals; filters can only reject, not create or delay entries',
    body='directional body at least 0.5 of original 14-bar ATR',
    close='directional close in final 25 percent of signal-bar high-low range',
    breakout='signal close beyond all three previous M5 highs/lows in entry direction',
    exits='maximum 6,12,24 observed M5 bars; original stop and 2.5R target remain fixed',
    common_boundary_purge_minutes=120,
    unchanged='H4/H1 alignment, lot, entries, stop, target, fees, min net RR2, daily max5 and risk budgets',
    comparisons='each arm versus reference; no filter combinations, no trigger-plus-exit combinations, no parameter search',
    same_entry_counterfactual='exit arms also replay each reference-filled trade in its own independent simulation; descriptive, not a portfolio',
    gaps='unexpected missing tradable bars censor exposure; no fictional outcome',
    costs='existing observed bid/ask spread, 0.2 pip market-fill slippage, USD35/million/side commission; no swap model',
    calendar='report wall-clock holds exceeding nominal holding window; 24 observed bars may span a closure',
    data_status='previously researched historical prices; all temporal partitions already known',
    multiplicity='six descriptive arms; no significance or winner claim from best retrospective value',
    live_policy_changed=False,orders_sent=0,automatic_promotion=False)


def feature_rows(samples,candles):
    indices={b.timestamp:i for i,b in enumerate(candles)}
    if len(indices)!=len(candles):raise ValueError('Duplicate source timestamps')
    output={}
    for sample in samples:
        signal=utc(sample['signal_at']);stamp=signal-timedelta(minutes=5)
        if utc(sample['entry_at'])!=signal:raise ValueError('Delayed or rewound sealed entry')
        if stamp not in indices:raise ValueError('Signal candle missing')
        i=indices[stamp];prefix=candles[max(0,i-14):i+1]
        if len(prefix)!=15:raise ValueError('Insufficient closed feature history')
        if any(unexpected_broker_gap(a,b,300) for a,b in zip(prefix,prefix[1:])):
            raise ValueError('Feature window has missing tradable candles')
        current=prefix[-1];side=sample['candidate']['side']
        expected={'long':('bullish','BULL_CONFIRMED'),'short':('bearish','BEAR_CONFIRMED')}.get(side)
        for role in ('macro_trend','context_trend'):
            tr=sample['snapshot'].get(role,{})
            if not expected or (tr.get('direction'),tr.get('state'))!=expected:
                raise ValueError('Sealed sample violates direction policy')
            if tr.get('timestamp_utc') and utc(tr['timestamp_utc'])>signal:
                raise ValueError('Future trend observation')
        if abs(current.close-sample['candidate']['entry'])>1e-12:
            raise ValueError('Signal price does not match frozen candle')
        sign=1 if side=='long' else -1
        atr=mean(max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(prefix[:-1],prefix[1:]))
        if atr<=0:raise ValueError('Invalid signal ATR')
        width=current.high-current.low
        location=((current.close-current.low) if sign==1 else (current.high-current.close))/width if width else 0.
        extreme=max(b.high for b in prefix[-4:-1]) if sign==1 else min(b.low for b in prefix[-4:-1])
        if current.timestamp+timedelta(minutes=5)!=signal:raise ValueError('Unclosed signal')
        output[sample['sample_id']]=dict(known_at=signal.isoformat(),body_atr=sign*(current.close-current.open)/atr,
            directional_close_location=location,break_previous3=sign*(current.close-extreme)>0)
    return output


def accepts(features,arm):
    if arm not in ARMS:raise ValueError('Unknown experiment arm')
    rule=ARMS[arm]['filter']
    if rule=='all':return True
    if rule=='body_05atr':return features['body_atr']>=.5
    if rule=='close_75pct':return features['directional_close_location']>=.75
    if rule=='break_previous3':return features['break_previous3'] is True
    raise ValueError('Unknown filter')


def replay(samples,candles,features,*,arm,start,end,units,purge_minutes=120):
    config=ARMS[arm];start,end=utc(start),utc(end)
    selected=[s for s in samples if start<=utc(s['entry_at'])<end-timedelta(minutes=purge_minutes)
              and accepts(features[s['sample_id']],arm)]
    signals={s['entry_at']:s for s in selected}
    if len(signals)!=len(selected):raise ValueError('Duplicate signals')
    engine=simulator(units);engine.config=replace(engine.config,max_holding_bars=config['holding_bars'])
    sessions=SessionEngine(SESSIONS);previous=None;overlaps=0
    for bar in candles:
        if not start<=bar.timestamp<end:continue
        gap=previous is not None and unexpected_broker_gap(previous,bar,300)
        sample=signals.get(bar.timestamp.isoformat())
        if sample and not gap:
            if engine.busy:overlaps+=1
            elif not engine.account_locked:
                c=sample['candidate'];candidate=Candidate(c['side'],c['entry'],c['stop'],c['target'],utc(c['expires_at']),tuple(c['evidence']))
                engine.submit(request_for(dict(candidate=candidate,snapshot=sample['snapshot'],signal_at=sample['signal_at']),sample['sample_id']))
        engine.advance(bar,data_valid=not gap,active_sessions=sessions.identify(bar.timestamp).active_sessions)
        previous=bar
    result=engine.summary();closed=[e for e in engine.events if e['status']=='closed']
    pnls=[e['financial_result']['net_pnl'] for e in closed]
    wins=sum(p>0 for p in pnls);loss=-sum(min(0,p) for p in pnls)
    result.update(arm=arm,candidate_signals=len(selected),overlap_skips=overlaps,
        win_rate_pct=100*wins/len(closed) if closed else None,
        win_rate_wilson_95_pct=wilson(wins,len(closed)),
        expectancy_usd=mean(pnls) if pnls else None,
        profit_factor=sum(max(0,p) for p in pnls)/loss if loss else None,
        unresolved_position=engine.busy,
        risk_reasons=dict(Counter(reason for e in engine.events if e['status']=='rejected' for reason in e.get('risk',{}).get('reasons',[]))),
        exit_reasons=dict(Counter(e['reason'] for e in closed)),
        wall_clock_extended=sum(e['duration_seconds']>config['holding_bars']*300 for e in closed),
        trades=[dict(sample_id=e['decision_id'],side=e['side'],entry_at=e['entry_at'],exit_at=e['observed_at'],
                     exit_reason=e['reason'],bars_held=e['bars_held'],duration_seconds=e['duration_seconds'],
                     financial_result=e['financial_result']) for e in closed])
    return result


def evaluate(samples,candles,features,manifest,progress=lambda *_:None):
    start,end=utc(manifest['first_label_at']),utc(manifest['as_of'])
    b1,b2=map(utc,manifest['boundaries'])
    periods={'all':(start,end),'development':(start,b1),'validation':(b1,b2),'final_previously_seen':(b2,end)}
    results={}
    for period,(a,b) in periods.items():
        results[period]={}
        for arm in ARMS:
            progress(dict(stage='portfolio',period=period,arm=arm))
            results[period][arm]=replay(samples,candles,features,arm=arm,start=a,end=b,
                units=float(manifest['lot'])*manifest['contract']['contract_size'])
    return results


def same_entry_exit_check(samples,candles,features,reference,manifest):
    """Paired exit-only diagnostic; each filled reference signal starts a fresh account."""
    from bisect import bisect_left
    stamps=[b.timestamp for b in candles];by_id={s['sample_id']:s for s in samples}
    output=[]
    for trade in reference['trades']:
        sample=by_id[trade['sample_id']];entry=utc(sample['entry_at']);i=bisect_left(stamps,entry)
        bars=candles[i:i+30]
        if not bars:raise ValueError('Paired entry missing')
        end=bars[-1].timestamp+timedelta(minutes=5)
        variants={}
        for arm in ('reference','holding_30min','holding_120min'):
            result=replay([sample],bars,features,arm=arm,start=entry,end=end,
                units=float(manifest['lot'])*manifest['contract']['contract_size'],purge_minutes=0)
            variants[arm]=dict(closed_trades=result['closed_trades'],net_pnl=result['net_pnl'],
                account_locked=result['account_locked'],unresolved_position=result['unresolved_position'],trades=result['trades'])
        output.append(dict(sample_id=sample['sample_id'],portfolio_reference_net=trade['financial_result']['net_pnl'],variants=variants))
    return output
