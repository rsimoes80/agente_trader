"""Small fixed 5M-model timeframe comparison; offline research, never orders."""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))

SPEC=dict(version='timestral-timeframe-pilot-v1',timeframes={'M5':300,'M15':900,'H1':3600},
    context=64,horizon=6,decision_time='09:00 Europe/London, weekdays, exact closed bar',
    gaps='Known market closures allowed in trading-bar sequence; unexpected M5 gaps reset all contexts',
    family='Direct median direction, with and without median displacement exceeding estimated round-trip cost',
    stop_atr=1.5,target_r=3.,holding='6 execution bars, managed on original M5 candles',
    costs='Observed spread, slippage .2pip/market side, USD35/million/side assumption',
    risk='Existing .01lot/10k account/.5pct trade/2pct day/5pct DD/max5day/maxspread2/minnetRR2',
    split='2026-07-01 UTC; common six-hour boundary purge; known-session end exit with5minutebuffer',
    selection='Only M15/H1: development>=50closed,net>0,PF>=1.1,clean; rank expectancy, no negative winner',
    confirmation='Selected check>=30closed,net>0,PF>=1.1,stresspositive,clean. Prospective confirmation still required.',
    data_status='Historical data previously researched; not new independent OOS',
    activation=False,orders_sent=0,weights_changed=False)


def opportunities(candles,start):
    from aurelia_fx.agent_research import intelligence_session,SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap,slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.agent_model import fingerprint
    agg=intelligence_session().aggregator;sessions=SessionEngine(SESSIONS)
    previous=None;result=[];london=ZoneInfo('Europe/London')
    for bar in candles:
        if previous and unexpected_broker_gap(previous,bar,300):agg.reset()
        histories=agg.add(bar);previous=bar;known=bar.timestamp+timedelta(minutes=5)
        local=known.astimezone(london)
        if known<start or local.weekday()>4 or (local.hour,local.minute)!=(9,0) or not slot_tradable(known):continue
        active=list(sessions.identify(known).active_sessions)
        if not active:continue
        for tf,seconds in SPEC['timeframes'].items():
            history=histories[tf]
            if len(history)<SPEC['context'] or history[-1].timestamp+timedelta(seconds=seconds)!=known:continue
            context=history[-SPEC['context']:]
            atr=sum(max(b.high-b.low,abs(b.high-a.close),abs(b.low-a.close)) for a,b in zip(context[-15:-1],context[-14:]))/14
            if atr<=0:continue
            result.append(dict(timeframe=tf,signal_at=known.isoformat(),reference=context[-1].close,
                spread_pips=bar.spread_pips,atr=atr,session=active,
                context_sha=fingerprint([c.as_dict() for c in context]),values=[c.close for c in context]))
    return result


