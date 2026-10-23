"""Separately preregister a uniform one-M5-bar session buffer after gap audit."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
SOURCE='ccecb7be961363c5b4abb43307e1309031789bfe1455fd798ad87065bf6950b1'


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from run_literature_experiment import simulate,choose
    from aurelia_fx.trend import timeframe_seconds
    from run_year_validation import windows
    memory=open_memory();emit=lambda d:print(json.dumps(d,ensure_ascii=True),flush=True)
    def read(kind,key):
        with memory.pool.connection() as c:row=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if not row:raise ValueError('Missing source')
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Integrity mismatch')
        return data
    try:
        import psutil
        try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
        except (psutil.Error,AttributeError):pass
        source=read('agent_timeframe_experiment',SOURCE)
        signals=read('agent_timeframe_signals',source['protocol']['protocol_id'])['samples']
        audit=read('agent_timeframe_censor_audit',SOURCE)
        files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/'run_literature_experiment.py',ROOT/'run_timeframe_session_check.py',ROOT/'run_timeframe_experiment.py',ROOT/'run_year_validation.py']
        protocol=dict(version='timeframe-session-buffer-v1',source=SOURCE,
            rationale='Post-result audit found source gap starts in final M5 slot before NY session close; both MT5 recapture methods still lack bars',
            caveat='Explicitly motivated after original outcomes, not independent validation or data repair; original failed/censored report retained',
            modification='Uniform5min buffer at session end on EVERY date and arm; no new entries in buffer and close existing positions one M5 bar early',
            gap_specific_exit=False,interpolation=False,parameter_search=False,
            unchanged=source['protocol'],session_buffer_minutes=5,
            selection='Same Jan-Jun >=50closed/positiveNET/PF1.1; only M15/H1; select before Jul-Sep results',
            confirmation='Same Jul-Sep >=20closed/positiveNET/PF1.1 and positive stressNET, no censored/locked/pending',
            code_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            registered_at=datetime.now(timezone.utc).isoformat(),orders_sent=0,live_policy_changed=False)
        protocol['protocol_id']=fingerprint(protocol)
        memory.record_project_data('agent_timeframe_session_protocol',protocol['protocol_id'],protocol)
        emit(dict(stage='protocol_registered',protocol_id=protocol['protocol_id']))
        _,rows=HistoricalRepository(memory).frozen_candles(source['baseline'],record_type='agent_year_history');candles=candles_from(rows)
        start,end=utc(source['baseline']['first_label_at']),utc(source['baseline']['as_of'])
        boundaries=dict(development=(start,datetime(2026,7,1,tzinfo=timezone.utc)),
            check_previously_seen=(datetime(2026,7,1,tzinfo=timezone.utc),datetime(2026,10,1,tzinfo=timezone.utc)))
        boundaries.update(windows(2026,end));results={};stress={};selected=None
        def run(arm,a,b,stressed=False):
            return simulate(signals[arm],candles,start=a,end=b,holding_bars=24*timeframe_seconds(arm.split(':')[0])//300,purge_hours=24,session_buffer_minutes=5,stress=stressed)
        for period,(a,b) in boundaries.items():
            results[period]={}
            for arm in signals:
                emit(dict(stage='portfolio',period=period,arm=arm))
                results[period][arm]=run(arm,a,b)
            if period=='development':
                selected=choose({arm:v for arm,v in results[period].items() if not arm.startswith('M5:')})
                memory.record_project_data('agent_timeframe_session_selection',protocol['protocol_id'],dict(selected=selected,scope='development_only'))
                emit(dict(stage='selection_frozen',selected=selected))
            if period in ('all','check_previously_seen'):
                stress[period]={arm:run(arm,a,b,True) for arm in signals if not arm.startswith('M5:')}
        check=results['check_previously_seen'].get(selected) if selected else None
        worse=stress['check_previously_seen'].get(selected) if selected else None
        clean=lambda v:v is not None and not v['account_locked'] and not v['unresolved_position'] and not v['censored_trades']
        passed=bool(clean(check) and clean(worse) and check['closed_trades']>=20 and check['net_pnl']>0 and (check['profit_factor'] or 0)>=1.1 and worse['net_pnl']>0)
        report=dict(protocol=protocol,baseline=source['baseline'],results=results,stress=stress,
            selected_on_development=selected,exploratory_check_passed=passed,independent_validation=False,
            source_gap_still_present=True,prices_changed=False,orders_sent=0,live_policy_changed=False,
            completed_at=datetime.now(timezone.utc).isoformat())
        report['report_id']=fingerprint(report);memory.record_project_data('agent_timeframe_session_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('timeframes-session-'+report['report_id'][:12]+'.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],selected=selected,exploratory_check_passed=passed,
            results={a:{k:v[k] for k in ('closed_trades','wins','losses','net_pnl','expectancy_usd','profit_factor','account_locked','censored_trades','unresolved_position')} for a,v in results['all'].items()}))
    finally:memory.close()


if __name__=='__main__':main()
