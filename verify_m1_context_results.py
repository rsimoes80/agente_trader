"""Audit all M1 profiles/cost scenarios against sealed signals and source hashes."""
from datetime import timedelta
import hashlib
import json
import math
from statistics import median

from run_m1_context_experiment import ROOT, PROFILES, read


def audit(memory, report, *, native=False):
    from aurelia_fx.historical.core import utc
    from aurelia_fx.trend import timeframe_seconds
    from run_h1_extended_validation import qualified
    protocol = report['protocol']; key = protocol['protocol_id']
    for path, expected in protocol['code_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != expected:
            raise ValueError('Source implementation changed: '+path)
    kind = 'agent_m1_native_signals' if native else 'agent_m1_context_signals'
    pools = read(memory, kind, key)['samples']
    signals_checked = portfolios_checked = trades_checked = 0
    summary = {}
    for arm, samples in pools.items():
        profile = arm.split(':')[0]
        context, confirm, execution = PROFILES[profile]
        for sample in samples:
            signal = utc(sample['signal_at']); c = sample['candidate']
            item = sample['snapshot']['research_context']
            if not (signal == utc(sample['entry_at']) == utc(item['known_at'])):
                raise ValueError('Signal time mismatch')
            if item['context_bias'] != item['confirmation_bias'] or item['context_bias'] not in (-1,1):
                raise ValueError('Conflicting entry direction')
            if (c['side']=='long') != (item['context_bias']==1):
                raise ValueError('Counter-context entry')
            for tf, field in ((context,'context_last'),(confirm,'confirmation_last')):
                if utc(item[field])+timedelta(seconds=timeframe_seconds(tf)) > signal:
                    raise ValueError('Future context')
            if utc(c['expires_at']) != signal+timedelta(seconds=timeframe_seconds(execution)):
                raise ValueError('Incorrect candidate expiry')
            signals_checked += 1
    for period, arms in report['results'].items():
        summary[period] = {}
        for arm, scenarios in arms.items():
            by_id = {s['sample_id']:s for s in pools[arm]}
            for scenario, result in scenarios.items():
                portfolios_checked += 1
                trades = result['trades']
                if len(trades) != result['closed_trades']:
                    raise ValueError('Trade count mismatch')
                if len({t['decision_id'] for t in trades}) != len(trades):
                    raise ValueError('Repeated closed decision')
                total = 0.
                for trade in trades:
                    sample = by_id[trade['decision_id']]
                    if trade['entry_at'] != sample['entry_at'] or trade['side'] != sample['candidate']['side']:
                        raise ValueError('Fill not linked to original signal')
                    duration = (utc(trade['observed_at'])-utc(trade['entry_at'])).total_seconds()
                    if not 60 <= duration <= 3600 or duration % 60:
                        raise ValueError('Not an intraday M1 duration')
                    f = trade['financial_result']
                    net = f['gross_pnl']-f['spread_cost']-f['slippage_cost']-f['commission']
                    if not math.isclose(net, f['net_pnl'], abs_tol=1e-8):
                        raise ValueError('Cost reconciliation failure')
                    fee = 0. if scenario.startswith('zero_fee') else .07
                    if not math.isclose(f['commission'], fee, abs_tol=1e-9):
                        raise ValueError('Commission profile mismatch')
                    total += f['net_pnl']; trades_checked += 1
                expected = result['known_realized_balance']-result['initial_balance']
                if not math.isclose(total,expected,abs_tol=1e-6):
                    raise ValueError('Balance reconciliation failure')
                if result['account_locked'] and result['net_pnl'] is not None:
                    raise ValueError('Unknown exposure reported as known total')
                if result['net_pnl'] is not None and not math.isclose(total,result['net_pnl'],abs_tol=1e-6):
                    raise ValueError('Net PnL mismatch')
            normal = scenarios['normal']
            summary[period][arm] = {k:normal[k] for k in ('signals','closed_trades','wins','losses',
                'net_pnl','gross_pnl_closed','spread_cost_closed','slippage_cost_closed','commission_closed',
                'expectancy_usd','profit_factor','win_rate_pct','max_close_equity_drawdown_pct',
                'censored_trades','unresolved_position','risk_reasons')}
            summary[period][arm].update(stress_net=scenarios['stress']['net_pnl'],
                stress_closed=scenarios['stress']['closed_trades'],
                stress_censored=scenarios['stress']['censored_trades'],
                zero_fee_net=scenarios['zero_fee_normal']['net_pnl'],
                zero_fee_stress_net=scenarios['zero_fee_stress']['net_pnl'])
            closed=normal['trades']
            costs=normal['spread_cost_closed']+normal['slippage_cost_closed']+normal['commission_closed']
            summary[period][arm].update(
                average_cost_pips=costs/len(closed)/.1 if closed else None,
                median_duration_minutes=median((utc(t['observed_at'])-utc(t['entry_at'])).total_seconds()/60 for t in closed) if closed else None,
                gross_expectancy_pips=normal['gross_pnl_closed']/len(closed)/.1 if closed else None,
                closed_expectancy_pips=sum(t['financial_result']['net_pnl'] for t in closed)/len(closed)/.1 if closed else None)
    eligible = [(a,r) for a,r in report['results']['development'].items()
                if not a.split(':')[0].endswith('_control') and qualified(r['normal'],r['stress'],50)]
    selected = max(eligible,key=lambda item:(item[1]['normal']['expectancy_usd'],item[0]))[0] if eligible else None
    if selected != report['selected']:
        raise ValueError('Development selection mismatch')
    checks = {p:bool(selected and qualified(report['results'][p][selected]['normal'],report['results'][p][selected]['stress'],20))
              for p in ('check','final')}
    if checks != report['checks'] or report['historical_checks_passed'] != bool(selected and all(checks.values())):
        raise ValueError('Validation gate mismatch')
    if report['orders_sent'] != 0 or report['live_policy_changed']:
        raise ValueError('Research unexpectedly affected live policy')
    return dict(report_id=report['report_id'],protocol_id=key,native=native,
        implementation_files_checked=len(protocol['code_hashes']), signals_checked=signals_checked,
        portfolios_checked=portfolios_checked,paired_closed_results_checked=trades_checked,
        selected=selected,checks=checks,summary=summary,orders_sent=0,
        paired_results_are_independent_samples=False)


def main():
    import argparse
    from aurelia_fx.storage import open_memory
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report_id')
    parser.add_argument('--native',action='store_true')
    args=parser.parse_args();m=open_memory()
    try:
        kind='agent_m1_native_experiment' if args.native else 'agent_m1_context_experiment'
        report=read(m,kind,args.report_id)
        verified=audit(m,report,native=args.native)
        earlier_id='50f2555e7fd9bef884744624196004bb0517992cdef16ad9d1853064a09288ff'
        earlier=read(m,'agent_h1_extended_experiment',earlier_id)
        dependency='run_h1_extended_validation.py'
        expected=earlier['protocol']['code_hashes'][dependency]
        if hashlib.sha256((ROOT/dependency).read_bytes()).hexdigest()!=expected:
            raise ValueError('Selection/uncertainty dependency changed since earlier sealed study')
        verified['supplementary_dependency']=dict(path=dependency,sha256=expected,earlier_sealed_report=earlier_id)
        m.record_project_data('agent_m1_context_verification',args.report_id,verified)
        path=ROOT/'data/reports'/('m1-verified-'+args.report_id[:12]+'.json')
        path.write_text(json.dumps(verified,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in verified.items() if k!='summary'}))
    finally:m.close()


if __name__=='__main__':main()