def signal(case,output,*,cost_gate):
    from aurelia_fx.historical.core import utc
    q=output['quantiles'][SPEC['horizon']-1]
    if (len(q)!=3 or not all(__import__('math').isfinite(v) and v>0 for v in q) or q!=sorted(q)):
        raise ValueError('Invalid pinned-model quantiles')
    delta=q[1]-case['reference'];sign=1 if delta>1e-10 else -1 if delta< -1e-10 else 0
    if not sign:return None
    spread=case['spread_pips']
    if spread is None or not __import__('math').isfinite(spread) or spread<0:return None
    if cost_gate and abs(delta)<=(spread+.4+.7)*.0001:return None
    entry=case['reference'];distance=SPEC['stop_atr']*case['atr'];known=utc(case['signal_at'])
    sid=f"timestral5m:{case['timeframe']}:{'cost' if cost_gate else 'raw'}:{case['signal_at']}"
    return dict(sample_id=sid,signal_at=case['signal_at'],entry_at=case['signal_at'],
        snapshot=dict(snapshot_id=sid,session=case['session'],regime='TIMESTRAL_TIMEFRAME_RESEARCH'),
        candidate=dict(side='long' if sign>0 else 'short',entry=entry,stop=entry-sign*distance,
            target=entry+sign*SPEC['target_r']*distance,expires_at=(known+timedelta(minutes=5)).isoformat(),
            evidence=['pinned5M_median_direction','closed_'+case['timeframe']+'_context']))


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.forecasting.config import TimestralConfig
    from aurelia_fx.forecasting.adapter import TimestralAdapter
    from aurelia_fx.training.proof import SOURCE_MODEL,SOURCE_REVISION,SDK_REVISION
    from run_literature_experiment import simulate,choose
    import psutil
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume');args=parser.parse_args()
    memory=open_memory();adapter=None
    def read(kind,key):
        with memory.pool.connection() as c:
            row=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if not row:return None
        d=json.loads(row['payload_json'])
        if memory._encode(d)[1]!=row['payload_sha256']:raise ValueError('Immutable research record changed')
        return d
    try:
        dataset=read('agent_training_dataset','661f1b42-0b1d-4066-a145-85f8cd0334ae');manifest=dataset['manifest']
        baseline=read('agent_training_history',manifest['baseline_id'])
        weights=ROOT/'data/training/cache/models--mistralai--Timestral-5M/snapshots'/SOURCE_REVISION/'model.safetensors'
        with weights.open('rb') as handle:artifact=hashlib.file_digest(handle,'sha256').hexdigest()
        config=TimestralConfig(enabled=True,model=SOURCE_MODEL,revision=SOURCE_REVISION,device='cpu',threads=1,
            context=64,min_context=64,memory_mb=768,python=str(ROOT/'.venv-training/Scripts/python.exe'),
            cache_dir=str(ROOT/'data/training/cache'))
        hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['run_timestral_timeframe_pilot.py',
            'run_literature_experiment.py','src/aurelia_fx/forecasting/engine.py','src/aurelia_fx/execution_simulator.py',
            'src/aurelia_fx/calendar_aggregation.py','src/aurelia_fx/broker_calendar.py']}
        protocol=dict(spec=SPEC,baseline=baseline['baseline_id'],prices_sha=baseline['timeframes']['M5']['dataset_sha256'],
            model=SOURCE_MODEL,revision=SOURCE_REVISION,artifact=artifact,sdk=SDK_REVISION,code_hashes=hashes,
            config_hash=config.fingerprint,numerical_contract='Generic univariate trading-bar input; production M5 configuration is untouched',
            registered_at=datetime.now(timezone.utc).isoformat())
        if args.resume:
            protocol=read('agent_tf_model_protocol',args.resume)
            if not protocol or protocol['code_hashes']!=hashes or protocol['artifact']!=artifact:raise ValueError('Frozen pilot changed')
        else:
            protocol['id']=fingerprint(protocol);memory.record_project_data('agent_tf_model_protocol',protocol['id'],protocol)
        print(json.dumps(dict(stage='registered',id=protocol['id'])),flush=True)
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(rows);del rows
        cases=opportunities(candles,utc(manifest['first_label_at']))
        print(json.dumps(dict(stage='contexts_sealed',count=len(cases),sha=fingerprint(cases))),flush=True)
        adapter=TimestralAdapter(config);outputs={}
        for offset in range(0,len(cases),8):
            group=cases[offset:offset+8];missing=[]
            for case in group:
                key=fingerprint(dict(context=case['context_sha'],timeframe=case['timeframe'],artifact=artifact,
                                     config=config.fingerprint,sdk=SDK_REVISION))
                case['cache_key']=key;stored=read('agent_tf_model_forecast',key)
                if stored:outputs[key]=stored['output']
                else:missing.append(case)
            if missing:
                if adapter.process is None and psutil.virtual_memory().available<512*1024**2:
                    raise RuntimeError('Pilot awaits512MB free RAM; resume same registered protocol')
                forecasts=adapter.forecast_batch([case['values'] for case in missing])
                for case,out in zip(missing,forecasts):
                    if out['artifact_sha256']!=artifact or out['sdk_revision']!=SDK_REVISION:raise ValueError('Wrong model artifact')
                    outputs[case['cache_key']]=out
                    memory.record_project_data('agent_tf_model_forecast',case['cache_key'],dict(context_sha=case['context_sha'],
                        timeframe=case['timeframe'],signal_at=case['signal_at'],output=out))
            print(json.dumps(dict(stage='forecasts',done=min(offset+8,len(cases)),total=len(cases))),flush=True)
        adapter.close();adapter=None
        arms={tf+':'+gate:[] for tf in SPEC['timeframes'] for gate in ('raw','cost')}
        for case in cases:
            for gate in ('raw','cost'):
                s=signal(case,outputs[case['cache_key']],cost_gate=gate=='cost')
                if s:arms[case['timeframe']+':'+gate].append(s)
        memory.record_project_data('agent_tf_model_signals',protocol['id'],dict(protocol=protocol['id'],signals=arms))
        result=dict(protocol=protocol,opportunities=len(cases),development={},check={},stress={})
        split=utc('2026-07-01T00:00:00+00:00')
        for phase,a,b in [('development',utc(manifest['first_label_at']),split),('check',split,utc(manifest['as_of']))]:
            for arm,samples in arms.items():
                holding=6*SPEC['timeframes'][arm.split(':')[0]]//300
                metrics=simulate(samples,candles,start=a,end=b,holding_bars=holding,purge_hours=6,session_buffer_minutes=5)
                result[phase][arm]=metrics
                print(json.dumps(dict(stage='portfolio',phase=phase,arm=arm,closed=metrics['closed_trades'],net=metrics['net_pnl'])),flush=True)
        selected=choose({k:v for k,v in result['development'].items() if not k.startswith('M5:')})
        result['selected']=selected;result['approved']=False
        if selected:
            result['stress'][selected]=simulate(arms[selected],candles,start=split,end=utc(manifest['as_of']),stress=True,
                holding_bars=6*SPEC['timeframes'][selected.split(':')[0]]//300,purge_hours=6,session_buffer_minutes=5)
            r=result['check'][selected];s=result['stress'][selected]
            result['historical_supported']=bool(r['closed_trades']>=30 and r['net_pnl'] is not None and r['net_pnl']>0 and
                (r['profit_factor'] or 0)>=1.1 and s['net_pnl'] is not None and s['net_pnl']>0 and
                all(not x['censored_trades'] and not x['unresolved_position'] and not x['account_locked'] for x in (r,s)))
        else:result['historical_supported']=False
        result['id']=fingerprint(result);path=ROOT/'data/reports'/('timestral-timeframes-'+result['id'][:12]+'.json')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        memory.record_project_data('agent_tf_model_experiment',result['id'],result)
        print(json.dumps(dict(stage='complete',id=result['id'],selected=selected,supported=result['historical_supported'])),flush=True)
    finally:
        if adapter:adapter.close()
        memory.close()


if __name__=='__main__':main()
