"""Frozen, costed trend-with-correction hypothesis test; never sends orders."""
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
    try:
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error,AttributeError):pass
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.agent_strategy import SPEC_HASH
    from aurelia_fx.correction_experiment import PROTOCOL,generate,evaluate
    from aurelia_fx.historical.repository import HistoricalRepository
    memory=open_memory()
    emit=lambda d:print(json.dumps(d,ensure_ascii=True),flush=True)
    def decode(row):
        if not row:raise ValueError('Source record missing')
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Source integrity mismatch')
        return data
    try:
        with memory.pool.connection() as c:
            datasets=[decode(r) for r in c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_dataset'").fetchall()]
            compatible=[d for d in datasets if fingerprint(d['manifest'].get('strategy',{}))==SPEC_HASH and d['manifest'].get('training_days')]
            source=max(compatible,key=lambda d:(d['manifest']['training_days'],d['manifest']['created_at']))
            meta=source['manifest']
            baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s ORDER BY recorded_at LIMIT 1",(meta['baseline_id'],)).fetchone())
        implementation=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in
            ['run_correction_experiment.py','src/aurelia_fx/correction_experiment.py',
             'src/aurelia_fx/research_levels.py'])).hexdigest()
        key=fingerprint(dict(protocol=PROTOCOL,source_run_id=source['run_id'],implementation=implementation))
        with memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_correction_protocol' AND record_key=%s LIMIT 1",(key,)).fetchone()
        if row:registration=decode(row)
        else:
            registration=dict(protocol_id=key,protocol=PROTOCOL,source_run_id=source['run_id'],
                implementation_sha256=implementation,registered_at=datetime.now(timezone.utc).isoformat(),
                code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                dirty_worktree=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()))
            memory.record_project_data('agent_correction_protocol',key,registration)
        emit(dict(stage='protocol_registered_before_outcomes',protocol_id=key,source=source['run_id']))
        frozen,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        emit(dict(stage='source_integrity_verified',candles=len(rows),start=meta['first_label_at'],end=meta['as_of']))
        samples,diagnostics=generate(rows,start=meta['first_label_at'],progress=emit)
        emit(dict(stage='candidate_generation_complete',eligible=len(samples),diagnostics=diagnostics))
        results=evaluate(rows,samples,meta)
        report=dict(version=PROTOCOL['version'],registration=registration,created_at=datetime.now(timezone.utc).isoformat(),
            source_manifest=meta,source_run_id=source['run_id'],frozen_baseline=frozen['baseline_id'],candles=len(rows),
            diagnostics=diagnostics,eligible_samples=samples,results=results,live_policy_changed=False,orders_sent=0)
        report['report_id']=fingerprint(report)
        memory.record_project_data('agent_correction_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('correction-'+report['report_id'][:12]+'.json')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],path=str(path),results={
            period:{arm:{k:v.get(k) for k in ['candidate_signals','closed_trades','wins','losses','net_pnl',
                'win_rate_pct','profit_factor','expectancy_usd','max_close_equity_drawdown_pct','unresolved_position']}
                for arm,v in arms.items()} for period,arms in results.items()}))
    finally:memory.close()


if __name__=='__main__':main()
