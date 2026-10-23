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
        for kind in ('agent_h1_extended_experiment','agent_h1_shadow_cycle','agent_h1_shadow_protocol'):
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
            else:
                report[kind] = {field:value[field] for field in ('protocol_id','start','mode','orders_sent')}
        print(json.dumps(report,ensure_ascii=False,indent=2))
    finally:
        memory.close()


if __name__ == '__main__':
    main()
