"""Offline trend/correction hypothesis. No live policy, SDK or model mutation."""
from collections import Counter
from datetime import timedelta

from .agent_research import SESSIONS, intelligence_session, request_for, simulator
from .agent_strategy import propose_pullback
from .broker_calendar import unexpected_broker_gap
from .entry_trend import entry_blocker
from .historical.core import utc
from .regime_study import candles_from
from .research_levels import ResearchLevels
from .sessions import SessionEngine
from .trend_experiment import wilson


PROTOCOL = dict(
    version='trend-with-correction-offline-v1',
    arms=['strict_current', 'strict_or_guarded_correction'],
    source_selection='largest compatible frozen training dataset by training_days then created_at, before outcomes',
    regeneration='all closed M5 bars; current expiry-fixed perception; no future candles',
    common='H4/H1 confirmed and aligned, original M5 pullback trigger, sessions, daily context, lot, stop, target, risk and costs',
    additional_entry_regimes=['UNKNOWN', 'TRANSITION'],
    range_entries=False,
    correction='prior three M5 bars: net close displacement opposite H1 and at least one opposite candle body',
    structural_guard='all four recent M5 closes remain strictly inside last confirmed H1 protected swing; confirmation known at signal time',
    resumption='current M5 closes past prior high/low, beyond EMA21 and with body in H1 direction; original propose_pullback must also pass',
    baseline_preserved='strict TREND entries unchanged; alternative only adds guarded corrections',
    geometry_threshold_changes=False,
    initial_equity_usd=10000, max_holding_m5_bars=12, daily_entry_limit=5,
    costs='observed spread, existing market-fill slippage 0.2 pip and commission USD35 per million per side',
    partition_policy='original chronological boundaries; independent accounts; no new entries in final 60 minutes of each partition',
    future_validation=False, live_policy_changed=False, orders_sent=0,
    timestral_training=False, adaptive_agent_reproduction=False,
    limitations=['Previously researched prices: no new independent holdout.',
                 'Fixed technical pullback comparison, not full adaptive live robot or Timestral ensemble.',
                 'Engineering definitions fixed before calculation, not formulas attributed to literature.',
                 'Win-rate intervals descriptive; trades may be temporally dependent.',
                 'No automatic production promotion from this experiment.'],
)


def phase(snapshot, history):
    """Use only closed bars and pivots confirmed before the observation."""
    if len(history) < 64:
        return dict(phase='INSUFFICIENT_DATA', allowed=False, reason='M5_CONTEXT_SHORT')
    trends=[snapshot.get(k) or {} for k in ('macro_trend','context_trend')]
    directions=[]
    for tr in trends:
        direction=tr.get('direction')
        expected={'bullish':'BULL_CONFIRMED','bearish':'BEAR_CONFIRMED'}.get(direction)
        if not expected or tr.get('state')!=expected or not tr.get('data_quality',{}).get('valid'):
            return dict(phase='CONTEXT_UNCONFIRMED',allowed=False,reason='HTF_CONFIRMATION_REQUIRED')
        directions.append(direction)
    if directions[0]!=directions[1]:
        return dict(phase='POTENTIAL_REVERSAL',allowed=False,reason='H4_H1_CONFLICT')
    if snapshot.get('regime_state',{}).get('missing_data'):
        return dict(phase='INSUFFICIENT_DATA',allowed=False,reason='REGIME_DATA_INVALID')
    if snapshot.get('invalidating_evidence'):
        return dict(phase='CONTEXT_INVALIDATED',allowed=False,reason='INVALIDATING_EVIDENCE')
    sign=1 if directions[0]=='bullish' else -1
    swing=trends[1].get('last_confirmed_low' if sign==1 else 'last_confirmed_high') or {}
    if not swing.get('price') or not swing.get('confirmed_at'):
        return dict(phase='INSUFFICIENT_DATA',allowed=False,reason='PROTECTED_SWING_MISSING')
    known_at=history[-1].timestamp+timedelta(minutes=5)
    if utc(swing['confirmed_at'])>known_at:
        return dict(phase='INSUFFICIENT_DATA',allowed=False,reason='FUTURE_SWING_REJECTED')
    if any(sign*(b.close-swing['price'])<=0 for b in history[-4:]):
        return dict(phase='POTENTIAL_REVERSAL',allowed=False,reason='H1_PROTECTED_SWING_BROKEN')
    prior=history[-4:-1]
    correction=(sign*(prior[-1].close-prior[0].close)<0 and
                any(sign*(b.close-b.open)<0 for b in prior))
    ema=history[-100:][0].close
    for b in history[-100:][1:]:ema+=2/22*(b.close-ema)
    previous,current=history[-2:]
    extreme=previous.high if sign==1 else previous.low
    resumed=(sign*(current.close-extreme)>0 and sign*(current.close-ema)>0 and
             sign*(current.close-current.open)>0)
    state='RESUMPTION' if correction and resumed else 'CORRECTION' if correction else (
        'IMPULSE' if sign*(current.close-prior[0].close)>0 else 'MIXED')
    allowed=(state=='RESUMPTION' and snapshot.get('regime') in {'UNKNOWN','TRANSITION'})
    return dict(phase=state,allowed=allowed,reason='GUARDED_CORRECTION' if allowed else 'NO_ADDITIONAL_ENTRY',
                direction=directions[0],protected_level=swing['price'])


