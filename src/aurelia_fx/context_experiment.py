"""Causal context diagnostics and fixed filters on sealed correction signals."""
from collections import Counter
from datetime import timedelta
from statistics import mean,median

from .agent_research import intelligence_session
from .broker_calendar import unexpected_broker_gap
from .historical.core import utc
from .structure import analyze_structure
from .trigger_exit_experiment import replay


SOURCE='6ba3f9946d64314f98f0d1181967b64e9a9ec2d675fe1967f37d78152caf392f'
ARMS=('reference','prior_h1_impulse','m5_impulse_shallow_correction','known_h1_room_to_target')
PROTOCOL=dict(version='pre-entry-context-v1',source_report=SOURCE,arms=ARMS,
    h1_impulse='last 3 H1 bars CLOSED BEFORE correction starts: directional open-to-close progress >=1 ATR; ATR14 computed before that leg',
    m5_context='6 M5 bars immediately before 3 correction bars: directional progress >=1 ATR14 computed before that six-bar leg, then positive wick retracement <=50 percent of impulse excursion',
    h1_room='nearest confirmed H1 swing in profit direction at signal time is at or beyond the unchanged target; unknown obstacle map fails filter',
    separation='three isolated filters, never combined, no threshold search or post-result calibration',
    clock='correction is the three closed M5 bars preceding the trigger; an H1 bar containing that correction cannot establish the earlier impulse',
    fixed='same 107 sealed signals, original H4/H1 direction, entry, stop, 2.5R target, lot .01, costs, risk, 12-bar holding and 120-minute common boundary purge',
    diagnostic='compare features of reference-filled winners and losses; descriptive associations are not causal proof',
    source_selection='reuse exact sealed source from previous investigation, not selection by profitability',
    data_status='known retrospective history through20Oct2026; no new independent holdout',
    obstacle_limit='confirmed swing proxy; no claim that every old pivot remains an active support/resistance',
    live_policy_changed=False,orders_sent=0,automatic_promotion=False)


def atr(bars):
    if len(bars)!=15:return None
    return mean(max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(bars,bars[1:]))


def directional_leg(bars,sign,scale):
    if not bars or not scale or scale<=0:return None,None
    displacement=sign*(bars[-1].close-bars[0].open)
    path=abs(bars[0].close-bars[0].open)+sum(abs(b.close-a.close) for a,b in zip(bars,bars[1:]))
    return displacement/scale,abs(displacement)/path if path else 0.


def context_for(sample,m5,h1):
    signal=utc(sample['signal_at'])
    if utc(sample['entry_at'])!=signal:raise ValueError('Sealed entry is not the signal close')
    if len(m5)<25 or m5[-1].timestamp+timedelta(minutes=5)!=signal:
        raise ValueError('Missing closed M5 context')
    if any(b.timestamp+timedelta(hours=1)>signal for b in h1):raise ValueError('Future H1 context')
    if any(unexpected_broker_gap(a,b,300) for a,b in zip(m5[-25:],m5[-24:])):
        raise ValueError('Missing tradable M5 feature candles')
    side=sample['candidate']['side'];sign=1 if side=='long' else -1
    expected={'long':('bullish','BULL_CONFIRMED'),'short':('bearish','BEAR_CONFIRMED')}.get(side)
    for role in ('macro_trend','context_trend'):
        tr=sample['snapshot'].get(role,{})
        if not expected or (tr.get('direction'),tr.get('state'))!=expected:
            raise ValueError('Context direction violates sealed H4/H1 policy')
        if tr.get('timestamp_utc') and utc(tr['timestamp_utc'])>signal:raise ValueError('Future trend state')
    if abs(m5[-1].close-sample['candidate']['entry'])>1e-12:raise ValueError('Changed signal candle')
    correction=m5[-4:-1];correction_start=correction[0].timestamp
    prior_h1=[b for b in h1 if b.timestamp+timedelta(hours=1)<=correction_start]
    h1_ready=(len(prior_h1)>=18 and not any(unexpected_broker_gap(a,b,3600)
               for a,b in zip(prior_h1[-18:],prior_h1[-17:])))
    h1_scale=atr(prior_h1[-18:-3]) if h1_ready else None
    h1_progress,h1_eff=directional_leg(prior_h1[-3:],sign,h1_scale) if h1_ready else (None,None)
    impulse=m5[-10:-4];m5_scale=atr(m5[-25:-10])
    m5_progress,m5_eff=directional_leg(impulse,sign,m5_scale)
    peak=max(b.high for b in impulse) if sign==1 else min(b.low for b in impulse)
    excursion=sign*(peak-impulse[0].open)
    depth=peak-min(b.low for b in correction) if sign==1 else max(b.high for b in correction)-peak
    retracement=depth/excursion if excursion>0 else None
    structure=analyze_structure(h1,2,bar_seconds=3600)
    opposite=[s for s in structure.swings if s.kind==('high' if sign==1 else 'low')
              and utc(s.confirmed_at)<=signal and sign*(s.price-sample['candidate']['entry'])>0]
    nearest=min(opposite,key=lambda s:abs(s.price-sample['candidate']['entry'])) if opposite else None
    distance=abs(sample['candidate']['entry']-sample['candidate']['stop'])
    room=abs(nearest.price-sample['candidate']['entry'])/distance if nearest and distance>0 else None
    target_r=abs(sample['candidate']['target']-sample['candidate']['entry'])/distance if distance>0 else None
    protected=sample['snapshot']['context_trend'].get('last_confirmed_low' if sign==1 else 'last_confirmed_high') or {}
    age=(signal-utc(protected['confirmed_at'])).total_seconds()/3600 if protected.get('confirmed_at') else None
    return dict(known_at=signal.isoformat(),correction_start=correction_start.isoformat(),
        h1_prior_leg_end=(prior_h1[-1].timestamp+timedelta(hours=1)).isoformat() if prior_h1 else None,
        h1_impulse_atr=h1_progress,h1_efficiency=h1_eff,h1_context_ready=h1_ready,
        m5_prior_leg_end=(impulse[-1].timestamp+timedelta(minutes=5)).isoformat(),
        m5_impulse_atr=m5_progress,m5_efficiency=m5_eff,m5_retracement=retracement,
        h1_room_r=room,target_r=target_r,opposing_level=nearest.price if nearest else None,
        level_confirmed_at=nearest.confirmed_at if nearest else None,protected_swing_age_hours=age,
        source_regime=sample['snapshot']['regime'])


