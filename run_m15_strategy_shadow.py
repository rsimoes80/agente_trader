"""Forward paper observation of the preselected M15 reversal, with both fee profiles."""
import argparse
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
PARENT='6a65b9b9df12e3a248638dba5105b89131d378465722758fa8bc727911bf9884'


def persist_experiences(memory,identity,tape,signals,raw,results,seen):
    """Store one observation/outcome per identity; cycles retain only summaries."""
    from aurelia_fx.historical.core import utc
    captured={utc(r['timestamp'])+timedelta(minutes=5):r['first_seen_at'] for r in raw}
    for signal in signals:
        key=identity+':'+signal['sample_id'];kind='agent_m15_strategy_signal'
        if (kind,key) not in seen:
            memory.record_project_data(kind,key,dict(protocol_id=identity,source_tape=tape,sample=signal,
                first_captured_at=captured[utc(signal['signal_at'])],mode='paper_only'))
            seen.add((kind,key))
    compact={}
    for profile,result in results.items():
        for trade in result['trades']:
            key=identity+':'+profile+':'+trade['decision_id'];kind='agent_m15_strategy_outcome'
            if (kind,key) not in seen:
                memory.record_project_data(kind,key,dict(protocol_id=identity,cost_profile=profile,
                    sample_id=trade['decision_id'],trade=trade,mode='paper_only',
                    note='Counterfactual fee profiles for one market event are not independent experiences'))
                seen.add((kind,key))
        compact[profile]={k:v for k,v in result.items() if k!='trades'}
    return compact


