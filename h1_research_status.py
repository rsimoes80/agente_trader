"""Read the most recent H1 research and paper observation, without secrets."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))


def main():
    from aurelia_fx.storage import open_memory
    memory = open_memory()
    try:
        report = {}
        for kind in ('agent_h1_extended_experiment','agent_h1_shadow_cycle','agent_h1_shadow_protocol',
                     'agent_h1_hours_experiment','agent_h1_hours_shadow_cycle','agent_h1_family_experiment',
                     'agent_m15_family_experiment','agent_demo_fee_experiment','agent_m15_strategy_shadow_cycle'):
            with memory.pool.connection() as connection:
                row = connection.execute('SELECT record_key,payload_json,payload_sha256 FROM project_records WHERE record_type=%s ORDER BY recorded_at DESC LIMIT 1',(kind,)).fetchone()
            if not row:
                report[kind] = dict(status='awaiting_first_record')
                continue
            value = json.loads(row['payload_json'])
            if memory._encode(value)[1] != row['payload_sha256']:
                raise ValueError('Report integrity mismatch')
            if kind == 'agent_h1_extended_experiment':
                report[kind] = dict(report_id=value['report_id'],gates=value['gates'],data_ready=value['data_ready'],
                    results={k:{field:r[field] for field in ('closed_trades','net_pnl','profit_factor','censored_trades','unresolved_position')}
                             for k,r in value['results'].items()},uncertainty=value['uncertainty'],
                    uncertainty_scope='Only observed closed trades, NOT full portfolio when censored or locked',
                    historical_criteria_passed=value['historical_criteria_passed'])
            elif kind == 'agent_h1_shadow_cycle':
                report[kind] = {field:value[field] for field in ('protocol_id','as_of','recorded_at','bars','timely_signals','late_signals_not_traded','mode')}
                report[kind]['results'] = {field:value['results'][field] for field in ('closed_trades','net_pnl','censored_trades','unresolved_position')}
            elif kind == 'agent_h1_shadow_protocol':
                report[kind] = {field:value[field] for field in ('protocol_id','start','mode','orders_sent')}
            else:
                def summary(pair):
                    return dict(normal={field:pair['normal'][field] for field in ('closed_trades','net_pnl','profit_factor','censored_trades','account_locked')},
                                stress_net=pair['stress']['net_pnl'])
                report[kind] = dict(selected=value.get('selected_on_development',value.get('selected')),
                    checks=value.get('selected_check_passed',value.get('checks')),
                    report_id=value.get('report_id'),as_of=value.get('as_of'),mode=value.get('mode','historical_research'))
                if kind in ('agent_h1_hours_shadow_cycle','agent_m15_strategy_shadow_cycle'):
                    report[kind]['results']={arm:summary(pair) for arm,pair in value['results'].items()}
                    if kind=='agent_m15_strategy_shadow_cycle':
                        from run_h1_extended_validation import qualified
                        for arm,pair in value['results'].items():
                            report[kind]['results'][arm]['conservative_net']=pair['conservative_normal']['net_pnl']
                            report[kind]['results'][arm]['forward_minimum_passed']=qualified(pair['normal'],pair['stress'],50)
                            report[kind]['results'][arm]['conservative_profile_passed']=qualified(pair['conservative_normal'],pair['conservative_stress'],50)
                        report[kind]['historically_validated']=False
                        report[kind]['automatic_promotion']=False
                else:
                    report[kind]['results']={period:{arm:summary(pair) for arm,pair in arms.items()} for period,arms in value['results'].items()}
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        memory.close()


if __name__ == '__main__':
    main()
