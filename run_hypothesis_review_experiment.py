"""Frozen MT5 replay of the review cycle; no broker calls or policy mutation."""
import argparse
from collections import Counter
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def longer_comparison(samples,candles,manifest):
    """Fixed global filter ablation in research only; no production gate relaxation."""
    from aurelia_fx.historical.core import utc
    from aurelia_fx.domain import Candidate
    from aurelia_fx import hypothesis_review as hr
    from run_literature_experiment import simulate,choose
    arms={'base':samples}
    for code in sorted(hr.LABELS):
        arms[code]=[]
        for sample in samples:
            candidate=Candidate(**{**sample['candidate'],'expires_at':utc(sample['candidate']['expires_at'])})
            facts=hr.critique(dict(candidate=candidate,snapshot=sample['snapshot'],signal_at=sample['signal_at']),sample['features'])
            if code not in facts['concerns']:arms[code].append(sample)
    start=utc(manifest['first_label_at']);end=utc(manifest['as_of'])
    split=utc('2026-07-01T00:00:00+00:00')
    if not start<split<end:raise ValueError('Fixed July boundary not covered by this source')
    result=dict(scope='broader_research_only_not_production',selection='Development only: >=50 closed, positive net, PF>=1.1; check >=30, same criteria; no censor/lock/pending',
        exit='Original 12-bar holding, known session-end flatten, one-hour boundary purge for every arm',
        costs='Observed spread, commission USD35/million/side, slippage .2pip; stress spreadx1.5/slippage.4pip',
        development={},check={},stress_check={})
    for period,a,b in [('development',start,split),('check',split,end)]:
        for arm,signals in arms.items():
            metrics=simulate(signals,candles,start=a,end=b,holding_bars=12,purge_hours=1)
            result[period][arm]=metrics
            print(json.dumps(dict(stage='long_comparison',period=period,arm=arm,closed=metrics['closed_trades'],net=metrics['net_pnl'])),flush=True)
    # Select only filters, against the unchanged opportunity stream; no negative winner fallback.
    selected=choose({k:v for k,v in result['development'].items() if k!='base'})
    result['selected']=selected
    if selected:
        result['stress_check'][selected]=simulate(arms[selected],candles,start=split,end=end,stress=True,holding_bars=12,purge_hours=1)
    def passed(r):
        return (r['closed_trades']>=30 and r['net_pnl'] is not None and r['net_pnl']>0 and
                (r['profit_factor'] or 0)>=1.1 and not r['censored_trades'] and
                not r['account_locked'] and not r['unresolved_position'])
    result['supported']=bool(selected and passed(result['check'][selected]) and passed(result['stress_check'][selected]))
    result['activation']=False
    return result


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.agent_research import simulator, request_for, SESSIONS
    from aurelia_fx.continual_learning import context
    from aurelia_fx.entry_trend import entry_blocker
    from aurelia_fx.domain import Candidate
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx import hypothesis_review as hr
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',default='661f1b42-0b1d-4066-a145-85f8cd0334ae')
    parser.add_argument('--long-comparison',action='store_true')
    args=parser.parse_args();memory=open_memory()
    def read(kind,key):
        with memory.pool.connection() as c:
            row=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if not row:raise ValueError('Missing frozen record: '+kind)
        d=json.loads(row['payload_json'])
        if memory._encode(d)[1]!=row['payload_sha256']:raise ValueError('Source integrity failure')
        return d
    try:
        dataset=read('agent_training_dataset',args.dataset);manifest=dataset['manifest']
        samples=[];source_hashes=[]
        for offset in range(0,len(dataset['sample_ids']),40):
            keys=dataset['sample_ids'][offset:offset+40]
            with memory.pool.connection() as c:
                batch=c.execute("SELECT DISTINCT ON(record_key) record_key,payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_sample' AND record_key=ANY(%s) ORDER BY record_key,recorded_at",(keys,)).fetchall()
            indexed={r['record_key']:r for r in batch}
            if set(indexed)!=set(keys):raise ValueError('Incomplete frozen sample batch')
            for key in keys:
                row=indexed[key];original=json.loads(row['payload_json'])
                if memory._encode(original)[1]!=row['payload_sha256']:raise ValueError('Sample integrity failure')
                source_hashes.append(fingerprint(original))
                # Deliberately omit original future execution/labels from replay inputs.
                sample={k:original[k] for k in ('sample_id','signal_at','entry_at','candidate','features','spec_hash')}
                sample['snapshot']={k:original['snapshot'][k] for k in ('snapshot_id','session','regime','regime_config_hash','macro_trend','context_trend','conflicting_evidence') if k in original['snapshot']}
                samples.append(sample)
        samples.sort(key=lambda s:(s['signal_at'],s['sample_id']))
        baseline=read('agent_training_history',manifest['baseline_id'])
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(rows)
        protocol=dict(version='review-cycle-replay-v1',dataset=args.dataset,review_spec=hr.SPEC,
            baseline_id=manifest['baseline_id'],data_sha=baseline['timeframes']['M5']['dataset_sha256'],
            sample_sha=fingerprint(samples),original_sample_hashes=source_hashes,
            long_comparison=args.long_comparison,long_split='2026-07-01T00:00:00+00:00',
            code_sha={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                ['src/aurelia_fx/hypothesis_review.py','src/aurelia_fx/continual_learning.py','src/aurelia_fx/execution_simulator.py','run_literature_experiment.py','run_hypothesis_review_experiment.py']},
            data_status='Previously researched historical data; chronological future windows are NOT new prospective evidence',
            scopes=['current_entry_policy','broader_research_only'],orders_sent=0,activation=False)
        protocol['id']=fingerprint(protocol)
        memory.record_project_data('agent_review_protocol',protocol['id'],protocol)
        print(json.dumps(dict(stage='registered',id=protocol['id'],samples=len(samples),bars=len(candles))),flush=True)
        report=dict(protocol=protocol,results={})
        sessions=SessionEngine(SESSIONS)
        scheduled={}
        for s in samples:scheduled.setdefault(utc(s['signal_at']),[]).append(s)
        for scope in protocol['scopes']:
            state=dict(units=1000.);sim=simulator(1000.);previous=None;closed=[];blocked=Counter();censored=0
            for i,bar in enumerate(candles):
                known=bar.timestamp+timedelta(minutes=5)
                valid=not previous or not unexpected_broker_gap(previous,bar,300)
                active=sessions.identify(bar.timestamp).active_sessions
                hr.advance_portfolios(state,bar,valid,active)
                for event in sim.advance(bar,data_valid=valid,active_sessions=active):
                    if event['status']=='closed':
                        f=event['financial_result'];result=dict(variant='baseline',context=event['intelligence_context']['learning_context'],
                            entry_at=event['entry_at'],exit_at=event['observed_at'],net_pnl=f['net_pnl'],result_in_r=f['result_in_r'],
                            event_id=event['event_id'],scope='historical_shadow')
                        hr.review(state,event,result);closed.append(result)
                    elif event['status']=='censored':
                        censored+=1
                        p=hr.state_for(state)['proposal']
                        if p and p['status']=='COLLECTING_FUTURE':p['status']='INVALIDATED_DATA_GAP'
                        hr.state_for(state)['reviews']=[]
                sim.events.clear();hr.evaluate(state,known)
                for sample in scheduled.get(known,[]):
                    reason=entry_blocker(sample['snapshot'],sample['candidate']['side'])
                    if scope=='current_entry_policy' and reason:
                        blocked[reason]+=1;continue
                    c={**sample['candidate'],'expires_at':utc(sample['candidate']['expires_at'])}
                    candidate=Candidate(**c);features=sample['features']
                    setup=dict(candidate=candidate,snapshot=sample['snapshot'],signal_at=sample['signal_at'],
                        atr=abs(candidate.entry-candidate.stop)/features['stop_atr'],
                        learning_source=sample['spec_hash'],learning_model=manifest['model_configuration'])
                    key=context(setup);hr.consider_portfolios(state,setup,features,key)
                    if not sim.busy and not sim.account_locked:
                        facts=hr.critique(setup,features)
                        setup['snapshot']={**setup['snapshot'],'learning_context':key,'hypothesis_critique':facts}
                        sim.submit(request_for(setup,sample['sample_id']))
                previous=bar
                if i%20000==0:print(json.dumps(dict(stage='replay',scope=scope,bars=i,closed=len(closed))),flush=True)
            result=dict(closed=len(closed),net_pnl=sum(r['net_pnl'] for r in closed),wins=sum(r['net_pnl']>0 for r in closed),
                censored=censored,pending=sim.busy,account_locked=sim.account_locked,blockers=dict(blocked),review=hr.summary(state),
                proposal=hr.state_for(state)['proposal'],ledger_sha=fingerprint(closed),
                conclusion='No automatic production change: this experiment measures research hypotheses only')
            report['results'][scope]=result
            print(json.dumps(dict(stage='scope_complete',scope=scope,closed=result['closed'],net_pnl=result['net_pnl'],
                review=result['review']['proposal'])),flush=True)
        if args.long_comparison:report['long_comparison']=longer_comparison(samples,candles,manifest)
        report['id']=fingerprint(report)
        path=ROOT/'data/reports'/('hypothesis-review-'+report['id'][:12]+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        memory.record_project_data('agent_review_experiment',report['id'],report)
        print(json.dumps(dict(stage='complete',id=report['id'],path=str(path))),flush=True)
    finally:memory.close()


if __name__=='__main__':main()
