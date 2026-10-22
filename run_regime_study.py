"""Costed offline expiry study and prospective follow-up. Never sends orders."""
import argparse
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import summarize,utc
    from aurelia_fx.regime_study import configurations,evaluate,recent_candidates
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--forward-only',action='store_true')
    parser.add_argument('--capture',action='store_true',help='Refresh 60 days from MT5 on Windows')
    args=parser.parse_args();memory=open_memory();repo=HistoricalRepository(memory)
    def emit(data):print(json.dumps(data,ensure_ascii=True),flush=True)
    def decode(row):
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Record integrity failure')
        return data
    try:
        with memory.pool.connection() as lease:
            if not lease.execute('SELECT pg_try_advisory_lock(70616071) AS acquired').fetchone()['acquired']:
                emit(dict(status='already_running'));return
            try:
                with memory.pool.connection() as c:
                    source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_dataset' AND record_key=%s LIMIT 1",('661f1b42-0b1d-4066-a145-85f8cd0334ae',)).fetchone())
                    meta=source['manifest']
                    protocol=dict(name='expiry-eff55-confirm2-v1',configurations={k:asdict(v) for k,v in configurations().items()},
                        source_run_id=source['run_id'],lot=meta['lot'],contract=meta['contract'],
                        live_threshold_promotion=False,minimum_days=7,minimum_closed_trades_per_arm=20,
                        false_breakout='First TREND activation of confirmed range breakout, then close back across its level within next 8 closed H1 bars; missing follow-up remains pending',
                        costs='existing ExecutionSimulator observed spread, market slippage 0.2 pip, commission 35 per million per side',
                        scope='isolated technical pullback eligibility, no adaptive hypothesis selection or Timestral weight training')
                    key=fingerprint(protocol)
                    row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_regime_study_protocol' AND record_key=%s LIMIT 1",(key,)).fetchone()
                if row:registration=decode(row)
                else:
                    registration=dict(protocol=protocol,study_id=key,registered_at=datetime.now(timezone.utc).isoformat())
                    memory.record_project_data('agent_regime_study_protocol',key,registration)
                report=dict(study_id=key,registration=registration,live_policy_changed=False)
                if args.forward_only and datetime.now(timezone.utc)-utc(registration['registered_at'])>timedelta(days=30):
                    memory.record_project_data('agent_regime_study_status',key,dict(status='FOLLOWUP_FINISHED_REVIEW_REQUIRED',study_id=key))
                    emit(dict(status='followup_finished_no_promotion'));return
                if not args.forward_only:
                    with memory.pool.connection() as c:
                        baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s LIMIT 1",(meta['baseline_id'],)).fetchone())
                        samples=[decode(r) for r in c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_sample' AND record_key=ANY(%s)",(source['sample_ids'],)).fetchall()]
                    _,rows=repo.frozen_candles(baseline,record_type='agent_training_history')
                    emit(dict(stage='historical',candles=len(rows)))
                    report['historical']=evaluate(rows,samples,start=meta['first_label_at'],end=meta['as_of'],lot=meta['lot'],contract=meta['contract'])
                if args.capture:
                    from mt5_provider import fetch_history
                    from aurelia_fx.agent_history import collect_training_history
                    captured=collect_training_history(repo,fetch_history,days=60,expected_clock_id=meta['clock_id'])
                    if captured['status']!='ready':raise ValueError('Recent history quality not ready')
                now=datetime.now(timezone.utc)
                rows=repo.candles(clock_id=meta['clock_id'],timeframe='M5',start=now-timedelta(days=60),as_of=now,known_by=now)
                measured=summarize(rows,'M5',start=now-timedelta(days=60),as_of=now,days=60)
                report['recent_data']=dict(as_of=now.isoformat(),known_by=now.isoformat(),statistics=measured)
                if not measured['ready']:raise ValueError('Recent PostgreSQL history not ready')
                start=max(utc(meta['as_of']),now-timedelta(days=30))
                samples=recent_candidates(rows,start=start,progress=emit)
                report['post_catalog_exploratory']=evaluate(rows,samples,start=start,end=now,lot=meta['lot'],contract=meta['contract'])
                forward_start=utc(registration['registered_at'])
                report['prospective']=evaluate(rows,samples,start=forward_start,end=now,lot=meta['lot'],contract=meta['contract'])
                report['prospective_elapsed_days']=(now-forward_start).total_seconds()/86400
                report['prospective_status']='INCONCLUSIVE'
                if report['prospective_elapsed_days']>=7 and all(report['prospective'][k]['portfolios']['h4_h1']['closed_trades']>=20 for k in ('expiry_fixed','efficiency55','confirmations2')):
                    report['prospective_status']='READY_FOR_REVIEW_NOT_PROMOTED'
                report['report_id']=fingerprint(report)
                memory.record_project_data('agent_regime_study_report',report['report_id'],report)
                path=ROOT/'data/reports/regime-study.json';path.parent.mkdir(exist_ok=True,parents=True)
                path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                emit(dict(report_id=report['report_id'],prospective_status=report['prospective_status'],path=str(path),
                    results={period:{k:{p:{x:r[x] for x in ('candidate_signals','closed_trades','wins','losses','net_pnl','win_rate_pct')} for p,r in v['portfolios'].items()} for k,v in report[period].items()} for period in ('historical','post_catalog_exploratory','prospective') if period in report}))
            finally:lease.execute('SELECT pg_advisory_unlock(70616071)')
    finally:memory.close()


if __name__=='__main__':main()
