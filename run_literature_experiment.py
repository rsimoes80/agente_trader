"""Preregister and compare book-motivated families on the same frozen MT5 year."""
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))
SOURCE = 'f898357a5ab80a9e9bf4d05eecda1f92754c3616239bd754c7d4b820f33086e1'


def simulate(samples, candles, *, start, end, stress=False, holding_bars=24, purge_hours=2):
    from aurelia_fx.agent_research import simulator, request_for, SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap, slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.historical.core import utc
    from aurelia_fx.domain import Candidate
    start, end = utc(start), utc(end)
    selected = [s for s in samples if start <= utc(s['entry_at']) < end-timedelta(hours=purge_hours)]
    signals = {utc(s['entry_at']): s for s in selected}
    if len(signals) != len(selected):
        raise ValueError('Duplicate signals in one family')
    engine = simulator(1000)
    engine.config = replace(engine.config, max_holding_bars=holding_bars, slippage_pips=.4 if stress else .2)
    sessions = SessionEngine(SESSIONS)
    previous = None
    overlaps = 0
    for original in candles:
        if not start <= original.timestamp < end:
            continue
        bar = replace(original, spread_pips=original.spread_pips*1.5) if stress and original.spread_pips is not None else original
        gap = previous is not None and unexpected_broker_gap(previous, bar, 300)
        active = sessions.identify(bar.timestamp).active_sessions
        sample = signals.get(bar.timestamp)
        if sample and not gap:
            if engine.busy:
                overlaps += 1
            elif not engine.account_locked:
                c = sample['candidate']
                candidate = Candidate(c['side'], c['entry'], c['stop'], c['target'], utc(c['expires_at']), tuple(c['evidence']))
                engine.submit(request_for(dict(candidate=candidate, snapshot=sample['snapshot'], signal_at=sample['signal_at']), sample['sample_id']))
        close = bar.timestamp+timedelta(minutes=5)
        # Calendar-only rule: no future prices required and no weekend swaps assumed away.
        ending = not slot_tradable(close) or not sessions.identify(close).active_sessions
        engine.advance(bar, data_valid=not gap, active_sessions=active, force_close_reason='KNOWN_SESSION_END' if ending else None)
        previous = bar
    result = engine.summary()
    trades = [e for e in engine.events if e['status'] == 'closed']
    pnls = [e['financial_result']['net_pnl'] for e in trades]
    gains, losses = sum(max(p,0) for p in pnls), -sum(min(p,0) for p in pnls)
    result.update(signals=len(selected), overlap_skips=overlaps,
        expectancy_usd=sum(pnls)/len(pnls) if pnls else None,
        win_rate_pct=100*result['wins']/len(trades) if trades else None,
        profit_factor=gains/losses if losses else None,
        unresolved_position=engine.busy,
        risk_reasons=dict(Counter(r for e in engine.events if e['status']=='rejected' for r in e.get('risk',{}).get('reasons',[]))),
        filled_sides=dict(Counter(e['side'] for e in trades)),
        trades=[{k:e[k] for k in ('decision_id','side','entry_at','observed_at','reason','financial_result')} for e in trades])
    return result


