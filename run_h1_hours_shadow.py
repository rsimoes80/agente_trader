"""Prospective time-policy comparison using the existing immutable H1 paper tape."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import argparse

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
HOURS='2be30ccf58ecdb26d43b1793b4a1201974d6822466004ee6e1f19a93769161a3'
def current_tape(memory):
    """Bind a study to the current feed implementation, including logon races."""
    from run_h1_shadow import implementation_hashes
    expected=implementation_hashes()
    with memory.pool.connection() as c:
        rows=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_h1_shadow_protocol' ORDER BY recorded_at DESC LIMIT 20").fetchall()
    for row in rows:
        value=json.loads(row['payload_json'])
        if memory._encode(value)[1]!=row['payload_sha256']:raise ValueError('Feed protocol integrity mismatch')
        if value['code_hashes']==expected:return value['protocol_id']
    raise RuntimeError('Waiting for current H1 feed protocol; automatic retry')


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from run_h1_hours_experiment import ARMS,permits
    from run_literature_experiment import simulate
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    memory=open_memory();emit=lambda x:print(json.dumps(x,ensure_ascii=True),flush=True)
    def decode(row):
        if row is None:return None
        x=json.loads(row['payload_json'])
        if memory._encode(x)[1]!=row['payload_sha256']:raise ValueError('Paper tape integrity mismatch')
        return x
    def read(kind,key):
        with memory.pool.connection() as c:
            return decode(c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone())
    try:
        with memory.pool.connection() as lock:
            if not lock.execute("SELECT pg_try_advisory_lock(hashtext('agente-trader-h1-hours-shadow-v1')) AS ok").fetchone()['ok']:
                raise RuntimeError('Time-policy observer already running')
            try:
                selection=read('agent_h1_hours_selection',HOURS)
                if selection is None:raise ValueError('Historical selection not frozen')
                tape=current_tape(memory)
                files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/p for p in ('run_h1_hours_shadow.py','run_h1_hours_experiment.py','run_literature_experiment.py')]
                hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
                identity=fingerprint(dict(parent=HOURS,tape=tape,code_hashes=hashes))
                protocol=read('agent_h1_hours_shadow_protocol',identity)
                if protocol is None:
                    now=datetime.now(timezone.utc)
                    start=datetime.fromtimestamp((int(now.timestamp())//300+1)*300,timezone.utc)
                    protocol=dict(protocol_id=identity,parent=HOURS,tape=tape,code_hashes=hashes,
                        registered_at=now.isoformat(),start=start.isoformat(),arms=ARMS,selected=selection['selected'],
                        mode='paper_only',orders_sent=0,live_policy_changed=False,
                        methodology='Reuse on-time H1 signals and first-seen M5 tape, no new MT5 reader.Only entries after this registration; full portfolio replay per arm,normal+stress,original exits.',
                        limitations='Paper prices and cost assumptions, not broker fills; historical selection is exploratory; censored exposure remains locked; no automatic promotion',
                        evaluation='Selected needs >=50closed,positive net,PF>=1.1,positive stressNET,clean; compare reference on same dates. Other arms descriptive, no future winner substitution.')
                    memory.record_project_data('agent_h1_hours_shadow_protocol',identity,protocol)
                emit(dict(stage='hours_shadow_started',protocol_id=identity,start=protocol['start'],selected=protocol['selected']))
                previous=None
                while True:
                    try:
                        with memory.pool.connection() as c:
                            source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_h1_shadow_cycle' AND record_key LIKE %s ORDER BY recorded_at DESC LIMIT 1",(tape+':%',)).fetchone())
                        if source and utc(source['as_of'])>utc(protocol['start']) and source['as_of']!=previous:
                            with memory.pool.connection() as c:
                                records=c.execute("SELECT DISTINCT ON(record_key) payload_json,payload_sha256 FROM project_records WHERE record_type='agent_h1_shadow_bar' AND record_key LIKE %s ORDER BY record_key,recorded_at ASC",(tape+':%',)).fetchall()
                            rows=[decode(r) for r in records]
                            cs=candles_from([r for r in rows if utc(protocol['start'])<=utc(r['timestamp'])<utc(source['as_of'])])
                            ss=[s for s in source['signals'] if utc(s['entry_at'])>=utc(protocol['start'])]
                            results={}
                            for arm in ARMS:
                                filtered=[s for s in ss if permits(s,arm)]
                                kw=dict(start=utc(protocol['start']),end=utc(source['as_of']),holding_bars=288,purge_hours=0,session_buffer_minutes=5)
                                results[arm]=dict(normal=simulate(filtered,cs,**kw),stress=simulate(filtered,cs,stress=True,**kw))
                            cycle=dict(protocol_id=identity,source_tape=tape,source_cycle_at=source['as_of'],
                                as_of=source['as_of'],recorded_at=datetime.now(timezone.utc).isoformat(),
                                selected=protocol['selected'],results=results,mode='paper_only',orders_sent=0,live_policy_changed=False,
                                source_late_signals_not_traded=source['late_signals_not_traded'])
                            memory.record_project_data('agent_h1_hours_shadow_cycle',identity+':'+source['as_of'],cycle)
                            emit(dict(stage='hours_shadow_cycle',as_of=source['as_of'],results={a:{k:r['normal'][k] for k in ('closed_trades','net_pnl','censored_trades')} for a,r in results.items()}))
                            previous=source['as_of']
                        else:emit(dict(stage='waiting_for_new_source_cycle'))
                    except Exception as exc:
                        emit(dict(stage='retry',error_type=type(exc).__name__,message=str(exc)[:300]))
                        if not args.watch:raise
                    if not args.watch:break
                    time.sleep(30)
            finally:lock.execute("SELECT pg_advisory_unlock(hashtext('agente-trader-h1-hours-shadow-v1'))")
    finally:memory.close()


if __name__=='__main__':main()
