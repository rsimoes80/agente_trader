"""Fixed walk-forward expected-net-reward experiment; no broker or model promotion."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def relabel(samples,candles):
    from aurelia_fx.agent_research import simulator,request_for,SESSIONS
    from aurelia_fx.historical.core import utc
    from aurelia_fx.domain import Candidate
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.broker_calendar import unexpected_broker_gap,slot_tradable
    sessions=SessionEngine(SESSIONS);index={b.timestamp:i for i,b in enumerate(candles)}
    result=[];excluded={}
    for s in samples:
        at=utc(s['signal_at']);j=index.get(at)
        if j is None or not sessions.identify(at+timedelta(minutes=5)).active_sessions:
            excluded['outside_execution_window']=excluded.get('outside_execution_window',0)+1;continue
        engine=simulator(1000.);candidate=Candidate(**{**s['candidate'],'expires_at':utc(s['candidate']['expires_at'])})
        engine.submit(request_for(dict(candidate=candidate,snapshot=s['snapshot'],signal_at=s['signal_at']),s['sample_id']+':reward-label'))
        previous=candles[j-1] if j else None
        for bar in candles[j:j+12]:
            known=bar.timestamp+timedelta(minutes=5)
            ending=not slot_tradable(known) or not sessions.identify(known+timedelta(minutes=5)).active_sessions
            engine.advance(bar,data_valid=previous is None or not unexpected_broker_gap(previous,bar,300),
                active_sessions=sessions.identify(bar.timestamp).active_sessions,
                force_close_reason='KNOWN_SESSION_END' if ending else None)
            previous=bar
            if not engine.busy:break
        closed=[e for e in engine.events if e['status']=='closed']
        if len(closed)!=1 or engine.account_locked:
            excluded['unresolved_or_rejected']=excluded.get('unresolved_or_rejected',0)+1;continue
        e=closed[0];f=e['financial_result']
        result.append(dict(sample_id=s['sample_id'],signal_at=s['signal_at'],exit_at=e['observed_at'],
            features=s['features'],result_in_r=f['result_in_r'],net_pnl=f['net_pnl']))
    return result,excluded


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx import reward_model
    from run_literature_experiment import simulate
    memory=open_memory()
    def read(kind,key):
        with memory.pool.connection() as c:
            row=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        d=json.loads(row['payload_json'])
        if memory._encode(d)[1]!=row['payload_sha256']:raise ValueError('Frozen source mismatch')
        return d
    try:
        dataset=read('agent_training_dataset','661f1b42-0b1d-4066-a145-85f8cd0334ae');manifest=dataset['manifest']
        baseline=read('agent_training_history',manifest['baseline_id']);samples=[];hashes=[]
        for offset in range(0,len(dataset['sample_ids']),40):
            keys=dataset['sample_ids'][offset:offset+40]
            with memory.pool.connection() as c:
                rows=c.execute("SELECT DISTINCT ON(record_key) record_key,payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_sample' AND record_key=ANY(%s) ORDER BY record_key,recorded_at",(keys,)).fetchall()
            indexed={r['record_key']:r for r in rows}
            if set(indexed)!=set(keys):raise ValueError('Incomplete reward input batch')
            for key in keys:
                r=indexed[key];raw=json.loads(r['payload_json'])
                if memory._encode(raw)[1]!=r['payload_sha256']:raise ValueError('Sample changed')
                hashes.append(r['payload_sha256'])
                # Old execution/financial labels are deliberately not model inputs.
                s={k:raw[k] for k in ('sample_id','signal_at','entry_at','candidate','features')}
                s['snapshot']={k:raw['snapshot'][k] for k in ('snapshot_id','session','regime')};samples.append(s)
        samples.sort(key=lambda s:s['signal_at'])
        end=utc(manifest['as_of']);boundaries=[utc(f'2026-{m:02d}-01T00:00:00+00:00') for m in (3,5,7,9)]+[end]
        protocol=dict(version='reward-walkforward-v1',model=reward_model.SPEC,source=dataset['run_id'],
            input_hash=fingerprint(hashes),price_hash=baseline['timeframes']['M5']['dataset_sha256'],
            boundaries=[b.isoformat() for b in boundaries],training='All labels resolved strictly before each fold; no tuning or refit within fold',
            labels='Relabel original candidates with current normal costs,12M5 maximum,known-session exit5minbuffer; overlapping counterfactuals are not independent portfolio trades',
            selection='Fixed predicted netR>0, no probability or threshold search',
            gate='First2folds pooled>=50closed,net>0,PF>=1.1; final2folds EACH>=20closed,net>0,PF>=1.1,positive stress,clean. Independent future confirmation still required.',
            data='Previously researched historical source, not new OOS',risk='Existing limits and .01lot unchanged; research regime universe only',
            code_hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                ['src/aurelia_fx/reward_model.py','run_reward_model_experiment.py','run_literature_experiment.py','src/aurelia_fx/execution_simulator.py']},
            registered_at=datetime.now(timezone.utc).isoformat(),activation=False,orders_sent=0)
        protocol['id']=fingerprint(protocol);memory.record_project_data('agent_reward_protocol',protocol['id'],protocol)
        print(json.dumps(dict(stage='registered',id=protocol['id'],candidates=len(samples))),flush=True)
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(rows);del rows
        labels,excluded=relabel(samples,candles)
        memory.record_project_data('agent_reward_labels',protocol['id'],dict(labels=labels,excluded=excluded))
        print(json.dumps(dict(stage='labels',n=len(labels),excluded=excluded)),flush=True)
        result=dict(protocol=protocol,folds=[],label_sha=fingerprint(labels),excluded_labels=excluded)
        for i,(a,b) in enumerate(zip(boundaries,boundaries[1:])):
            train=[s for s in labels if utc(s['exit_at'])<a and utc(s['signal_at'])<a]
            model=reward_model.fit(train,known_before=a)
            memory.record_project_data('agent_reward_model',model['id'],model)
            opportunities=[s for s in samples if a<=utc(s['signal_at'])<b]
            predictions={s['sample_id']:reward_model.predict(model,s['features']) for s in opportunities}
            chosen=[s for s in opportunities if predictions[s['sample_id']]>reward_model.SPEC['entry_threshold']]
            base=simulate(opportunities,candles,start=a,end=b,holding_bars=12,purge_hours=1,session_buffer_minutes=5)
            learned=simulate(chosen,candles,start=a,end=b,holding_bars=12,purge_hours=1,session_buffer_minutes=5)
            evaluated=[s for s in labels if s['sample_id'] in predictions and utc(s['exit_at'])<b]
            mse=sum((predictions[s['sample_id']]-s['result_in_r'])**2 for s in evaluated)/len(evaluated) if evaluated else None
            constant_mse=sum((model['constant_prediction']-s['result_in_r'])**2 for s in evaluated)/len(evaluated) if evaluated else None
            fold=dict(start=a.isoformat(),end=b.isoformat(),role='development' if i<2 else 'check',model=model['id'],
                fit_n=len(train),opportunities=len(opportunities),positive_predictions=len(chosen),
                out_of_fold_mse=mse,constant_mse=constant_mse,base=base,learned=learned)
            if i>=2:fold['stress']=simulate(chosen,candles,start=a,end=b,stress=True,holding_bars=12,purge_hours=1,session_buffer_minutes=5)
            result['folds'].append(fold)
            print(json.dumps(dict(stage='fold',start=fold['start'],fit=len(train),selected=len(chosen),base_net=base['net_pnl'],learned_net=learned['net_pnl'],closed=learned['closed_trades'],mse=mse,constant_mse=constant_mse)),flush=True)
        def clean(m):return not m['account_locked'] and not m['unresolved_position'] and not m['censored_trades'] and m['net_pnl'] is not None
        dev=[f['learned'] for f in result['folds'][:2]]
        dev_trades=[t for m in dev for t in m['trades']];pnls=[t['financial_result']['net_pnl'] for t in dev_trades]
        gains=sum(max(0,p) for p in pnls);losses=-sum(min(0,p) for p in pnls)
        development_passed=(all(clean(m) for m in dev) and len(pnls)>=50 and sum(pnls)>0 and losses>0 and gains/losses>=1.1)
        def qualified(f):
            m=f['learned'];s=f['stress']
            return clean(m) and clean(s) and m['closed_trades']>=20 and m['net_pnl']>0 and (m['profit_factor'] or 0)>=1.1 and s['net_pnl']>0
        result.update(development_passed=development_passed,historical_supported=development_passed and all(qualified(f) for f in result['folds'][2:]),approved=False)
        result['id']=fingerprint(result)
        (ROOT/'data/reports'/('reward-model-'+result['id'][:12]+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        memory.record_project_data('agent_reward_experiment',result['id'],result)
        print(json.dumps(dict(stage='complete',id=result['id'],supported=result['historical_supported'])),flush=True)
    finally:memory.close()


if __name__=='__main__':main()
