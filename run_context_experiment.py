"""Investigate pre-entry impulse, correction and structural room offline."""
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
    from aurelia_fx.context_experiment import PROTOCOL,SOURCE,features,evaluate,diagnostics
    memory=open_memory();emit=lambda d:print(json.dumps(d,ensure_ascii=True),flush=True)
    def decode(row):
        if not row:raise ValueError('Required record missing')
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Frozen record integrity failure')
        return data
    try:
        with memory.pool.connection() as c:
            source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_correction_experiment' AND record_key=%s LIMIT 1",(SOURCE,)).fetchone())
            baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s LIMIT 1",(source['frozen_baseline'],)).fetchone())
        sha=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in
            ['run_context_experiment.py','src/aurelia_fx/context_experiment.py','src/aurelia_fx/trigger_exit_experiment.py'])).hexdigest()
        key=fingerprint(dict(protocol=PROTOCOL,implementation_sha256=sha))
        with memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_context_protocol' AND record_key=%s LIMIT 1",(key,)).fetchone()
        registration=decode(row) if row else dict(protocol_id=key,protocol=PROTOCOL,implementation_sha256=sha,
            registered_at=datetime.now(timezone.utc).isoformat(),
            code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_worktree=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()))
        if not row:memory.record_project_data('agent_context_protocol',key,registration)
        emit(dict(stage='protocol_registered_before_outcomes',protocol_id=key))
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(rows);samples=source['eligible_samples'];meta=source['source_manifest']
        values=features(samples,candles,progress=emit)
        results=evaluate(samples,candles,values,meta,progress=emit)
        old=source['results']['all']['strict_or_guarded_correction'];reference=results['all']['reference']
        for k in ('closed_trades','wins','losses','net_pnl'):
            if reference[k]!=old[k]:raise ValueError('Reference portfolio reproduction failed: '+k)
        report=dict(registration=registration,source_report=SOURCE,source_manifest=meta,
            baseline_id=source['frozen_baseline'],source_candles=len(candles),sealed_signals=len(samples),
            created_at=datetime.now(timezone.utc).isoformat(),features=values,results=results,
            diagnostics=diagnostics(reference,values),reference_exactly_reproduced=True,
            live_policy_changed=False,orders_sent=0)
        report['report_id']=fingerprint(report)
        memory.record_project_data('agent_context_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('context-'+report['report_id'][:12]+'.json')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],path=str(path),results={p:{a:{k:v.get(k) for k in
            ('candidate_signals','closed_trades','wins','losses','win_rate_pct','net_pnl','profit_factor','expectancy_usd','max_close_equity_drawdown_pct','account_locked','unresolved_position')}
            for a,v in arms.items()} for p,arms in results.items()},diagnostics=report['diagnostics']))
    finally:memory.close()


if __name__=='__main__':main()