def choose(development):
    """Development-only selection; do not fall back to a negative 'best' strategy."""
    eligible = [(a,r) for a,r in development.items() if r['closed_trades'] >= 50
        and r['net_pnl'] is not None and r['net_pnl'] > 0
        and (r['profit_factor'] or 0) >= 1.1 and not r['unresolved_position']
        and not r['account_locked'] and not r['censored_trades']]
    return max(eligible, key=lambda item:(item[1]['expectancy_usd'],item[0]))[0] if eligible else None


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_research import intelligence_session, SESSIONS
    from aurelia_fx.broker_calendar import unexpected_broker_gap, slot_tradable
    from aurelia_fx.sessions import SessionEngine
    from aurelia_fx.literature_strategies import FAMILIES, PARAMETERS, setups
    from aurelia_fx.trigger_exit_experiment import replay
    from run_year_validation import windows
    memory = open_memory()
    emit = lambda d: print(json.dumps(d, ensure_ascii=True), flush=True)

    def read(kind, key):
        with memory.pool.connection() as c:
            row = c.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if row is None:
            raise ValueError('Frozen source missing')
        data = json.loads(row['payload_json'])
        if memory._encode(data)[1] != row['payload_sha256']:
            raise ValueError('Record integrity mismatch')
        return data

    try:
        import psutil
        try:
            psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if sys.platform=='win32' else 10)
        except (psutil.Error,AttributeError):
            pass
        source = read('agent_year_experiment', SOURCE)
        review = json.loads((ROOT/'data/knowledge/literature_families.json').read_text(encoding='utf-8'))
        files = sorted((ROOT/'src').rglob('*.py'))+[ROOT/'run_literature_experiment.py',ROOT/'run_year_validation.py']
        hashes = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        protocol = dict(version='literature-families-v1', source=SOURCE,
            source_baseline=source['baseline']['baseline_id'], code_hashes=hashes,
            source_review=review, families=list(FAMILIES), parameters=PARAMETERS,
            controls=['legacy_strict_original','legacy_correction_original','legacy_correction_common_geometry'],
            common='new families and common control: quote-aware 3R target except bounded range target, 24M5 max holding, calendar/session flatten, no H4/global regime/D1 veto',
            immutable_risk='lot.01, equity10000, maxspread2pips, max5/day, .5percent/trade,2percent/day,5percentdrawdown,minnetRR2,observedspread,.2pipslippage,USD35/million/sidecommission',
            stress='frozen same signals/targets; spread x1.5 and slippage .4pip; unchanged commission and risk',
            selection='Jan-Jun only; >=50 closed, positive net,PF>=1.1; rank expectancy; no eligible means none',
            check='Jul-Sep previously seen: >=20 closed,positive net,PF>=1.1,positive stress net; October descriptive only',
            interpretation='all 2026 largely seen by earlier research; this is exploratory, not independent out-of-sample proof',
            original_control='same original sealed entries and original 2.5R/12bar exits, no session flatten changes',
            live_policy_changed=False, automatic_promotion=False, orders_sent=0,
            registered_at=datetime.now(timezone.utc).isoformat())
        protocol['protocol_id'] = fingerprint(protocol)
        memory.record_project_data('agent_literature_protocol', protocol['protocol_id'], protocol)
        emit(dict(stage='protocol_registered_before_results',protocol_id=protocol['protocol_id']))
        _,rows = HistoricalRepository(memory).frozen_candles(source['baseline'],record_type='agent_year_history')
        candles = candles_from(rows)
        agg = intelligence_session().aggregator
        sessions = SessionEngine(SESSIONS)
        signals = {a:[] for a in FAMILIES}
        seen = set()
        previous = None
        for i,bar in enumerate(candles):
            if i%10000==0:
                emit(dict(stage='generating_closed_context',processed=i,total=len(candles)))
            if previous and unexpected_broker_gap(previous,bar,300):
                agg.reset()
            histories = agg.add(bar)
            previous = bar
            known = bar.timestamp+timedelta(minutes=5)
            active = sessions.identify(known).active_sessions
            if bar.timestamp < utc(source['baseline']['first_label_at']) or not active or not slot_tradable(known):
                continue
            for family,s in setups(histories).items():
                event = (family,s['event'],s['candidate'].side)
                if event in seen:
                    continue
                seen.add(event)
                c = s.pop('candidate')
                snapshot = dict(snapshot_id=family+':'+known.isoformat(), session=list(active),
                    regime='FAMILY_'+family.upper(), research_context=s)
                signals[family].append(dict(sample_id=family+':'+known.isoformat(),signal_at=known.isoformat(),entry_at=known.isoformat(),snapshot=snapshot,
                    candidate=dict(side=c.side,entry=c.entry,stop=c.stop,target=c.target,expires_at=c.expires_at.isoformat(),evidence=list(c.evidence))))
        emit(dict(stage='signals_sealed',counts={a:len(v) for a,v in signals.items()}))
        memory.record_project_data('agent_literature_signals',protocol['protocol_id'],dict(signals=signals))
        # Same old signal timestamps and stops, with the new common quote-aware target.
        by_time = {b.timestamp+timedelta(minutes=5):b for b in candles}
        control=[]
        for sample in source['eligible_samples']:
            s=json.loads(json.dumps(sample));c=s['candidate'];bar=by_time[utc(s['signal_at'])]
            sign=1 if c['side']=='long' else -1
            anticipated=c['entry']+(bar.spread_pips*.0001+.00002 if sign==1 else -.00002)
            c['target']=anticipated+sign*3*abs(anticipated-c['stop'])
            control.append(s)
        signals['legacy_correction_common_geometry']=control
        start,end=utc(source['baseline']['first_label_at']),utc(source['baseline']['as_of'])
        boundaries=dict(development=(start,datetime(2026,7,1,tzinfo=timezone.utc)),
            check_previously_seen=(datetime(2026,7,1,tzinfo=timezone.utc),datetime(2026,10,1,tzinfo=timezone.utc)))
        boundaries.update(windows(2026,end))
        results={};stress={};selected=None
        for period,(a,b) in boundaries.items():
            results[period]={}
            for arm,samples in signals.items():
                emit(dict(stage='portfolio',period=period,arm=arm))
                results[period][arm]=simulate(samples,candles,start=a,end=b)
            if period=='development':
                selected=choose({a:results[period][a] for a in FAMILIES})
                memory.record_project_data('agent_literature_selection',protocol['protocol_id'],dict(selected=selected,scope='development_only_before_check_results'))
                emit(dict(stage='development_selection_frozen',selected=selected))
            if period in ('all','check_previously_seen'):
                stress[period]={arm:simulate(signals[arm],candles,start=a,end=b,stress=True) for arm in FAMILIES}
        originals={}
        for arm,subset in [('legacy_strict_original',[s for s in source['eligible_samples'] if 'strict_current' in s['arms']]),('legacy_correction_original',source['eligible_samples'])]:
            originals[arm]=replay(subset,candles,{s['sample_id']:{} for s in subset},arm='reference',start=start,end=end,units=1000)
        for arm,old in [('legacy_strict_original','strict_current'),('legacy_correction_original','reference')]:
            if originals[arm]['trades']!=source['results']['all'][old]['trades']:
                raise ValueError('Original control failed exact reproduction')
        check=results['check_previously_seen'].get(selected) if selected else None
        stress_check=stress['check_previously_seen'].get(selected) if selected else None
        passed=bool(check and check['closed_trades']>=20 and check['net_pnl'] is not None and check['net_pnl']>0 and (check['profit_factor'] or 0)>=1.1
            and stress_check['net_pnl'] is not None and stress_check['net_pnl']>0 and not check['account_locked'] and not check['unresolved_position'] and not check['censored_trades'])
        report=dict(protocol=protocol,source_review=review,signals=signals,results=results,stress=stress,
            original_controls=originals,selected_on_development=selected,exploratory_check_passed=passed,
            independent_validation=False,live_policy_changed=False,orders_sent=0,completed_at=datetime.now(timezone.utc).isoformat())
        report['report_id']=fingerprint(report)
        memory.record_project_data('agent_literature_experiment',report['report_id'],report)
        path=ROOT/'data/reports'/('literature-'+report['report_id'][:12]+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        emit(dict(stage='complete',report_id=report['report_id'],selected=selected,exploratory_check_passed=passed,
            results={a:{k:v[k] for k in ('signals','closed_trades','wins','losses','net_pnl','expectancy_usd','profit_factor','filled_sides','censored_trades','unresolved_position')} for a,v in results['all'].items()}))
    finally:
        memory.close()


if __name__=='__main__':
    main()
