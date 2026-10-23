"""Describe pre-entry context of frozen H1 trades; never tune or place orders."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
SOURCE = '50f2555e7fd9bef884744624196004bb0517992cdef16ad9d1853064a09288ff'


def alignment(bias,side):
    if bias not in (-1,0,1):
        raise ValueError('Invalid frozen bias')
    if side not in ('long','short'):
        raise ValueError('Invalid side')
    return 'neutral' if not bias else 'aligned' if bias == (1 if side=='long' else -1) else 'opposed'


def context(sample):
    from aurelia_fx.historical.core import utc
    snapshot = sample['snapshot']
    observed = snapshot['research_context']
    if utc(observed['known_at']) != utc(sample['signal_at']):
        raise ValueError('Context not frozen at signal')
    side = sample['candidate']['side']
    sessions = frozenset(snapshot['session'])
    if not sessions or not sessions <= {'london','new_york'}:
        raise ValueError('Unexpected source session')
    event = utc(observed['event'])
    signal = utc(sample['signal_at'])
    if event >= signal:
        raise ValueError('Future breakout event')
    return dict(side=side,h1_alignment=alignment(observed['h1_bias'],side),
                d1_alignment=alignment(observed['macro_bias'],side),
                session='overlap' if len(sessions)==2 else next(iter(sessions)),
                breakout_age_hours=(signal-event).total_seconds()/3600)


def summarize(rows):
    pnl = [r['financial_result']['net_pnl'] for r in rows]
    gains,losses = sum(max(v,0) for v in pnl),-sum(min(v,0) for v in pnl)
    return dict(closed=len(rows),net=sum(pnl),wins=sum(v>0 for v in pnl),
                mean_net=sum(pnl)/len(pnl) if pnl else None,
                profit_factor=gains/losses if losses else None,
                gross=sum(r['financial_result']['gross_pnl'] for r in rows),
                costs=sum(sum(r['financial_result'][k] for k in ('spread_cost','slippage_cost','commission')) for r in rows),
                median_initial_risk=median(r['financial_result']['initial_risk'] for r in rows) if rows else None,
                median_breakout_age_hours=median(r['context']['breakout_age_hours'] for r in rows) if rows else None)


def group(rows,field):
    pools=defaultdict(list)
    for row in rows:
        label=row['reason'] if field=='exit_reason' else row['context'][field]
        pools[label].append(row)
    return {label:summarize(items) for label,items in sorted(pools.items())}


def availability(candles,signals):
    """Recover readiness from closed histories, never infer it from a zero bias."""
    from datetime import timedelta
    from aurelia_fx.agent_research import intelligence_session
    from aurelia_fx.broker_calendar import unexpected_broker_gap
    from aurelia_fx.historical.core import utc
    agg=intelligence_session().aggregator
    wanted={utc(s['signal_at']):s['sample_id'] for s in signals}
    counts={}
    previous=None
    for bar in candles:
        if previous and unexpected_broker_gap(previous,bar,300):
            agg.reset()
        histories=agg.add(bar)
        previous=bar
        sid=wanted.get(bar.timestamp+timedelta(minutes=5))
        if sid:
            counts[sid]={tf:len(histories[tf]) for tf in ('H1','H4','D1')}
    if len(counts)!=len(signals):
        raise ValueError('Signal missing from frozen availability replay')
    return counts


def attach_readiness(rows,counts):
    for row in rows:
        count=counts[row['decision_id']]
        for tf,label in [('H1','h1'),('D1','d1')]:
            row['context'][label+'_state']=('insufficient_history' if count[tf]<60
                else row['context'][label+'_alignment'])
        row['context']['closed_context_bars']=count
    return rows


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.historical.core import utc
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.regime_study import candles_from
    memory=open_memory()
    def read(kind,key):
        with memory.pool.connection() as connection:
            row=connection.execute('SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s AND record_key=%s ORDER BY recorded_at LIMIT 1',(kind,key)).fetchone()
        if row is None:
            raise ValueError('Frozen source missing')
        value=json.loads(row['payload_json'])
        if memory._encode(value)[1]!=row['payload_sha256']:
            raise ValueError('Source integrity mismatch')
        return value
    try:
        source=read('agent_h1_extended_experiment',SOURCE)
        # Register the grouping plan before reading per-trade context/outcomes.
        protocol=dict(version='h1-context-description-v2',source=SOURCE,
            registered_at=datetime.now(timezone.utc).isoformat(),
            fields=['side','h1_alignment','d1_alignment','h1_state','d1_state','session','exit_reason'],
            readiness='Post-initial-review ambiguity: replay exact frozen aggregation to distinguish <60 closed bars from neutral bias; no trading rule change',
            interpretation='Post-result exploratory grouping, not causal explanation, strategy backtest or independent validation',
            subsets='2021..2024 complete annual portfolios primary;2025 partial separate;2026 selected discovery separate',
            safeguards='All closed trades joined exactly once; context available at signal; no parameter search, entry filters, promotion or orders',
            code_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        protocol['protocol_id']=fingerprint(protocol)
        memory.record_project_data('agent_h1_context_protocol',protocol['protocol_id'],protocol)
        rows_by_year={}
        fields=protocol['fields']
        for year in range(2021,2026):
            key=str(year)
            signals=read('agent_h1_extended_signals',source['protocol']['protocol_id']+':'+key)['signals']
            by_id={s['sample_id']:s for s in signals}
            if len(by_id)!=len(signals):
                raise ValueError('Duplicate signal IDs')
            trades=source['results'][key]['trades']
            joined=[dict(**t,context=context(by_id[t['decision_id']])) for t in trades]
            _,archived=HistoricalRepository(memory).frozen_candles(source['baselines'][key],record_type='agent_h1_extended_history')
            joined=attach_readiness(joined,availability(candles_from(archived),signals))
            print(json.dumps(dict(stage='context_readiness',year=year,trades=len(joined))),flush=True)
            if len(joined)!=source['results'][key]['closed_trades']:
                raise ValueError('Closed trade count mismatch')
            known=source['results'][key]['known_realized_balance']-source['results'][key]['initial_balance']
            if abs(sum(t['financial_result']['net_pnl'] for t in joined)-known)>1e-7:
                raise ValueError('Financial reconciliation failed')
            rows_by_year[key]=joined
        primary=[r for y,rs in rows_by_year.items() if y!='2025' for r in rs]
        periods={year:dict(complete_portfolio=year!='2025',summary=summarize(rs),groups={f:group(rs,f) for f in fields}) for year,rs in rows_by_year.items()}
        # Separate selected discovery period from historical corroboration.
        old=read('agent_timeframe_session_experiment','2f6f3f7dc7391f62d9422a56885c7543392917ff40b448947c3c825c3f6f1d9c')
        original=read('agent_timeframe_experiment',old['protocol']['source'])
        signals=read('agent_timeframe_signals',original['protocol']['protocol_id'])['samples']['H1:breakout_retest']
        by_id={s['sample_id']:s for s in signals}
        selected=[dict(**t,context=context(by_id[t['decision_id']])) for t in old['results']['all']['H1:breakout_retest']['trades']]
        _,archived=HistoricalRepository(memory).frozen_candles(old['baseline'],record_type='agent_year_history')
        selected=attach_readiness(selected,availability(candles_from(archived),signals))
        periods['2026_selected_discovery']=dict(complete_portfolio=True,independent_validation=False,summary=summarize(selected),groups={f:group(selected,f) for f in fields})
        report=dict(protocol=protocol,periods=periods,
            complete_2021_2024=dict(summary=summarize(primary),groups={f:group(primary,f) for f in fields}),
            caveats=['Multiple overlapping post-result comparisons; do not select the most profitable cell as a validated policy',
                     'Exit reason is an outcome diagnostic, not an entry feature',
                     'No new filtered portfolio was simulated; removing closed trades would ignore overlap/risk/exposure changes',
                     '2025 partial outcomes cannot be compared as full annual results'],
            completed_at=datetime.now(timezone.utc).isoformat(),orders_sent=0,live_policy_changed=False)
        report['report_id']=fingerprint(report)
        memory.record_project_data('agent_h1_context_review',report['report_id'],report)
        path=ROOT/'data/reports'/('h1-context-'+report['report_id'][:12]+'.json')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(report_id=report['report_id'],primary=report['complete_2021_2024']),ensure_ascii=True),flush=True)
    finally:
        memory.close()


if __name__=='__main__':main()
