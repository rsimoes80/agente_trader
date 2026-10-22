"""Compare H1 versus H4+H1 on the largest compatible frozen historical catalog."""
import json
from pathlib import Path
import subprocess
import sys
import hashlib
from collections import Counter
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.agent_strategy import SPEC_HASH
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.domain import Candle
    from aurelia_fx.trend_experiment import compare
    memory=open_memory()
    def decode(row):
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Record integrity failure')
        return data
    try:
        with memory.pool.connection() as c:
            datasets=[decode(r) for r in c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_dataset'").fetchall()]
            compatible=[d for d in datasets if fingerprint(d['manifest'].get('strategy',{}))==SPEC_HASH and d['manifest'].get('training_days')]
            dataset=max(compatible,key=lambda d:(d['manifest']['training_days'],d['manifest']['created_at']))
            manifest=dataset['manifest']
            samples=[decode(r) for r in c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_sample' AND record_key=ANY(%s)",(dataset['sample_ids'],)).fetchall()]
            if len(samples)!=len(set(dataset['sample_ids'])):raise ValueError('Incomplete or duplicated sample catalog')
            baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s ORDER BY recorded_at LIMIT 1",(manifest['baseline_id'],)).fetchone())
        print(json.dumps(dict(stage='loading_frozen_data',run_id=dataset['run_id'],samples=len(samples))),flush=True)
        frozen,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=[Candle(utc(r['timestamp']),*(r[k] for k in ('open','high','low','close')),r.get('volume',0),r.get('spread_pips')) for r in rows]
        report=dict(version='h1-vs-h4-h1-offline-v1',created_at=datetime.now(timezone.utc).isoformat(),
                    source_run_id=dataset['run_id'],source_manifest=manifest,frozen_baseline=frozen['baseline_id'],
                    candles=len(candles),sample_catalog=len(samples),
                    code_version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    implementation_sha256=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in
                        ['run_trend_experiment.py','src/aurelia_fx/trend_experiment.py'])).hexdigest(),
                    dirty_worktree=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
                    catalog_regimes=dict(Counter(s['snapshot'].get('regime','UNKNOWN') for s in samples)),
                    h1_aligned_confirmed_candidates_any_regime=sum(
                        (s['snapshot'].get('context_trend',{}).get('direction'),s['snapshot'].get('context_trend',{}).get('state'))
                        == {'long':('bullish','BULL_CONFIRMED'),'short':('bearish','BEAR_CONFIRMED')}.get(s['candidate']['side']) for s in samples),
                    protocol=dict(live_policy_changed=False,selection='largest_compatible_catalog_before_results',
                        changed_variable='H4 confirmation/alignment only',common_regime='TREND',
                        h1='confirmed and side aligned',initial_equity_usd=10000,one_position=True,
                        daily_entry_limit=5,maximum_holding_m5_bars=12,
                        costs='existing ExecutionSimulator: observed spread, 0.2 pip slippage per market fill, commission 35 per million per side; no adverse slippage on target limits',
                        final_window_is_new_holdout=False,statistical_causality_claim=False,
                        limitations=['retrospective catalog of previously closed standalone candidates; not all market bars are candidates',
                                     'no adaptive hypothesis selection or Timestral weight training',
                                     'Wilson intervals descriptive; temporal independence not assumed',
                                     'no guarantee of future or demo account performance']),
                    results=compare(samples,candles,manifest))
        report['experiment_id']=fingerprint(report)
        memory.record_project_data('agent_trend_experiment',report['experiment_id'],report)
        target=ROOT/'data/reports'/('trend-'+report['experiment_id'][:12]+'.json')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(report_path=str(target),experiment_id=report['experiment_id'],results={k:{p:{x:v[x] for x in ('candidate_signals','closed_trades','wins','losses','win_rate_pct','net_pnl','max_close_equity_drawdown_pct','unresolved_position')} for p,v in values.items()} for k,values in report['results'].items()}),ensure_ascii=True),flush=True)
    finally:memory.close()


if __name__=='__main__':main()
