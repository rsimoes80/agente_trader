"""Investigate trigger quality and exit duration independently; no orders."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    import psutil
    try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error,AttributeError):pass
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.trigger_exit_experiment import PROTOCOL,feature_rows,evaluate,replay,same_entry_exit_check
    memory=open_memory();emit=lambda d:print(json.dumps(d,ensure_ascii=True),flush=True)
    def decode(row):
        if not row:raise ValueError('Required frozen record missing')
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Record integrity failure')
        return data
    try:
        with memory.pool.connection() as c:
            source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_correction_experiment' AND record_key=%s LIMIT 1",(PROTOCOL['source_report'],)).fetchone())
            baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s LIMIT 1",(source['frozen_baseline'],)).fetchone())
        implementation=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in
            ['run_trigger_exit_experiment.py','src/aurelia_fx/trigger_exit_experiment.py'])).hexdigest()
        key=fingerprint(dict(protocol=PROTOCOL,implementation_sha256=implementation))
        with memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_trigger_exit_protocol' AND record_key=%s LIMIT 1",(key,)).fetchone()
        registration=decode(row) if row else dict(protocol_id=key,protocol=PROTOCOL,
            registered_at=datetime.now(timezone.utc).isoformat(),implementation_sha256=implementation,
            code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_worktree=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()))
        if not row:memory.record_project_data('agent_trigger_exit_protocol',key,registration)
        emit(dict(stage='registered_before_outcomes',protocol_id=key))
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(rows);samples=source['eligible_samples'];meta=source['source_manifest']
        features=feature_rows(samples,candles)
        units=float(meta['lot'])*meta['contract']['contract_size']
        reproduced=replay(samples,candles,features,arm='reference',start=meta['first_label_at'],end=meta['as_of'],units=units,purge_minutes=60)
        old=source['results']['all']['strict_or_guarded_correction']
        for k in ('closed_trades','wins','losses','net_pnl'):
            if reproduced[k]!=old[k]:raise ValueError('Original control failed reproduction: '+k)
        emit(dict(stage='source_and_original_control_verified',candles=len(candles),sealed_signals=len(samples)))
        results=evaluate(samples,candles,features,meta,progress=emit)
        paired=same_entry_exit_check(samples,candles,features,results['all']['reference'],meta)
        report=dict(registration=registration,source_report=PROTOCOL['source_report'],source_manifest=meta,
            baseline_id=source['frozen_baseline'],created_at=datetime.now(timezone.utc).isoformat(),
            source_candles=len(candles),sealed_signals=len(samples),features=features,
            original_control_reproduced=True,results=results,same_entry_exit_diagnostic=paired,
            live_policy_changed=False,orders_sent=0)
        report['report_id']=fingerprint(report)
        memory.record_project_data('agent_trigger_exit_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('trigger-exit-'+report['report_id'][:12]+'.json')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],path=str(path),results={p:{a:{k:v.get(k) for k in
            ('candidate_signals','closed_trades','wins','losses','win_rate_pct','net_pnl','profit_factor','expectancy_usd','max_close_equity_drawdown_pct','account_locked','unresolved_position')}
            for a,v in arms.items()} for p,arms in results.items()}))
    finally:memory.close()


if __name__=='__main__':main()
