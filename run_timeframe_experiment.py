"""Fixed M15/H1 comparison; execute and assess risk on original M5 prices."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
SOURCE='d648f4439e23fb24d2cc880ea9c9507c4bc3fb31860d14d92db1f87e0a54a07d'
PROFILES={
    'M5':dict(execution='M5',context='H1',confirmation='M15',macro='H4'),
    'M15':dict(execution='M15',context='H1',confirmation='H1',macro='H4'),
    'H1':dict(execution='H1',context='H4',confirmation='H4',macro='D1'),
}


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.agent_research import intelligence_session,SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap,slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.literature_strategies import FAMILIES,PARAMETERS,setups
    from aurelia_fx.trend import timeframe_seconds
    from run_literature_experiment import simulate,choose
    from run_year_validation import windows
    memory=open_memory();emit=lambda d:print(json.dumps(d,ensure_ascii=True),flush=True)
    def read(kind,key):
        with memory.pool.connection() as c:
            row=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if not row:raise ValueError('Missing frozen source')
        value=json.loads(row['payload_json'])
        if memory._encode(value)[1]!=row['payload_sha256']:raise ValueError('Frozen source integrity mismatch')
        return value
    try:
        import psutil
        try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
        except (psutil.Error,AttributeError):pass
        old=read('agent_literature_experiment',SOURCE)
        year=read('agent_year_experiment',old['protocol']['source'])
        baseline=year['baseline']
        files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/'run_timeframe_experiment.py',ROOT/'run_literature_experiment.py',ROOT/'run_year_validation.py']
        protocol=dict(version='larger-execution-timeframes-v1',source=SOURCE,baseline=baseline['baseline_id'],
            profiles=PROFILES,parameters=PARAMETERS,
            motivation='Previous M5 gross advantage was smaller than observed/assumed execution costs; test larger structural horizons, not cheaper fictional fees',
            signal='only complete closed execution candles emitted exactly at their nominal close; no stale or unfinished HTF entry',
            calendar='known weekly closures allowed in M15/H1 patterns; unexpected base-M5 gaps reset all contexts; M5 original logic preserved for exact controls',
            holding='24 execution candles: M5 2h, M15 6h, H1 24h nominal; all flattened at known trading-session/calendar close, no overnight model',
            comparison='same four families and bar-count thresholds; H1 execution uses H4 direction/confirmation and D1 macro; higher timeframe ATR/stop/target, original M5 intrabar execution',
            correlation='M15 context/confirmation both H1 and H1 context/confirmation both H4 are correlated, not independent evidence',
            boundary='all 12 matrix arms use common 24h no-new-entry purge at every period end; original M5 control reproduced separately with original2h purge',
            selection='Jan-Jun only, only M15/H1 arms: >=50 closed,positive net,PF>=1.1; rank net expectancy. None eligible means no winner',
            confirmation='Jul-Sep: >=20 closed,positive net,PF>=1.1 and positive net under spreadx1.5/slippage.4pip; no lock/censored/pending',
            risk='same lot.01,equity10000,risk.5pct,daily2pct,drawdown5pct,max5/day,maxspread2,minnetRR2',
            costs='actual historical spread,.2pip slippage,USD35/million/side assumption; unchanged targets in stress',
            data_status='2026 previously researched, not independent OOS; no parameter search, promotion, Timestral training or orders',
            code_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            registered_at=datetime.now(timezone.utc).isoformat(),live_policy_changed=False,orders_sent=0)
        protocol['protocol_id']=fingerprint(protocol)
        memory.record_project_data('agent_timeframe_protocol',protocol['protocol_id'],protocol)
        emit(dict(stage='protocol_registered',protocol_id=protocol['protocol_id']))
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_year_history');candles=candles_from(rows)
        agg=intelligence_session().aggregator;sessions=SessionEngine(SESSIONS);previous=None
        samples={tf+':'+family:[] for tf in PROFILES for family in FAMILIES};events=set()
        for i,bar in enumerate(candles):
            if i%10000==0:emit(dict(stage='closed_candle_generation',processed=i,total=len(candles)))
            if previous and unexpected_broker_gap(previous,bar,300):agg.reset()
            histories=agg.add(bar);previous=bar;known=bar.timestamp+timedelta(minutes=5)
            active=sessions.identify(known).active_sessions
            if bar.timestamp<utc(baseline['first_label_at']) or not active or not slot_tradable(known):continue
            for tf,profile in PROFILES.items():
                execution=histories[tf];seconds=timeframe_seconds(tf)
                if not execution or execution[-1].timestamp+timedelta(seconds=seconds)!=known:continue
                for family,s in setups(histories,**profile).items():
                    event=(tf,family,s['event'],s['candidate'].side)
                    if event in events:continue
                    events.add(event);c=s.pop('candidate');arm=tf+':'+family
                    # Preserve exact old M5 identity/context for an actual reproduction assertion.
                    sid=(family if tf=='M5' else arm)+':'+known.isoformat()
                    snapshot=dict(snapshot_id=sid,session=list(active),regime='FAMILY_'+family.upper(),research_context=s)
                    samples[arm].append(dict(sample_id=sid,signal_at=known.isoformat(),entry_at=known.isoformat(),snapshot=snapshot,
                        candidate=dict(side=c.side,entry=c.entry,stop=c.stop,target=c.target,expires_at=c.expires_at.isoformat(),evidence=list(c.evidence))))
        for family in FAMILIES:
            if samples['M5:'+family]!=old['signals'][family]:raise ValueError('M5 signal/control regression: '+family)
        emit(dict(stage='signals_sealed_m5_exact',counts={a:len(v) for a,v in samples.items()}))
        memory.record_project_data('agent_timeframe_signals',protocol['protocol_id'],dict(samples=samples))
        start,end=utc(baseline['first_label_at']),utc(baseline['as_of'])
        boundaries=dict(development=(start,datetime(2026,7,1,tzinfo=timezone.utc)),
            check_previously_seen=(datetime(2026,7,1,tzinfo=timezone.utc),datetime(2026,10,1,tzinfo=timezone.utc)))
        boundaries.update(windows(2026,end));results={};stress={};selected=None
        for period,(a,b) in boundaries.items():
            results[period]={}
            for arm,signals in samples.items():
                emit(dict(stage='portfolio',period=period,arm=arm))
                holding=24*timeframe_seconds(arm.split(':')[0])//300
                results[period][arm]=simulate(signals,candles,start=a,end=b,holding_bars=holding,purge_hours=24)
            if period=='development':
                selected=choose({arm:v for arm,v in results[period].items() if not arm.startswith('M5:')})
                memory.record_project_data('agent_timeframe_selection',protocol['protocol_id'],dict(selected=selected,scope='development_only'))
                emit(dict(stage='development_choice_frozen',selected=selected))
            if period in ('all','check_previously_seen'):
                stress[period]={arm:simulate(signals,candles,start=a,end=b,holding_bars=24*timeframe_seconds(arm.split(':')[0])//300,purge_hours=24,stress=True)
                    for arm,signals in samples.items() if not arm.startswith('M5:')}
        controls={}
        for family in FAMILIES:
            controls[family]=simulate(samples['M5:'+family],candles,start=start,end=end)
            if controls[family]!=old['results']['all'][family]:raise ValueError('Original M5 portfolio reproduction failed: '+family)
        check=results['check_previously_seen'].get(selected) if selected else None
        stressed=stress['check_previously_seen'].get(selected) if selected else None
        clean=lambda v:v is not None and not v['account_locked'] and not v['unresolved_position'] and not v['censored_trades']
        passed=bool(clean(check) and clean(stressed) and check['closed_trades']>=20 and check['net_pnl']>0 and (check['profit_factor'] or 0)>=1.1 and stressed['net_pnl']>0)
        report=dict(protocol=protocol,baseline=baseline,results=results,stress=stress,original_m5_controls=controls,
            selected_on_development=selected,exploratory_check_passed=passed,m5_signals_and_portfolios_exact=True,
            independent_validation=False,live_policy_changed=False,orders_sent=0,completed_at=datetime.now(timezone.utc).isoformat())
        report['report_id']=fingerprint(report);memory.record_project_data('agent_timeframe_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('timeframes-'+report['report_id'][:12]+'.json');path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],selected=selected,exploratory_check_passed=passed,
            results={a:{k:v[k] for k in ('closed_trades','wins','losses','net_pnl','expectancy_usd','profit_factor','censored_trades','unresolved_position')} for a,v in results['all'].items()}))
    finally:memory.close()


if __name__=='__main__':main()
