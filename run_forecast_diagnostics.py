"""Audit existing immutable Timestral caches against frozen MT5 candles."""
from collections import defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.core import utc
    from aurelia_fx.regime_study import candles_from
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx import forecast_diagnostics as audit
    memory=open_memory()
    try:
        with memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_history' AND record_key=%s ORDER BY recorded_at LIMIT 1",('8d411834725ee19d83dbe9edeee6f6ea8a5d812686f6923265086d72186af9ca',)).fetchone()
            baseline=json.loads(row['payload_json'])
            if memory._encode(baseline)[1]!=row['payload_sha256']:raise ValueError('Invalid frozen source')
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_dataset' AND record_key=%s ORDER BY recorded_at LIMIT 1",('661f1b42-0b1d-4066-a145-85f8cd0334ae',)).fetchone()
            dataset=json.loads(row['payload_json'])
            if memory._encode(dataset)[1]!=row['payload_sha256']:raise ValueError('Invalid dataset manifest')
            if dataset['manifest']['baseline_id']!=baseline['baseline_id']:raise ValueError('Dataset source mismatch')
            cutoff=c.execute("SELECT MAX(recorded_at) t FROM project_records WHERE record_type='agent_forecast_cache'").fetchone()['t']
            records=c.execute("SELECT DISTINCT ON(record_key) record_key,payload_json,payload_sha256 FROM project_records WHERE record_type='agent_forecast_cache' AND recorded_at<=%s ORDER BY record_key,recorded_at",(cutoff,)).fetchall()
        caches=[];hashes=[]
        for r in records:
            cache=json.loads(r['payload_json'])
            if memory._encode(cache)[1]!=r['payload_sha256']:raise ValueError('Cache integrity failure')
            caches.append(cache);hashes.append((r['record_key'],r['payload_sha256']))
        del records
        protocol=dict(spec=audit.SPEC,cache_cutoff=cutoff.isoformat(),cache_manifest_sha=fingerprint(hashes),
            baseline=baseline['baseline_id'],price_sha=baseline['timeframes']['M5']['dataset_sha256'],
            first_label_at=dataset['manifest']['first_label_at'],split='2026-07-01T00:00:00+00:00',
            registered_at=datetime.now(timezone.utc).isoformat(),
            source_hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
                ['src/aurelia_fx/forecast_diagnostics.py','run_forecast_diagnostics.py']},
            warning='Irregular cached forecasts, previously researched data; not new OOS or portfolio proof',
            activation=False,orders_sent=0)
        protocol['id']=fingerprint(protocol)
        memory.record_project_data('agent_forecast_information_protocol',protocol['id'],protocol)
        print(json.dumps(dict(stage='registered',id=protocol['id'],caches=len(caches))),flush=True)
        _,source=HistoricalRepository(memory).frozen_candles(baseline,record_type='agent_training_history')
        candles=candles_from(source);del source
        cases,excluded=audit.cases(candles,caches);del caches
        groups=defaultdict(list)
        for row in cases:
            if utc(row['known_at'])<utc(protocol['first_label_at']):continue
            phase='development' if utc(row['known_at'])<utc(protocol['split']) else 'check'
            # Do not let discovery labels cross into the comparison period.
            if phase=='development' and utc(row['target_closed_at'])>=utc(protocol['split']):continue
            prefix=f"{phase}|{row['model_key']}|{row['configuration']}|{row['horizon']}"
            groups[prefix+'|all'].append(row)
            if row['hourly_reference']:groups[prefix+'|hourly'].append(row)
        result=dict(protocol=protocol,counts=excluded,cases_sha=fingerprint(cases),metrics={})
        for key,rows in sorted(groups.items()):
            result['metrics'][key]=audit.metrics(rows)
            print(json.dumps(dict(stage='metrics',group=key,**result['metrics'][key])),flush=True)
        result['id']=fingerprint(result)
        path=ROOT/'data/reports'/('forecast-information-'+result['id'][:12]+'.json')
        path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        memory.record_project_data('agent_forecast_information_audit',result['id'],result)
        print(json.dumps(dict(stage='complete',id=result['id'],counts=excluded)),flush=True)
    finally:memory.close()


if __name__=='__main__':main()