def replay_candidates(signals,candles,*,start,end):
    from run_literature_experiment import simulate
    from run_demo_fee_sensitivity import zero_fee_simulator
    import aurelia_fx.agent_research as research
    original=research.simulator
    kw=dict(start=start,end=end,holding_bars=72,purge_hours=0,session_buffer_minutes=5)
    try:
        research.simulator=zero_fee_simulator(original)
        normal=simulate(signals,candles,**kw)
        stress=simulate(signals,candles,stress=True,**kw)
    finally:research.simulator=original
    return dict(normal=normal,stress=stress,conservative_normal=simulate(signals,candles,**kw),
                conservative_stress=simulate(signals,candles,stress=True,**kw))


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from run_h1_shadow import on_time
    from run_h1_hours_shadow import current_tape
    from run_h1_hours_experiment import permits
    from run_literature_validation import generate
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    memory=open_memory();emit=lambda x:print(json.dumps(x,ensure_ascii=True),flush=True)
    def decode(row):
        if row is None:return None
        value=json.loads(row['payload_json'])
        if memory._encode(value)[1]!=row['payload_sha256']:raise ValueError('Paper source integrity mismatch')
        return value
    def read(kind,key):
        with memory.pool.connection() as c:return decode(c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone())
    try:
        with memory.pool.connection() as lock:
            if not lock.execute("SELECT pg_try_advisory_lock(hashtext('agente-trader-m15-strategy-shadow-v1')) AS ok").fetchone()['ok']:
                raise RuntimeError('M15 observer already running')
            try:
                parent=read('agent_demo_fee_experiment',PARENT)
                if parent is None or not parent['selected']:raise ValueError('No preselected research candidate')
                selected=parent['selected'];family,policy=selected.split(':');tape=current_tape(memory)
                files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/p for p in ('run_m15_strategy_shadow.py','run_literature_validation.py','run_h1_shadow.py','run_h1_hours_shadow.py','run_h1_hours_experiment.py','run_literature_experiment.py','run_demo_fee_sensitivity.py','run_timeframe_experiment.py')]
                hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
                identity=fingerprint(dict(parent=PARENT,tape=tape,code_hashes=hashes))
                protocol=read('agent_m15_strategy_shadow_protocol',identity)
                if protocol is None:
                    now=datetime.now(timezone.utc);start=datetime.fromtimestamp((int(now.timestamp())//300+1)*300,timezone.utc)
                    protocol=dict(protocol_id=identity,parent=PARENT,tape=tape,code_hashes=hashes,start=start.isoformat(),registered_at=now.isoformat(),
                        version='m15-shadow-normalized-experiences-v2',
                        selected=selected,timeframe='M15',mode='paper_only',historically_validated=False,
                        purpose='Exploratory forward evaluation; historical checks failed. Do not activate demo/live execution or claim profit validation.',
                        fees='Normal/stress zero-commission conditional demo profile; conservative_normal/conservative_stress USD35/million/side. Observed demo sample does not confirm live tariff.',
                        entry='Only signals first observed within90sec of closing M5,afterregistration; no old trades or later bars. Same original M15 definitions,72M5holding,5minsessionbuffer,lot.01 and risk.',
                        evaluation='At least50newclosed,positiveNET/PF>=1.1/positiveSTRESS/clean and report both fee profiles. This is a research minimum,not an automatic promotion or guarantee.',
                        orders_sent=0,live_policy_changed=False)
                    memory.record_project_data('agent_m15_strategy_shadow_protocol',identity,protocol)
                emit(dict(stage='m15_shadow_started',protocol_id=identity,start=protocol['start'],selected=selected))
                with memory.pool.connection() as c:
                    stored=c.execute("SELECT record_type,record_key FROM project_records WHERE record_type IN ('agent_m15_strategy_signal','agent_m15_strategy_outcome') AND record_key LIKE %s",(identity+':%',)).fetchall()
                seen={(r['record_type'],r['record_key']) for r in stored}
                previous=None
                while True:
                    try:
                        with memory.pool.connection() as c:source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_h1_shadow_cycle' AND record_key LIKE %s ORDER BY recorded_at DESC LIMIT 1",(tape+':%',)).fetchone())
                        if source and utc(source['as_of'])>utc(protocol['start']) and previous!=source['as_of']:
                            seed=read('agent_h1_shadow_seed',tape)
                            with memory.pool.connection() as c:rows=c.execute("SELECT DISTINCT ON(record_key) payload_json,payload_sha256 FROM project_records WHERE record_type='agent_h1_shadow_bar' AND record_key LIKE %s ORDER BY record_key,recorded_at ASC",(tape+':%',)).fetchall()
                            raw=[decode(r) for r in rows];raw=[r for r in raw if utc(r['timestamp'])<utc(source['as_of'])]
                            all_candles=candles_from(seed['candles']+raw)
                            pools=generate(all_candles,utc(protocol['start'])-timedelta(minutes=5),timeframe='M15')
                            signals,late=on_time(pools[family],raw)
                            signals=[s for s in signals if utc(s['entry_at'])>=utc(protocol['start']) and permits(s,policy)]
                            candles=[c for c in all_candles if utc(protocol['start'])<=c.timestamp<utc(source['as_of'])]
                            result=replay_candidates(signals,candles,start=utc(protocol['start']),end=utc(source['as_of']))
                            compact=persist_experiences(memory,identity,tape,signals,raw,result,seen)
                            cycle=dict(protocol_id=identity,source_tape=tape,as_of=source['as_of'],recorded_at=datetime.now(timezone.utc).isoformat(),
                                selected=selected,results={selected:compact},timely_signals=len(signals),late_signals_not_traded=len(late),
                                mode='paper_only',historically_validated=False,orders_sent=0,live_policy_changed=False)
                            memory.record_project_data('agent_m15_strategy_shadow_cycle',identity+':'+source['as_of'],cycle)
                            emit(dict(stage='m15_shadow_cycle',as_of=source['as_of'],timely_signals=len(signals),closed=result['normal']['closed_trades'],
                                net=result['normal']['net_pnl'],conservative_net=result['conservative_normal']['net_pnl'],censored=result['normal']['censored_trades']))
                            previous=source['as_of']
                        else:emit(dict(stage='waiting_for_new_source_cycle'))
                    except Exception as exc:
                        emit(dict(stage='retry',error_type=type(exc).__name__,message=str(exc)[:300]))
                        if not args.watch:raise
                    if not args.watch:break
                    time.sleep(30)
            finally:lock.execute("SELECT pg_advisory_unlock(hashtext('agente-trader-m15-strategy-shadow-v1'))")
    finally:memory.close()


if __name__=='__main__':main()
