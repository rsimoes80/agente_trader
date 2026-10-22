"""Offline paired replay of frozen candidates; never changes the live entry policy."""
from collections import Counter
from datetime import timedelta
from math import sqrt

from .agent_research import SESSIONS, request_for, simulator
from .domain import Candidate
from .entry_trend import entry_blocker
from .historical.core import utc
from .sessions import SessionEngine


def eligible(sample, policy):
    if policy not in ('h4_h1', 'h1'):
        raise ValueError('Unknown experiment policy')
    snapshot=sample['snapshot']
    side=sample['candidate']['side']
    if policy=='h4_h1':
        return entry_blocker(snapshot,side) is None
    # Only remove the H4 requirement. Regime, H1 confirmation and side stay fixed.
    context=snapshot.get('context_trend') or {}
    expected={'long':('bullish','BULL_CONFIRMED'),'short':('bearish','BEAR_CONFIRMED')}.get(side)
    return snapshot.get('regime')=='TREND' and expected is not None and (
        context.get('direction'),context.get('state'))==expected


def wilson(wins,n):
    if not n:return None
    z=1.96;p=wins/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [100*(center-half),100*(center+half)]


def replay(samples,candles,*,policy,start,end,units):
    start,end=utc(start),utc(end)
    # Leave the common 12-bar holding window before each fixed period boundary.
    cutoff=end-timedelta(minutes=60)
    candidates=[s for s in samples if start<=utc(s['entry_at'])<cutoff and eligible(s,policy)]
    signals={s['entry_at']:s for s in candidates}
    if len(signals)!=len(candidates):raise ValueError('Duplicate entry timestamps')
    engine=simulator(units);sessions=SessionEngine(SESSIONS)
    overlaps=0
    for bar in candles:
        if not start<=bar.timestamp<end:continue
        sample=signals.get(bar.timestamp.isoformat())
        if sample:
            if engine.busy:overlaps+=1
            elif not engine.account_locked:
                c=sample['candidate']
                candidate=Candidate(c['side'],c['entry'],c['stop'],c['target'],utc(c['expires_at']),tuple(c['evidence']))
                engine.submit(request_for(dict(candidate=candidate,snapshot=sample['snapshot'],signal_at=sample['signal_at']),sample['sample_id']))
        engine.advance(bar,data_valid=True,active_sessions=sessions.identify(bar.timestamp).active_sessions)
    result=engine.summary()
    closed=[e for e in engine.events if e['status']=='closed']
    pnls=[e['financial_result']['net_pnl'] for e in closed]
    gain=sum(max(0,p) for p in pnls);loss=-sum(min(0,p) for p in pnls)
    result.update(policy=policy,candidate_signals=len(candidates),overlap_skips=overlaps,
        win_rate_pct=100*result['wins']/len(closed) if closed else None,
        win_rate_wilson_95_pct=wilson(result['wins'],len(closed)),
        expectancy_usd=sum(pnls)/len(pnls) if pnls else None,
        profit_factor=gain/loss if loss else None,
        unresolved_position=engine.busy,
        rejection_reasons=dict(Counter(e.get('reason','unknown') for e in engine.events if e['status']=='rejected')),
        trades=[dict(sample_id=e['decision_id'],side=e['side'],entry_at=e['entry_at'],
                     exit_at=e['observed_at'],net_pnl=e['financial_result']['net_pnl']) for e in closed])
    return result


def compare(samples,candles,manifest):
    start=utc(manifest['first_label_at']);end=utc(manifest['as_of'])
    b1,b2=map(utc,manifest['boundaries'])
    periods={'all':(start,end),'development':(start,b1),'validation':(b1,b2),'final_previously_seen':(b2,end)}
    return {name:{policy:replay(samples,candles,policy=policy,start=a,end=b,
                               units=float(manifest['lot'])*manifest['contract']['contract_size'])
                  for policy in ('h4_h1','h1')} for name,(a,b) in periods.items()}
