"""Isolated expiry/threshold experiments. No broker or live control imports."""
import copy
from collections import Counter
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from .agent_research import intelligence_session
from .agent_strategy import propose_pullback
from .broker_calendar import unexpected_broker_gap
from .domain import Candle
from .historical.core import utc
from .regime import MarketRegimeEngine, RegimeConfig
from .trend_experiment import replay


def configurations():
    fixed=RegimeConfig()
    return dict(legacy=replace(fixed,regime_model_version='0.1.0-research',transition_expiry_policy='legacy_research_v0'),
                expiry_fixed=fixed,efficiency55=replace(fixed,trend_efficiency_min=.55),
                confirmations2=replace(fixed,confirmation_bars=2))


def candles_from(rows):
    return [Candle(utc(r['timestamp']),*(r[k] for k in ('open','high','low','close')),
                   r.get('volume',0),r.get('spread_pips')) for r in rows]


def classify(rows,*,start):
    engines={k:MarketRegimeEngine(v) for k,v in configurations().items()}
    agg=intelligence_session().aggregator;previous=None;last=None;h1=[]
    maps={k:{} for k in engines};counts={k:Counter() for k in engines};activations={k:[] for k in engines}
    seen={k:set() for k in engines}
    for bar in candles_from(rows):
        if previous and unexpected_broker_gap(previous,bar,300):
            agg.reset();last=None
            for engine in engines.values():engine.reset()
        histories=agg.add(bar);previous=bar
        if not histories['H1'] or histories['H1'][-1].timestamp==last:continue
        last=histories['H1'][-1].timestamp;h1.append(histories['H1'][-1])
        for name,engine in engines.items():
            state=engine.evaluate(histories['H1'],symbol='EURUSD',timeframe='H1',
                now=bar.timestamp+timedelta(minutes=5),snapshot_id='study')
            maps[name][(last+timedelta(hours=1)).isoformat()]=dict(regime=state.regime,
                regime_config_hash=engine.config_hash,regime_model_version=engine.config.regime_model_version)
            if last<utc(start):continue
            counts[name][state.regime]+=1
            counts[name]['expired_transition_incoherence']+=int(state.regime=='TRANSITION' and state.transition_status=='EXPIRED')
            b=state.breakout
            if state.regime=='TREND' and b.get('current_status')=='CONFIRMED' and b['breakout_id'] not in seen[name]:
                seen[name].add(b['breakout_id'])
                activations[name].append(dict(at=last.isoformat(),level=b['breakout_level'],direction=b['direction']))
    failures={}
    for name,events in activations.items():
        co=Counter(activations=len(events),evaluated=0,failed=0,pending=0)
        for event in events:
            following=[b for b in h1 if b.timestamp>utc(event['at'])][:8]
            if (len(following)!=8 or
                (following and unexpected_broker_gap(SimpleNamespace(timestamp=utc(event['at'])),following[0],3600)) or
                any(unexpected_broker_gap(a,b,3600) for a,b in zip(following,following[1:]))):
                co['pending']+=1;continue
            co['evaluated']+=1
            co['failed']+=int(any(b.close<=event['level'] if event['direction']=='BULLISH' else b.close>=event['level'] for b in following))
        failures[name]=dict(co,failure_rate_pct=100*co['failed']/co['evaluated'] if co['evaluated'] else None)
    return maps,counts,failures


def project(samples,mapping):
    output=[]
    for sample in samples:
        s=copy.deepcopy(sample);stamp=s['snapshot'].get('context_trend',{}).get('timestamp_utc')
        state=mapping.get(stamp)
        if state:s['snapshot'].update(state)
        else:s['snapshot']['regime']='UNKNOWN'
        output.append(s)
    return output


def evaluate(rows,samples,*,start,end,lot,contract):
    maps,counts,failures=classify(rows,start=start);candles=candles_from(rows)
    results={}
    for name,mapping in maps.items():
        projected=project(samples,mapping)
        results[name]=dict(regimes=dict(counts[name]),breakout_followthrough=failures[name],
            portfolios={direction:replay(projected,candles,policy=direction,start=start,end=end,
                         units=float(lot)*contract['contract_size']) for direction in ('h4_h1','h1')})
    return results


def recent_candidates(rows,*,start,progress=lambda *_:None):
    session=intelligence_session();samples=[]
    for i,row in enumerate(rows):
        if i%1000==0:progress(dict(processed=i,total=len(rows)))
        snapshot=session.update([row],spread_pips=row.get('spread_pips'),
            observed_at=utc(row['timestamp'])+timedelta(minutes=5))
        if utc(row['timestamp'])<utc(start):continue
        setup,reason=propose_pullback(snapshot,session.history,daily_history=session.aggregator.history['D1'],research=True)
        if reason or not setup:continue
        c=setup['candidate']
        samples.append(dict(sample_id='regime-study:'+setup['signal_at'],signal_at=setup['signal_at'],
            entry_at=setup['signal_at'],snapshot=setup['snapshot'],candidate=dict(side=c.side,entry=c.entry,
                stop=c.stop,target=c.target,expires_at=c.expires_at.isoformat(),evidence=list(c.evidence))))
    return samples