def features(samples,candles,progress=lambda *_:None):
    targets={utc(s['signal_at']):s for s in samples}
    if len(targets)!=len(samples):raise ValueError('Duplicate sealed signal times')
    aggregator=intelligence_session().aggregator;previous=None;output={}
    for i,bar in enumerate(candles):
        if i%10000==0:progress(dict(stage='closed_context',processed=i,total=len(candles)))
        if previous and unexpected_broker_gap(previous,bar,300):aggregator.reset()
        histories=aggregator.add(bar);previous=bar
        sample=targets.get(bar.timestamp+timedelta(minutes=5))
        if not sample:continue
        for role,tf,hours in [('macro_trend','H4',4),('context_trend','H1',1)]:
            stamp=sample['snapshot'][role].get('timestamp_utc')
            if not histories[tf] or utc(stamp)!=histories[tf][-1].timestamp+timedelta(hours=hours):
                raise ValueError('Reconstructed closed HTF differs from sealed observation')
        output[sample['sample_id']]=context_for(sample,list(histories['M5']),list(histories['H1']))
    if len(output)!=len(samples):raise ValueError('Missing sealed contexts')
    return output


def passes(f,arm):
    if arm=='reference':return True
    if arm=='prior_h1_impulse':return f['h1_impulse_atr'] is not None and f['h1_impulse_atr']>=1
    if arm=='m5_impulse_shallow_correction':
        return f['m5_impulse_atr'] is not None and f['m5_impulse_atr']>=1 and f['m5_retracement'] is not None and 0<f['m5_retracement']<=.5
    if arm=='known_h1_room_to_target':
        return f['h1_room_r'] is not None and f['target_r'] is not None and f['h1_room_r']+1e-12>=f['target_r']
    raise ValueError('Unknown context hypothesis')


def evaluate(samples,candles,values,manifest,progress=lambda *_:None):
    start,end=utc(manifest['first_label_at']),utc(manifest['as_of']);b1,b2=map(utc,manifest['boundaries'])
    periods={'all':(start,end),'development':(start,b1),'validation':(b1,b2),'final_previously_seen':(b2,end)}
    neutral={s['sample_id']:{} for s in samples};output={}
    for period,(a,b) in periods.items():
        output[period]={}
        for arm in ARMS:
            progress(dict(stage='portfolio',period=period,arm=arm))
            selected=[s for s in samples if passes(values[s['sample_id']],arm)]
            r=replay(selected,candles,neutral,arm='reference',start=a,end=b,
                units=float(manifest['lot'])*manifest['contract']['contract_size'])
            r['arm']=arm;output[period][arm]=r
    return output


def diagnostics(reference,values):
    trades=reference['trades'];output={}
    for arm in ARMS:
        output[arm]={}
        for label,keep in [('pass',True),('fail',False)]:
            group=[t for t in trades if passes(values[t['sample_id']],arm)==keep]
            pnls=[t['financial_result']['net_pnl'] for t in group]
            output[arm][label]=dict(n=len(group),wins=sum(p>0 for p in pnls),losses=sum(p<0 for p in pnls),net_pnl=sum(pnls))
    summary={}
    for name,group in [('winners',[t for t in trades if t['financial_result']['net_pnl']>0]),
                       ('losses',[t for t in trades if t['financial_result']['net_pnl']<0])]:
        summary[name]=dict(n=len(group))
        for field in ('h1_impulse_atr','m5_impulse_atr','m5_retracement','h1_room_r','protected_swing_age_hours'):
            numbers=[values[t['sample_id']][field] for t in group if values[t['sample_id']][field] is not None]
            summary[name][field]=dict(n=len(numbers),median=median(numbers) if numbers else None)
    return dict(fixed_reference_trade_groups=output,feature_medians=summary,
        signal_sides=dict(Counter(t['side'] for t in trades)),scope='descriptive, reference fills only; not portfolio effects or calibrated prediction')
