"""Immutable all-candle dataset, chronological labels and bounded-memory export."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path

from ..agent_model import fingerprint
from ..historical.core import closed_rows,utc
from ..historical.repository import HistoricalRepository

SOURCE_RUN='661f1b42-0b1d-4066-a145-85f8cd0334ae'
CONTEXT=256
HORIZON=12
STRIDE=12

def validate_dataset(folder):
    """Recompute partitions as well as hashing prices; modified labels cannot leak."""
    import numpy as np
    from .proof import file_hash
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    identity={k:v for k,v in manifest.items() if k not in {'dataset_id','array_sha256'}}
    if fingerprint(identity)!=manifest['dataset_id']:raise ValueError('Dataset manifest changed')
    if file_hash(folder/'candles.npy')!=manifest['array_sha256']:raise ValueError('Dataset prices changed')
    data=np.load(folder/'candles.npy',mmap_mode='r',allow_pickle=False)
    expected,boundaries,excluded=split_windows(data[:,0],first_label=manifest['first_label_at'],end=manifest['source_as_of'])
    for phase,indices in expected.items():
        if not np.array_equal(indices,np.load(folder/(phase+'.npy'),allow_pickle=False)):raise ValueError('Dataset target partition changed')
    if manifest['counts']!={k:len(v) for k,v in expected.items()}:raise ValueError('Dataset counts changed')
    return manifest,data


def split_windows(stamps,*,first_label,end,context=CONTEXT,horizon=HORIZON,stride=STRIDE):
    import numpy as np
    stamps=np.asarray(stamps,dtype=np.int64)
    if len(stamps)<context+horizon or (np.diff(stamps)<=0).any():raise ValueError('Insufficient or unordered data')
    first,end=int(utc(first_label).timestamp()),int(utc(end).timestamp())
    boundaries=[first+int((end-first)*f) for f in (.70,.85)]
    gaps=np.r_[0,np.cumsum(np.diff(stamps)!=300)]
    result={k:[] for k in ('train','validation','test')};excluded={'gap':0,'cross_boundary':0,'outside':0}
    for i in range(context,len(stamps)-horizon+1,stride):
        if stamps[i]<first or stamps[i+horizon-1]+300>end:
            excluded['outside']+=1;continue
        if gaps[i+horizon-1]!=gaps[i-context]:
            excluded['gap']+=1;continue
        phase='train' if stamps[i]<boundaries[0] else 'validation' if stamps[i]<boundaries[1] else 'test'
        upper=boundaries[0] if phase=='train' else boundaries[1] if phase=='validation' else end
        if stamps[i+horizon-1]+300>=upper:
            excluded['cross_boundary']+=1;continue
        result[phase].append(i)
    return {k:np.asarray(v,dtype=np.int64) for k,v in result.items()},boundaries,excluded


def export(memory,root,progress=lambda **kw:None):
    import numpy as np
    def decode(row):
        d=json.loads(row['payload_json'])
        if memory._encode(d)[1]!=row['payload_sha256']:raise ValueError('Archive record integrity failure')
        return d
    with memory.pool.connection() as c:
        source=decode(c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_dataset' AND record_key=%s LIMIT 1",(SOURCE_RUN,)).fetchone())
        baseline=decode(c.execute("SELECT payload_json,payload_sha256,recorded_at FROM project_records WHERE record_type='agent_training_history' AND record_key=%s ORDER BY recorded_at LIMIT 1",(source['manifest']['baseline_id'],)).fetchone())
        known=c.execute("SELECT recorded_at FROM project_records WHERE record_type='agent_training_history' AND record_key=%s ORDER BY recorded_at LIMIT 1",(baseline['baseline_id'],)).fetchone()['recorded_at']
        reserved=c.execute("SELECT MIN((payload_json::jsonb->>'registered_at')::timestamptz) AS start FROM project_records WHERE record_type='agent_regime_study_protocol'").fetchone()['start']
    if reserved and utc(baseline['as_of'])>=reserved:raise ValueError('Source overlaps reserved regime study')
    prefix=HistoricalRepository.prefix(baseline['clock_id'],'M5');digest=hashlib.sha256();digest.update(b'[')
    values=[];previous=None;count=0
    with memory.pool.connection() as c,c.transaction(),c.cursor(name='training_candle_export') as cursor:
        cursor.execute("""SELECT DISTINCT ON(record_key) payload_json,payload_sha256 FROM project_records
            WHERE record_type='closed_candle' AND record_key>=%s AND record_key<=%s
            AND recorded_at<=%s ORDER BY record_key,recorded_at DESC,payload_sha256 DESC""",
            (prefix+baseline['start'],prefix+baseline['as_of'],known))
        for record in cursor:
            raw=decode(record);normalized=closed_rows([raw],'M5',start=baseline['start'],as_of=baseline['as_of'])
            if not normalized:continue
            row=normalized[0];stamp=int(utc(row['timestamp']).timestamp())
            if previous is not None and stamp<=previous:raise ValueError('Archive order changed')
            previous=stamp
            if count:digest.update(b', ')
            digest.update(json.dumps(row,sort_keys=True,allow_nan=False).encode())
            values.append([stamp,*[row[k] for k in ('open','high','low','close','volume')],row.get('spread_pips') if row.get('spread_pips') is not None else float('nan')])
            count+=1
            if count%5000==0:progress(stage='dataset',message='Exportando candles verificados',candles=count)
    digest.update(b']')
    if digest.hexdigest()!=baseline['timeframes']['M5']['dataset_sha256']:raise ValueError('Frozen candle hash mismatch')
    array=np.asarray(values,dtype=np.float64);del values
    splits,bounds,excluded=split_windows(array[:,0],first_label=source['manifest']['first_label_at'],end=baseline['as_of'])
    if any(len(v)<200 for v in splits.values()):raise ValueError('Insufficient chronological windows')
    manifest=dict(version='eurusd-training-v1',source_run=SOURCE_RUN,baseline_id=baseline['baseline_id'],
        source_clock_id=baseline['clock_id'],known_by=known.isoformat(),source_candles_sha256=digest.hexdigest(),
        source_as_of=baseline['as_of'],source_start=baseline['start'],first_label_at=source['manifest']['first_label_at'],
        boundaries=[datetime.fromtimestamp(t,timezone.utc).isoformat() for t in bounds],
        context=CONTEXT,horizon=HORIZON,stride=STRIDE,candles=len(array),counts={k:len(v) for k,v in splits.items()},excluded=excluded,
        reserved_regime_study_from=reserved.isoformat() if reserved else None,prior_market_data_seen=True,
        split='70/15/15 chronological; context may include past partition, targets never cross boundaries',
        columns=['timestamp','open','high','low','close','volume','spread_pips'],lot=source['manifest']['lot'],contract=source['manifest']['contract'])
    manifest['dataset_id']=fingerprint(manifest)
    folder=Path(root)/'data/training/datasets'/manifest['dataset_id'];folder.mkdir(parents=True,exist_ok=True)
    np.save(folder/'candles.npy',array,allow_pickle=False)
    for name,indices in splits.items():np.save(folder/(name+'.npy'),indices,allow_pickle=False)
    manifest['array_sha256']=hashlib.sha256((folder/'candles.npy').read_bytes()).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    memory.record_project_data('agent_timestral_training_dataset',manifest['dataset_id'],manifest)
    return folder,manifest
