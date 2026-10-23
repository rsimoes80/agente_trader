"""Fixed literature families beyond breakout/retest; full portfolios, no orders."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
SOURCE='50f2555e7fd9bef884744624196004bb0517992cdef16ad9d1853064a09288ff'
HOURS='2be30ccf58ecdb26d43b1793b4a1201974d6822466004ee6e1f19a93769161a3'
FAMILIES=('trend_pullback','range_failure','reversal_shift')
ARMS=tuple(f+':'+h for f in FAMILIES for h in ('reference','exclude_new_york_only'))


def generate(candles,start):
    from aurelia_fx.agent_research import intelligence_session,SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap,slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.literature_strategies import setups,FAMILIES as ALL
    from run_h1_extended_validation import PROFILE
    agg=intelligence_session().aggregator;sessions=SessionEngine(SESSIONS)
    previous=None;seen=set();pools={f:[] for f in ALL}
    for bar in candles:
        if previous and unexpected_broker_gap(previous,bar,300):agg.reset()
        h=agg.add(bar);previous=bar;known=bar.timestamp+timedelta(minutes=5)
        active=sessions.identify(known).active_sessions
        if bar.timestamp<start or not active or not slot_tradable(known) or not h['H1'] or h['H1'][-1].timestamp+timedelta(hours=1)!=known:continue
        for family,setup in setups(h,**PROFILE).items():
            c=setup.pop('candidate');event=(family,setup['event'],c.side)
            if event in seen:continue
            seen.add(event);sid='H1:'+family+':'+known.isoformat()
            pools[family].append(dict(sample_id=sid,signal_at=known.isoformat(),entry_at=known.isoformat(),
                snapshot=dict(snapshot_id=sid,session=list(active),regime='FAMILY_'+family.upper(),research_context=setup),
                candidate=dict(side=c.side,entry=c.entry,stop=c.stop,target=c.target,expires_at=c.expires_at.isoformat(),evidence=list(c.evidence))))
    return pools


def main():
    import psutil
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.literature_strategies import PARAMETERS
    from run_h1_hours_experiment import permits
    from run_h1_extended_validation import qualified
    from run_literature_experiment import simulate
    try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error,AttributeError):pass
    memory=open_memory();repo=HistoricalRepository(memory);emit=lambda x:print(json.dumps(x,ensure_ascii=True),flush=True)
    def read(kind,key):
        with memory.pool.connection() as c:r=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if r is None:raise ValueError('Missing immutable record '+kind)
        x=json.loads(r['payload_json'])
        if memory._encode(x)[1]!=r['payload_sha256']:raise ValueError('Source integrity mismatch')
        return x
    try:
        source=read('agent_h1_extended_experiment',SOURCE)
        hours=read('agent_h1_hours_protocol',HOURS)
        files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/p for p in ('run_h1_family_validation.py','run_h1_hours_experiment.py','run_h1_extended_validation.py','run_literature_experiment.py')]
        protocol=dict(version='h1-other-literature-families-v1',source=SOURCE,hours_protocol=HOURS,
            registered_at=datetime.now(timezone.utc).isoformat(),families=FAMILIES,arms=ARMS,parameters=PARAMETERS,
            code_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            literature_review=hours['literature_review'],
            hypotheses='H1 structural correction/resumption,range failure,reversal shift; exact existing literature definitions,2predeclaredsessionpolicies, no new numeric tuning or combinations',
            risk='Same lot.01/equity10k/risk.5pct/daily2pct/DD5pct/maxspread2/minnetRR2/max5day; no relaxation even for countertrend/range research',
            execution='Original M5nextopen/stopfirst,source gaps retained,holding288M5,purge24h,5minbuffer,quoteaware3R exceptboundedrange target; standard and stress costs unchanged',
            controls='Regenerated breakout_retest pool must EXACTLYmatch existing frozen signals peryear. 2026all4pools also exact original12matrixcontrol.',
            selection='Pooled2021..2023 among6arms >=50closed,net>0,PF>=1.1,positive stressNET,clean; rank net expectancy then arm. Freeze selection before checks; no winner substitution.',
            check='2024,2025,2020MayDec separately >=20closed,net>0,PF>=1.1,positive stressNET,clean.2025censor remains failure,not deleted.',
            caveat='Research follows known negative2024 time-policy findings.2020already allocated to prior timepolicy check,so not a fresh independentOOS reserve for this familysearch. All historical evidence exploratory; prospective validation still required.',
            automatic_promotion=False,orders_sent=0,live_policy_changed=False)
        protocol['protocol_id']=fingerprint(protocol);key=protocol['protocol_id']
        memory.record_project_data('agent_h1_family_protocol',key,protocol);emit(dict(stage='protocol_registered',protocol_id=key))
        datasets={};pools={}
        def load(year,baseline,kind):
            _,rows=repo.frozen_candles(baseline,record_type=kind);cs=candles_from(rows)
            ps=generate(cs,utc(baseline['first_label_at']))
            if year!='2020':
                expected=read('agent_h1_extended_signals',source['protocol']['protocol_id']+':'+year)['signals']
                if ps['breakout_retest']!=expected:raise ValueError('Frozen breakout control changed '+year)
            memory.record_project_data('agent_h1_family_signals',key+':'+year,dict(samples=ps))
            emit(dict(stage='signals_sealed',year=year,counts={f:len(s) for f,s in ps.items()}))
            return cs,ps
        for year in ('2021','2022','2023'):
            datasets[year],pools[year]=load(year,source['baselines'][year],'agent_h1_extended_history')
        def run(cs,ps,a,b,label):
            out={}
            for arm in ARMS:
                family,policy=arm.split(':')
                ss=[s for s in ps[family] if permits(s,policy)]
                kw=dict(start=a,end=b,holding_bars=288,purge_hours=24,session_buffer_minutes=5)
                out[arm]=dict(normal=simulate(ss,cs,**kw),stress=simulate(ss,cs,stress=True,**kw))
                emit(dict(stage='portfolio',period=label,arm=arm,closed=out[arm]['normal']['closed_trades'],net=out[arm]['normal']['net_pnl']))
            return out
        joint=[c for year in ('2021','2022','2023') for c in datasets[year] if c.timestamp>=datetime(int(year),1,1,tzinfo=timezone.utc)]
        ss={f:[s for year in ('2021','2022','2023') for s in pools[year][f]] for f in FAMILIES}
        results=dict(development_2021_2023=run(joint,ss,datetime(2021,1,1,tzinfo=timezone.utc),datetime(2024,1,1,tzinfo=timezone.utc),'development'))
        eligible=[(arm,r) for arm,r in results['development_2021_2023'].items() if qualified(r['normal'],r['stress'],50)]
        selected=max(eligible,key=lambda item:(item[1]['normal']['expectancy_usd'],item[0]))[0] if eligible else None
        memory.record_project_data('agent_h1_family_selection',key,dict(selected=selected,scope='development_only'))
        emit(dict(stage='selection_frozen',selected=selected))
        del joint
        for year,baseline in source['baselines'].items():
            if year not in datasets:datasets[year],pools[year]=load(year,baseline,'agent_h1_extended_history')
            results[year]=run(datasets[year],pools[year],utc(baseline['first_label_at']),utc(baseline['as_of']),year)
            del datasets[year]
        reserve=read('agent_h1_hours_history',HOURS+':2020')
        cs,ps=load('2020',reserve,'agent_h1_hours_history')
        results['2020_may_dec_previously_allocated']=run(cs,ps,utc(reserve['first_label_at']),utc(reserve['as_of']),'2020')
        # Existing selected-discovery signal reconstruction, not another optimization window.
        original=read('agent_timeframe_experiment','ccecb7be961363c5b4abb43307e1309031789bfe1455fd798ad87065bf6950b1')
        _,rows=repo.frozen_candles(original['baseline'],record_type='agent_year_history')
        actual=generate(candles_from(rows),utc(original['baseline']['first_label_at']))
        expected=read('agent_timeframe_signals',original['protocol']['protocol_id'])['samples']
        if any(actual[f]!=expected['H1:'+f] for f in actual):raise ValueError('Original all-family signal regression')
        checks={p:bool(selected and qualified(results[p][selected]['normal'],results[p][selected]['stress'],20)) for p in ('2024','2025','2020_may_dec_previously_allocated')}
        report=dict(protocol=protocol,results=results,selected=selected,checks=checks,all_checks_passed=bool(selected and all(checks.values())),
            controls_exact=True,orders_sent=0,live_policy_changed=False,independent_prospective_validation=False,completed_at=datetime.now(timezone.utc).isoformat())
        report['report_id']=fingerprint(report);memory.record_project_data('agent_h1_family_experiment',report['report_id'],report)
        (ROOT/'data/reports'/('h1-family-'+report['report_id'][:12]+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],selected=selected,checks=checks))
    finally:memory.close()


if __name__=='__main__':main()
