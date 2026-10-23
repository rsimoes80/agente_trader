"""Fixed session-policy comparison on frozen H1 entries, full M5 portfolio replay."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
UTC=timezone.utc
SOURCE='50f2555e7fd9bef884744624196004bb0517992cdef16ad9d1853064a09288ff'
ARMS=('reference','exclude_new_york_only','london_only','avoid_last_two_hours')


def permits(sample,arm):
    from aurelia_fx.agent_research import SESSIONS
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.historical.core import utc
    if arm not in ARMS:
        raise ValueError('Unknown time policy')
    when=utc(sample['entry_at'])
    sessions=SessionEngine(SESSIONS)
    active=frozenset(sessions.identify(when).active_sessions)
    if not active:
        return False
    if arm=='reference':
        return True
    if arm=='exclude_new_york_only':
        return 'london' in active
    if arm=='london_only':
        return active=={'london'}
    return bool(sessions.identify(when+timedelta(hours=2)).active_sessions)


def choose(results):
    from run_h1_extended_validation import qualified
    eligible=[(arm,p) for arm,p in results.items() if arm!='reference'
              and qualified(p['normal'],p['stress'],50)]
    return max(eligible,key=lambda item:(item[1]['normal']['expectancy_usd'],item[0]))[0] if eligible else None


def main():
    import psutil
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc,closed_rows,summarize
    from aurelia_fx.regime_study import candles_from
    from run_h1_extended_validation import generate,qualified
    from run_literature_experiment import simulate
    try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error,AttributeError):pass
    memory=open_memory();repo=HistoricalRepository(memory)
    emit=lambda x:print(json.dumps(x,ensure_ascii=True),flush=True)
    def read(kind,key):
        with memory.pool.connection() as connection:
            row=connection.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if row is None:raise ValueError('Missing immutable source '+kind)
        x=json.loads(row['payload_json'])
        if memory._encode(x)[1]!=row['payload_sha256']:raise ValueError('Integrity mismatch')
        return x
    try:
        source=read('agent_h1_extended_experiment',SOURCE)
        files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/p for p in
            ('run_h1_hours_experiment.py','run_h1_extended_validation.py','run_literature_experiment.py','mt5_provider.py')]
        review=json.loads((ROOT/'data/knowledge/literature_families.json').read_text(encoding='utf-8'))
        for book in review['sources']:
            if hashlib.sha256((ROOT/'Aprendizado'/book['document']).read_bytes()).hexdigest()!=book['sha256']:
                raise ValueError('Literature manifest mismatch')
        protocol=dict(version='h1-session-policies-v1',source=SOURCE,arms=ARMS,
            registered_at=datetime.now(UTC).isoformat(),code_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            literature_review=review,
            motivation='Context and follow-through from technical literature; fixed risk and repeated observations from Douglas. Exact London/NY windows and2hour threshold are engineering hypotheses, not book prescriptions.',
            definitions=dict(reference='Original London08..17 + NewYork08..17 union',exclude_new_york_only='Permit if London active, including overlap',
                london_only='London active AND NewYork inactive',avoid_last_two_hours='Permit if union of sessions remains active at entry+2hours'),
            timezone='Europe/London and America/New_York DST-aware; never fixed UTC/Brazil offsets',
            unchanged='Frozen H1 breakout-retest candidates; original M5 prices,next-open,lot.01,risk,observedspread,commission35/million/sideassumption,slippage.2pip,3R,holding288M5,purge24h,sessionbuffer5min',
            simulation='Filter original eligible signals then rerun entire portfolio; exits retain original union sessions, not force-close when entry window ends. Do not remove closed trades after outcome.',
            stress='Same frozen candidates/targets; spreadx1.5,slippage.4pip; risk vetoes can change filled set',
            selection='2021..2023 joint portfolio only: among three alternatives >=50closed,net>0,PF>=1.1,positive stressNET,clean; rank normal net expectancy then arm name. Freeze BEFORE2020holdout outcomes.',
            checks='Selected must meet >=20closed,net>0,PF>=1.1,positive stressNET,clean separately in2024 and2020MayDec. 2025 reportcensor/lock honestly, never repair by deleting exposure.',
            novelty='Time-policy families motivated AFTER annual/context outcomes;2021..2026 already researched.2020MayDec additional earlier historical check not genuine prospectiveOOS.',
            reserve='2020May1..2021Jan1, warmupApril2020; no prior strategy results calculated on this reserve in this research',
            quality='Report all arm-years,source gaps,coverage,and no-censor flags. Generic monthly ready may befalseafterweeklyclose; no hidden override.',
            automatic_promotion=False,live_policy_changed=False,orders_sent=0)
        protocol['protocol_id']=fingerprint(protocol);key=protocol['protocol_id']
        memory.record_project_data('agent_h1_hours_protocol',key,protocol)
        emit(dict(stage='protocol_registered',protocol_id=key))
        # Freeze additional archive before any time-policy outcomes, without training on its results.
        capture=read('agent_h1_extended_capture',source['protocol']['protocol_id'])
        path=ROOT/'data/reports'/capture['raw_path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=capture['raw_sha256']:
            raise ValueError('Raw reserve snapshot mismatch')
        import numpy as np
        import mt5_provider as provider
        raw=np.load(path,mmap_mode='r',allow_pickle=False)
        start=datetime(2020,4,1,tzinfo=UTC);end=datetime(2021,1,1,tzinfo=UTC)
        wall=raw[(raw['time']>=int((start-timedelta(days=1)).timestamp()))&(raw['time']<int((end+timedelta(days=1)).timestamp()))]
        clock=capture['metadata']['source_clock']
        normalized=provider._CLOCK.normalize_bars(wall,clock)
        if capture['metadata']['pip_size']!=.0001 or capture['metadata']['digits']!=5:
            raise ValueError('Unexpected pip convention')
        rows=[dict(timestamp=stamp,source_time_epoch=epoch,source_utc_offset_seconds=offset,
            open=float(r['open']),high=float(r['high']),low=float(r['low']),close=float(r['close']),
            volume=float(r['tick_volume']),spread_pips=float(r['spread'])/10)
            for r,(stamp,epoch,offset) in zip(wall,normalized)]
        rows=closed_rows(rows,'M5',start=start,as_of=end)
        for i in range(0,len(rows),5000):repo.ingest(rows[i:i+5000],clock=clock,timeframe='M5')
        frozen=repo.candles(clock_id=clock['clock_id'],timeframe='M5',start=start,as_of=end)
        fields=('timestamp','source_time_epoch','source_utc_offset_seconds','open','high','low','close','volume','spread_pips')
        canonical=lambda seq:[{k:r.get(k) for k in fields} for r in seq]
        if canonical(rows)!=canonical(frozen):raise ValueError('Reserve differs from MT5 immutable source')
        reserve=dict(baseline_id=key+':2020',version='h1-hours-reserve-v1',source_capture=capture['protocol_id'],
            start=start.isoformat(),first_label_at=datetime(2020,5,1,tzinfo=UTC).isoformat(),as_of=end.isoformat(),days=(end-start).days,
            clock_id=clock['clock_id'],source_clock=clock,timeframes={'M5':summarize(frozen,'M5',start=start,as_of=end,days=(end-start).days)})
        memory.record_project_data('agent_h1_hours_history',reserve['baseline_id'],reserve)
        emit(dict(stage='reserve_frozen',bars=len(frozen),coverage=reserve['timeframes']['M5']['coverage']))
        del rows,frozen,wall,raw,normalized
        # Known development only, before generating or assessing reserve signals.
        candles=[];signals=[]
        for year in ('2021','2022','2023'):
            baseline=source['baselines'][year]
            _,rows=repo.frozen_candles(baseline,record_type='agent_h1_extended_history')
            candles.extend(c for c in candles_from(rows) if c.timestamp>=utc(baseline['first_label_at']))
            signals.extend(read('agent_h1_extended_signals',source['protocol']['protocol_id']+':'+year)['signals'])
        def replay(ss,cs,a,b):
            out={}
            for arm in ARMS:
                filtered=[s for s in ss if permits(s,arm)]
                args=dict(start=a,end=b,holding_bars=288,purge_hours=24,session_buffer_minutes=5)
                out[arm]=dict(normal=simulate(filtered,cs,**args),stress=simulate(filtered,cs,stress=True,**args),
                    source_signals=len(ss),permitted_signals=len(filtered))
            return out
        results=dict(development_2021_2023=replay(signals,candles,datetime(2021,1,1,tzinfo=UTC),datetime(2024,1,1,tzinfo=UTC)))
        expected=source['results']['qualification_2021_2023']
        if results['development_2021_2023']['reference']['normal']!=expected:
            raise ValueError('Development reference regression')
        selected=choose(results['development_2021_2023'])
        memory.record_project_data('agent_h1_hours_selection',key,dict(selected=selected,scope='development2021..2023 ONLY',at=datetime.now(UTC).isoformat()))
        emit(dict(stage='selection_frozen',selected=selected))
        for year,baseline in source['baselines'].items():
            _,rows=repo.frozen_candles(baseline,record_type='agent_h1_extended_history');cs=candles_from(rows)
            ss=read('agent_h1_extended_signals',source['protocol']['protocol_id']+':'+year)['signals']
            results[year]=replay(ss,cs,utc(baseline['first_label_at']),utc(baseline['as_of']))
            for scenario in ('normal','stress'):
                expected=source['results' if scenario=='normal' else 'stress'][year]
                if results[year]['reference'][scenario]!=expected:
                    raise ValueError('Annual reference regression '+year+scenario)
            emit(dict(stage='year_complete',year=year,results={arm:{k:r['normal'][k] for k in ('closed_trades','net_pnl','profit_factor','censored_trades')} for arm,r in results[year].items()}))
        _,rows=repo.frozen_candles(reserve,record_type='agent_h1_hours_history');cs=candles_from(rows)
        ss=generate(cs,utc(reserve['first_label_at']))
        memory.record_project_data('agent_h1_hours_signals',key+':2020',dict(signals=ss))
        results['reserve_2020_may_dec']=replay(ss,cs,utc(reserve['first_label_at']),utc(reserve['as_of']))
        checks={period:bool(selected and qualified(results[period][selected]['normal'],results[period][selected]['stress'],20))
                for period in ('2024','2025','reserve_2020_may_dec')}
        report=dict(protocol=protocol,reserve=reserve,results=results,selected_on_development=selected,
            selected_check_passed=checks,all_checks_passed=bool(selected and all(checks.values())),
            independent_prospective_validation=False,orders_sent=0,live_policy_changed=False,
            completed_at=datetime.now(UTC).isoformat())
        report['report_id']=fingerprint(report)
        memory.record_project_data('agent_h1_hours_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('h1-hours-'+report['report_id'][:12]+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],selected=selected,checks=checks,
            reserve={arm:{k:r['normal'][k] for k in ('closed_trades','net_pnl','profit_factor','censored_trades')} for arm,r in results['reserve_2020_may_dec'].items()}))
    finally:memory.close()


if __name__=='__main__':main()