def generate(rows, *, start, progress=lambda *_:None):
    session=intelligence_session();samples=[];counts=Counter();phases=Counter();regimes=Counter()
    original=session.observer.level_reader
    session.observer.level_reader=ResearchLevels(tolerance=original.tolerance,
        ttl_bars=original.ttl_bars,swing_window=original.swing_window)
    start=utc(start)
    for i,row in enumerate(rows):
        if i%500==0:progress(dict(stage='replaying_closed_candles',processed=i,total=len(rows)))
        snap=session.update([row],spread_pips=row.get('spread_pips'),
                            observed_at=utc(row['timestamp'])+timedelta(minutes=5))
        if utc(row['timestamp'])<start:continue
        regimes[snap.regime]+=1
        setup,reason=propose_pullback(snap,session.history,daily_history=session.aggregator.history['D1'],research=True)
        if not setup:
            counts[reason or 'NO_SETUP']+=1;continue
        snapshot=setup['snapshot'];p=phase(snapshot,session.history)
        phases[p['phase']]+=1
        side=setup['candidate'].side
        expected='long' if p.get('direction')=='bullish' else 'short' if p.get('direction')=='bearish' else None
        strict=entry_blocker(snapshot,side) is None
        extra=p['allowed'] and side==expected
        counts['technical_candidates']+=1
        counts['strict_signals']+=strict;counts['additional_guarded_signals']+=extra
        if not strict and not extra:
            counts['candidate_block:'+p['reason']]+=1;continue
        # Retain the original regime and structural evidence. Never label UNKNOWN as TREND.
        compact={k:snapshot[k] for k in ('snapshot_id','session','regime','context_trend','macro_trend')}
        candidate=setup['candidate']
        samples.append(dict(sample_id='correction:'+setup['signal_at'],signal_at=setup['signal_at'],
            entry_at=setup['signal_at'],snapshot=compact,phase=p,
            arms=['strict_current','strict_or_guarded_correction'] if strict else ['strict_or_guarded_correction'],
            candidate=dict(side=side,entry=candidate.entry,stop=candidate.stop,target=candidate.target,
                           expires_at=candidate.expires_at.isoformat(),evidence=list(candidate.evidence))))
    return samples,dict(candidates=dict(counts),phases=dict(phases),phase_count_scope='technical candidates only',regimes=dict(regimes))


def replay(samples,candles,*,arm,start,end,units):
    from .domain import Candidate
    start,end=utc(start),utc(end);cutoff=end-timedelta(hours=1)
    selected=[s for s in samples if arm in s['arms'] and start<=utc(s['entry_at'])<cutoff]
    signals={s['entry_at']:s for s in selected}
    if len(signals)!=len(selected):raise ValueError('Duplicate entry timestamps')
    engine=simulator(units);sessions=SessionEngine(SESSIONS);previous=None;overlaps=0
    for bar in candles:
        if not start<=bar.timestamp<end:continue
        # Exposure through unexpected missing tradable bars must not earn a reliable outcome.
        gap=previous is not None and unexpected_broker_gap(previous,bar,300)
        sample=signals.get(bar.timestamp.isoformat())
        if sample and not gap:
            if engine.busy:overlaps+=1
            elif not engine.account_locked:
                c=sample['candidate']
                candidate=Candidate(c['side'],c['entry'],c['stop'],c['target'],utc(c['expires_at']),tuple(c['evidence']))
                engine.submit(request_for(dict(candidate=candidate,snapshot=sample['snapshot'],signal_at=sample['signal_at']),sample['sample_id']))
        engine.advance(bar,data_valid=not gap,active_sessions=sessions.identify(bar.timestamp).active_sessions)
        previous=bar
    result=engine.summary();closed=[e for e in engine.events if e['status']=='closed']
    pnls=[e['financial_result']['net_pnl'] for e in closed]
    gains=sum(max(0,p) for p in pnls);losses=-sum(min(0,p) for p in pnls)
    result.update(candidate_signals=len(selected),overlap_skips=overlaps,
        win_rate_pct=100*result['wins']/len(closed) if closed else None,
        win_rate_wilson_95_pct=wilson(result['wins'],len(closed)),
        expectancy_usd=sum(pnls)/len(pnls) if pnls else None,
        profit_factor=gains/losses if losses else None,unresolved_position=engine.busy,
        rejection_reasons=dict(Counter(e.get('reason','unknown') for e in engine.events if e['status']=='rejected')),
        trades=[dict(sample_id=e['decision_id'],side=e['side'],entry_at=e['entry_at'],
                     exit_at=e['observed_at'],net_pnl=e['financial_result']['net_pnl']) for e in closed])
    return result


def evaluate(rows,samples,manifest):
    start,end=utc(manifest['first_label_at']),utc(manifest['as_of'])
    b1,b2=map(utc,manifest['boundaries']);candles=candles_from(rows)
    periods={'all':(start,end),'development':(start,b1),'validation':(b1,b2),'final_previously_seen':(b2,end)}
    return {name:{arm:replay(samples,candles,arm=arm,start=a,end=b,
                            units=float(manifest['lot'])*manifest['contract']['contract_size'])
                  for arm in PROTOCOL['arms']} for name,(a,b) in periods.items()}
