"""Supplementary exploratory test of known-pivot legs versus fixed windows."""
import hashlib
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
SOURCE='fb8d9cd051243e66b9ad356f245ff50dd61627763b128d5ae3c6237732934af2'
PROTOCOL=dict(version='known-pivot-context-v1',source_context_report=SOURCE,
    motivation='post-result descriptive review found different leg segmentation, not evidence of profitability',
    arms=['reference','fixed_window','confirmed_pivot_leg'],
    definition='latest confirmed M5 high/low in trade direction whose bar closed before correction began; preceding opposite confirmed pivot is origin; both confirmations known by signal time',
    filter='pivot amplitude >=1 ATR14 from bars before origin, and original three-bar correction retraces >0 and <=50 percent of amplitude',
    missing='no valid pivot pair or prior ATR means filter fails',
    changed='leg representation: confirmed swing extremes and their actual duration instead of fixed six-bar open/close window',
    unchanged='sealed107 signals,H4/H1 direction,entry,stop,target2.5R,lot.01,costs,minnetRR2,daily5,12barholding,common120minboundarypurge',
    no_combinations=True,no_threshold_search=True,previously_seen_data=True,
    new_independent_validation=False,live_policy_changed=False,automatic_promotion=False,orders_sent=0)


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.agent_research import intelligence_session
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    from aurelia_fx.context_experiment import passes
    from aurelia_fx.trigger_exit_experiment import replay
    from run_context_review import leg
    memory=open_memory();emit=lambda d:print(json.dumps(d),flush=True)
    def decode(row):
        if not row:raise ValueError('Missing frozen record')
        value=json.loads(row['payload_json'])
        if memory._encode(value)[1]!=row['payload_sha256']:raise ValueError('Integrity mismatch')
        return value
    try:
        with memory.pool.connection() as c:
            context=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_context_experiment' AND record_key=%s LIMIT 1",(SOURCE,)).fetchone())
            source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_correction_experiment' AND record_key=%s LIMIT 1",(context['source_report'],)).fetchone())
            baseline=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s LIMIT 1",(context['baseline_id'],)).fetchone())
        sha=hashlib.sha256(b''.join((ROOT/p).read_bytes() for p in ['run_pivot_context_experiment.py','run_context_review.py','src/aurelia_fx/trigger_exit_experiment.py','src/aurelia_fx/context_experiment.py'])).hexdigest()
        key=fingerprint(dict(protocol=PROTOCOL,implementation_sha256=sha))
        with memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_pivot_context_protocol' AND record_key=%s LIMIT 1",(key,)).fetchone()
        registration=decode(row) if row else dict(protocol_id=key,protocol=PROTOCOL,implementation_sha256=sha,registered_at=datetime.now(timezone.utc).isoformat())
        if not row:memory.record_project_data('agent_pivot_context_protocol',key,registration)
        emit(dict(stage='supplementary_protocol_registered',protocol_id=key))
        _,rows=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history');candles=candles_from(rows)
        samples=source['eligible_samples'];targets={utc(s['signal_at']):s for s in samples}
        agg=intelligence_session().aggregator;previous=None;values={}
        for bar in candles:
            if previous and unexpected_broker_gap(previous,bar,300):agg.reset()
            histories=agg.add(bar);previous=bar;signal=bar.timestamp+timedelta(minutes=5)
            s=targets.get(signal)
            if not s:continue
            m5=list(histories['M5']);corr=m5[-4:-1]
            adverse=min(b.low for b in corr) if s['candidate']['side']=='long' else max(b.high for b in corr)
            values[s['sample_id']]=leg(m5,s['candidate']['side'],signal,corr[0].timestamp,300,adverse)
        if len(values)!=len(samples):raise ValueError('Incomplete pivot contexts')
        masks={
            'reference':samples,
            'fixed_window':[s for s in samples if passes(context['features'][s['sample_id']],'m5_impulse_shallow_correction')],
            'confirmed_pivot_leg':[s for s in samples if (v:=values[s['sample_id']]) is not None and v['amplitude_atr'] is not None and v['amplitude_atr']>=1 and 0<v['retracement']<=.5]}
        meta=source['source_manifest'];start,end=utc(meta['first_label_at']),utc(meta['as_of']);b1,b2=map(utc,meta['boundaries'])
        neutral={s['sample_id']:{} for s in samples};results={}
        for period,(a,b) in dict(all=(start,end),development=(start,b1),validation=(b1,b2),final_previously_seen=(b2,end)).items():
            results[period]={}
            for arm,selected in masks.items():
                emit(dict(stage='portfolio',period=period,arm=arm))
                results[period][arm]=replay(selected,candles,neutral,arm='reference',start=a,end=b,units=float(meta['lot'])*meta['contract']['contract_size'])
                results[period][arm]['arm']=arm
        for old,new in [('reference','reference'),('m5_impulse_shallow_correction','fixed_window')]:
            for k in ('closed_trades','wins','losses','net_pnl'):
                if results['all'][new][k]!=context['results']['all'][old][k]:raise ValueError('Control reproduction failure')
        report=dict(registration=registration,source_context_report=SOURCE,pivot_contexts=values,results=results,controls_reproduced=True,live_policy_changed=False,orders_sent=0)
        report['report_id']=fingerprint(report);memory.record_project_data('agent_pivot_context_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('pivot-context-'+report['report_id'][:12]+'.json');path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],results={p:{a:{k:v.get(k) for k in ('candidate_signals','closed_trades','wins','losses','win_rate_pct','net_pnl','expectancy_usd','account_locked','unresolved_position')} for a,v in arms.items()} for p,arms in results.items()}))
    finally:memory.close()


if __name__=='__main__':main()
