"""Audit current EURUSD proposal rules on an existing sealed plan, no broker I/O."""
import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))


def main():
    from aurelia_fx.agent_strategy import strategy_spec, strategy_hash
    from aurelia_fx.domain import Candle
    from aurelia_fx.historical.core import utc
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.operational_audit import scan, verify_partition
    from aurelia_fx.storage import open_memory
    from run_literature_experiment import simulate
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--warmup', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/reports')
    parser.add_argument('--compare-daytrade', action='store_true',help='Compare frozen H1-only and continuation hypotheses offline')
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    warmup = json.loads(args.warmup.read_text())
    cutoff = utc(plan['partitions']['holdout']['first_open'])
    start = utc(warmup['start'])
    output = args.output / ('operational-audit-' + str(uuid4()))
    output.mkdir(parents=True, exist_ok=False)
    output.chmod(0o700)
    emit = lambda **kw: print(json.dumps(kw), flush=True)
    memory = open_memory()
    try:
        with memory.pool.connection() as c:
            record = c.execute("SELECT payload_json,payload_sha256,recorded_at FROM project_records WHERE record_type='historical_warmup' AND record_key=%s ORDER BY recorded_at LIMIT 1", (warmup['baseline_id'],)).fetchone()
        if record is None or memory._encode(json.loads(record['payload_json']))[1] != record['payload_sha256']:
            raise ValueError('Fonte de aquecimento ausente ou inválida.')
        if json.loads(record['payload_json']) != warmup:
            raise ValueError('O aquecimento local difere da fonte persistida.')
        repo = HistoricalRepository(memory)
        rows = repo.candles(clock_id=warmup['clock_id'], timeframe='M5', start=start,
                            as_of=cutoff - timedelta(microseconds=1), known_by=record['recorded_at'])
        if not rows or any(utc(r['timestamp']) >= cutoff for r in rows):
            raise ValueError('Reserva final invadida ou fonte vazia.')
        verified = {label: verify_partition(rows, plan['partitions'][label])
                    for label in ('development', 'validation')}
        from aurelia_fx.entry_trend import H1_POLICY_ID, CONTINUATION_POLICY_ID
        comparisons=(H1_POLICY_ID,CONTINUATION_POLICY_ID) if args.compare_daytrade else ()
        protocol = dict(version='operational-proposal-audit-v1', reference_plan=plan['plan_id'],
            comparison_policies=list(comparisons),selection='No automatic winner selection or live promotion',
            code_version=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            dirty_worktree=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
            runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            audit_sha256=hashlib.sha256((ROOT/'src/aurelia_fx/operational_audit.py').read_bytes()).hexdigest(),
            strategy_source_sha256=hashlib.sha256((ROOT/'src/aurelia_fx/agent_strategy.py').read_bytes()).hexdigest(),
            guard_source_sha256=hashlib.sha256((ROOT/'src/aurelia_fx/entry_trend.py').read_bytes()).hexdigest(),
            dataset_sha256=memory._encode(rows)[1], source_known_by=record['recorded_at'].isoformat(),
            original_partition_hashes_verified=verified,
            holdout_start=cutoff.isoformat(), holdout='reserved_not_evaluated',
            strategy=strategy_spec(),strategy_hash=strategy_hash(),lot=.01,
            costs=dict(commission_per_million_side=35,slippage_pips=.2,
                       stress_spread_multiplier=1.5,stress_slippage_pips=.4),
            account='synthetic USD 10000; fixed 1000 EUR units (.01 standard lot)',
            scope='Strict operational proposal gates before model/continual-learning selection; no full-agent equivalence',
            model_gate='not bypassed for live trading; hypothetical proposal portfolios are separate research only',
            fitting=False,automatic_promotion=False,orders_sent=0)
        (output/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n')
        emit(stage='sealed',directory=str(output),bars=len(rows),holdout_start=cutoff.isoformat())
        reports={}
        for label in ('development','validation'):
            partition=plan['partitions'][label]
            a=utc(partition['first_open']);b=utc(partition['last_open'])+timedelta(minutes=5)
            if b>cutoff:raise ValueError('Partição invade a reserva.')
            report=scan(rows,start=a,end=b,progress=lambda **kw:emit(partition=label,**kw),compare_policies=comparisons)
            if report['evaluated_bars'] != partition['bars']:
                raise ValueError('A revisão do histórico mudou a partição selada.')
            candles=[Candle(utc(r['timestamp']),*(r[k] for k in ('open','high','low','close')),
                           r.get('volume',0),r.get('spread_pips')) for r in rows if a<=utc(r['timestamp'])<b]
            report['hypothetical_portfolios']={
                key:simulate(report['samples'],candles,start=a,end=b,stress=stress,holding_bars=12,purge_hours=1)
                for key,stress in (('normal',False),('stress',True))}
            for policy,comparison in report['policy_comparisons'].items():
                comparison['hypothetical_portfolios']={key:simulate(comparison['samples'],candles,start=a,end=b,
                    stress=stress,holding_bars=12,purge_hours=1) for key,stress in (('normal',False),('stress',True))}
            reports[label]=report
            (output/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
            emit(stage='partition_complete',partition=label,reasons=report['reasons'],
                 proposals=len(report['samples']),daily_context=report['daily_context'])
        final=dict(protocol=protocol,reports=reports,status='completed',directory=str(output))
        (output/'summary.json').write_text(json.dumps(final,indent=2)+'\n')
        memory.record_project_data('operational_proposal_audit',output.name,final)
        emit(stage='complete',directory=str(output))
    finally:memory.close()


if __name__=='__main__':main()
