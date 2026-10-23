"""Full M15 portfolio sensitivity to zero commission observed in the demo sample."""
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
SOURCE='01bf0ca45b97360228660d8fc38bd0483f783491cca8fe1a27f5808aabd74669'


def zero_fee_simulator(original):
    def factory(units):
        engine=original(units)
        engine.config=replace(engine.config,commission_per_million_side=0)
        return engine
    return factory


def main():
    import psutil
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from run_h1_hours_experiment import permits
    from run_h1_extended_validation import qualified
    from run_literature_experiment import simulate
    import aurelia_fx.agent_research as research
    try:psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
    except (psutil.Error,AttributeError):pass
    memory=open_memory();repo=HistoricalRepository(memory);emit=lambda x:print(json.dumps(x,ensure_ascii=True),flush=True)
    def read(kind,key):
        with memory.pool.connection() as c:r=c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if r is None:raise ValueError('Missing immutable source '+kind)
        x=json.loads(r['payload_json'])
        if memory._encode(x)[1]!=r['payload_sha256']:raise ValueError('Source integrity mismatch')
        return x
    original=research.simulator
    try:
        source=read('agent_m15_family_experiment',SOURCE)
        archive=read('agent_h1_extended_experiment',source['protocol']['source'])
        evidence=json.loads((ROOT/'data/knowledge/broker_cost_evidence.json').read_text(encoding='utf-8'))
        files=sorted((ROOT/'src').rglob('*.py'))+[ROOT/p for p in ('run_demo_fee_sensitivity.py','run_literature_experiment.py','run_h1_hours_experiment.py','run_h1_extended_validation.py')]
        protocol=dict(version='m15-zero-demo-fee-sensitivity-v1',source=SOURCE,
            registered_at=datetime.now(timezone.utc).isoformat(),arms=source['protocol']['arms'],
            broker_cost_evidence=evidence,
            code_hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            modification='Only commission_per_million_side35->0 to reflect observed6demoexecutiondeals; no account tariff asserted. Full portfolio replay,not addback to closed trades.',
            unchanged='All8frozenM15familypools/timepolicies/targets/holding72M5/purge24h/sessionbuffer5/spread/slippage/risk/equity/lot.01/sourcearchive',
            comparison='Fee35 reference is exactly the immutable prior report,not recomputed or altered; fee0 is separate conditional profile',
            interpretation='Post-result cost sensitivity motivated by observed demo fees and official Standard/ThinkZero distinction,not independent strategyvalidation or free-cost optimization',
            selection='2021..2023only amongsame8arms >=50closed,net>0,PF>=1.1,positive spreadx1.5/slip.4stressNET,clean;rank net expectancy.Freeze beforechecks.',
            checks='Selected separately2024/2025/2020MayDec >=20closed/net>0/PF>=1.1/stresspositive/clean;no winner substitution,no removal of censored exposure',
            independent_prospective_validation=False,automatic_promotion=False,orders_sent=0,live_policy_changed=False)
        protocol['protocol_id']=fingerprint(protocol);key=protocol['protocol_id']
        memory.record_project_data('agent_demo_fee_protocol',key,protocol);emit(dict(stage='protocol_registered',protocol_id=key))
        research.simulator=zero_fee_simulator(original)
        def load(year,baseline,kind):
            _,rows=repo.frozen_candles(baseline,record_type=kind)
            pools=read('agent_m15_family_signals',source['protocol']['protocol_id']+':'+year)['samples']
            return candles_from(rows),pools
        def run(cs,pools,a,b,label):
            out={}
            for arm in protocol['arms']:
                family,policy=arm.split(':');ss=[s for s in pools[family] if permits(s,policy)]
                kw=dict(start=a,end=b,holding_bars=72,purge_hours=24,session_buffer_minutes=5)
                out[arm]=dict(normal=simulate(ss,cs,**kw),stress=simulate(ss,cs,stress=True,**kw))
                for pair in out[arm].values():
                    if any(t['financial_result']['commission']!=0 for t in pair['trades']):raise ValueError('Commission profile not applied')
                emit(dict(stage='portfolio',period=label,arm=arm,closed=out[arm]['normal']['closed_trades'],net=out[arm]['normal']['net_pnl']))
            return out
        cs=[];pools={f:[] for f in ('trend_pullback','breakout_retest','range_failure','reversal_shift')}
        for year in ('2021','2022','2023'):
            candles,ps=load(year,archive['baselines'][year],'agent_h1_extended_history')
            cs.extend(c for c in candles if c.timestamp>=datetime(int(year),1,1,tzinfo=timezone.utc))
            for f in pools:pools[f].extend(ps[f])
        results=dict(development_2021_2023=run(cs,pools,datetime(2021,1,1,tzinfo=timezone.utc),datetime(2024,1,1,tzinfo=timezone.utc),'development'))
        eligible=[(a,r) for a,r in results['development_2021_2023'].items() if qualified(r['normal'],r['stress'],50)]
        selected=max(eligible,key=lambda item:(item[1]['normal']['expectancy_usd'],item[0]))[0] if eligible else None
        memory.record_project_data('agent_demo_fee_selection',key,dict(selected=selected,scope='development_only'))
        emit(dict(stage='selection_frozen',selected=selected))
        del cs,pools
        for year,baseline in archive['baselines'].items():
            cs,ps=load(year,baseline,'agent_h1_extended_history')
            results[year]=run(cs,ps,utc(baseline['first_label_at']),utc(baseline['as_of']),year)
        reserve=read('agent_h1_hours_history',source['protocol']['hours_protocol']+':2020')
        cs,ps=load('2020',reserve,'agent_h1_hours_history')
        results['2020_may_dec_previously_allocated']=run(cs,ps,utc(reserve['first_label_at']),utc(reserve['as_of']),'2020')
        checks={p:bool(selected and qualified(results[p][selected]['normal'],results[p][selected]['stress'],20)) for p in ('2024','2025','2020_may_dec_previously_allocated')}
        report=dict(protocol=protocol,results=results,selected=selected,checks=checks,all_checks_passed=bool(selected and all(checks.values())),
            fee35_source=SOURCE,orders_sent=0,live_policy_changed=False,independent_prospective_validation=False,completed_at=datetime.now(timezone.utc).isoformat())
        report['report_id']=fingerprint(report);memory.record_project_data('agent_demo_fee_experiment',report['report_id'],report)
        (ROOT/'data/reports'/('demo-fees-'+report['report_id'][:12]+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],selected=selected,checks=checks))
    finally:
        research.simulator=original
        memory.close()


if __name__=='__main__':main()
