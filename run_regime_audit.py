"""Offline regime sensitivity and causal example charts; no live changes.

Install requirements-research.txt before running from the project directory.
"""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from collections import Counter

def main():
    from datetime import timedelta
    from dataclasses import replace,asdict
    from aurelia_fx.storage import open_memory
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.domain import Candle
    from aurelia_fx.agent_research import intelligence_session
    from aurelia_fx.regime import MarketRegimeEngine,RegimeConfig
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    m=open_memory()
    with m.pool.connection() as c:
     d=json.loads(c.execute("SELECT payload_json FROM project_records WHERE record_type='agent_training_dataset' AND record_key='661f1b42-0b1d-4066-a145-85f8cd0334ae' LIMIT 1").fetchone()['payload_json'])
     ss=[json.loads(r['payload_json']) for r in c.execute("SELECT payload_json FROM project_records WHERE record_type='agent_training_sample' AND record_key=ANY(%s)",(d['sample_ids'],)).fetchall()]
     b=json.loads(c.execute("SELECT payload_json FROM project_records WHERE record_type='agent_training_history' AND record_key=%s LIMIT 1",(d['manifest']['baseline_id'],)).fetchone()['payload_json'])
    counts=Counter();missing=Counter()
    for s in ss:
     x=s['snapshot'];r=x['regime_state'];f=r.get('features',{});rg=x['regime'];counts['regime:'+rg]+=1
     missing.update(r.get('missing_data',[]))
     for label,cond in [('efficiency_pass',f.get('efficiency',-1)>=.65),('extremes_pass',f.get('directional_extremes_fraction',-1)>=.5),('raw_trend',f.get('candidate')=='TREND'),('raw_trend_not_TREND',f.get('candidate')=='TREND' and rg!='TREND'),('stored_range',bool(r.get('range_state'))),('H1confirmed',x.get('context_trend',{}).get('state') in ['BULL_CONFIRMED','BEAR_CONFIRMED'])]:counts[label]+=int(cond)
     if rg=='TRANSITION':
      counts['transition:'+r.get('subtype','')]+=1
      counts['transition_status:'+r.get('transition',{}).get('status','none')]+=1
     if rg=='UNKNOWN':counts['unknown:'+r.get('classification_status','')]+=1
    print(json.dumps(dict(stage='catalog',counts=counts,missing=missing)),flush=True)
    frozen,rows=HistoricalRepository(m).frozen_candles(b,record_type='agent_training_history')
    base=RegimeConfig(regime_model_version="0.1.0-research",transition_expiry_policy="legacy_research_v0");variants={'base':base,'eff55':replace(base,trend_efficiency_min=.55),'eff50':replace(base,trend_efficiency_min=.50),'confirm2':replace(base,confirmation_bars=2),'range60':replace(base,range_lifetime_bars=60),'combined_exploratory':replace(base,trend_efficiency_min=.55,trend_extreme_fraction_min=.45,confirmation_bars=2)}
    engines={k:MarketRegimeEngine(v) for k,v in variants.items()};full={k:Counter() for k in variants};candidate_map={k:{} for k in variants};last_h1=None;agg=intelligence_session().aggregator;previous=None;h1s=[]
    for row in rows:
     bar=Candle(utc(row['timestamp']),*(row[k] for k in ['open','high','low','close']),row.get('volume',0),row.get('spread_pips'))
     if previous and unexpected_broker_gap(previous,bar,300):
      agg.reset();last_h1=None
      for engine in engines.values():engine.reset()
     histories=agg.add(bar);previous=bar
     if not histories['H1'] or histories['H1'][-1].timestamp==last_h1:continue
     last_h1=histories['H1'][-1].timestamp;h1s.append(histories['H1'][-1])
     for k,engine in engines.items():
      r=engine.evaluate(histories['H1'],symbol='EURUSD',timeframe='H1',now=bar.timestamp+timedelta(minutes=5),snapshot_id='audit')
      candidate_map[k][last_h1.isoformat()]=r.regime
      if last_h1>=utc(d['manifest']['first_label_at']):
       full[k]['regime:'+r.regime]+=1
       for why in r.missing_data:full[k]['missing:'+why]+=1
       if r.features:
        full[k]['efficiency_pass']+=int(r.features['efficiency']>=variants[k].trend_efficiency_min)
        full[k]['raw_trend']+=int(r.features['candidate']=='TREND')
    print(json.dumps(dict(stage='full_H1',counts=full)),flush=True)
    Path('data/reports/audit-h1-map.json').write_text(json.dumps(dict(full=full,candidate_map=candidate_map,h1s=[dict(timestamp=z.timestamp.isoformat(),open=z.open,high=z.high,low=z.low,close=z.close,volume=z.volume,spread_pips=z.spread_pips) for z in h1s])),encoding='utf-8')
    # Candidate classifications projected from closed H1 snapshots, without relabeling originals.
    sensitivity={}
    for k in variants:
     co=Counter()
     for s in ss:
      x=s['snapshot'];stamp=x.get('context_trend',{}).get('timestamp_utc')
      rg=candidate_map[k].get((utc(stamp)-timedelta(hours=1)).isoformat(),'UNAVAILABLE') if stamp else 'UNAVAILABLE';co['regime:'+rg]+=1
      side=s['candidate']['side'];tr=x.get('context_trend',{});match=(tr.get('direction'),tr.get('state'))=={'long':('bullish','BULL_CONFIRMED'),'short':('bearish','BEAR_CONFIRMED')}.get(side)
      co['H1_eligible']+=int(rg=='TREND' and match)
      macro=x.get('macro_trend',{});co['H4H1_eligible']+=int(rg=='TREND' and match and macro.get('direction')==tr.get('direction') and macro.get('state')==tr.get('state'))
      if k=='base':co['matches_saved']+=int(rg==x['regime'])
     sensitivity[k]=co
    print(json.dumps(dict(stage='sensitivity',counts=sensitivity)),flush=True)
    # Deterministic contrasting examples, selected by classification and geometry, never PnL.
    selected=[]
    for regime in ['TREND','RANGE','TRANSITION','UNKNOWN']:
     pool=[s for s in ss if s['snapshot']['regime']==regime and s['snapshot']['regime_state'].get('features') and s['snapshot'].get('context_trend',{}).get('state') in ['BULL_CONFIRMED','BEAR_CONFIRMED']]
     pool.sort(key=lambda s:s['snapshot']['regime_state']['features'].get('efficiency',0),reverse=True)
     if pool:selected.append(pool[0])
    import os
    os.environ['MPLCONFIGDIR']=str(Path('data/reports/.mpl-cache').resolve())
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig,axs=plt.subplots(len(selected),1,figsize=(13,3.8*len(selected)),layout='constrained')
    examples=[]
    for ax,s in zip(axs,selected):
     x=s['snapshot'];r=x['regime_state'];f=r['features'];at=utc(s['signal_at']);bars=[z for z in h1s if z.timestamp+timedelta(hours=1)<=at][-60:]
     for i,z in enumerate(bars):
      color='#147d60' if z.close>=z.open else '#c74657';ax.vlines(i,z.low,z.high,color=color,lw=.8);ax.add_patch(Rectangle((i-.3,min(z.open,z.close)),.6,max(abs(z.close-z.open),.000002),color=color))
     if len(bars)>=20:ax.axvspan(len(bars)-20-.5,len(bars)-.5,color='#739cf1',alpha=.12,label='20-bar measurement window')
     if r.get('range_state'):
      for field in ['lower_boundary','upper_boundary']:ax.axhline(r['range_state'][field],color='#b18115',ls='--',lw=1)
     ax.set_title(f"{s['signal_at']} UTC | saved={x['regime']} | H1={x['context_trend']['state']} | efficiency={f['efficiency']:.3f} | extremes={f['directional_extremes_fraction']:.3f}",fontsize=10)
     ax.set_xticks(range(0,len(bars),10),[z.timestamp.strftime('%d/%m %Hh') for z in bars[::10]],fontsize=8);ax.grid(alpha=.15);ax.set_ylabel('EUR/USD')
     examples.append(dict(sample_id=s['sample_id'],signal_at=s['signal_at'],regime=x['regime'],H1=x['context_trend']['state'],features={a:f.get(a) for a in ['efficiency','directional_extremes_fraction','candidate','candidate_observations']},range=r.get('range_state'),transition=r.get('transition')))
    out=Path('data/reports');out.mkdir(exist_ok=True)
    fig.savefig(out/'regime-audit-examples.png',dpi=140)
    assert sensitivity['base']['matches_saved']==len(ss), 'Replay differs from saved classifications; do not interpret alternatives'
    report=dict(source_run_id=d['run_id'],parameters={k:asdict(v) for k,v in variants.items()},catalog_counts=counts,missing=missing,full_H1=full,sensitivity=sensitivity,examples=examples,live_policy_changed=False)
    report['audit_id']=fingerprint(report);m.record_project_data('agent_regime_audit',report['audit_id'],report)
    (out/'regime-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(dict(audit_id=report['audit_id'],examples=examples)),flush=True);m.close()

if __name__=="__main__":main()
