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
    from .scope import identity
    identity(manifest)
    identity={k:v for k,v in manifest.items() if k not in {'dataset_id','array_sha256'}}
    if fingerprint(identity)!=manifest['dataset_id']:raise ValueError('Dataset manifest changed')
    if file_hash(folder/'candles.npy')!=manifest['array_sha256']:raise ValueError('Dataset prices changed')
    data=np.load(folder/'candles.npy',mmap_mode='r',allow_pickle=False)
    from .scope import profile_for
    profile=profile_for(manifest)
    calendar=profile.calendar if profile and manifest.get('context_policy')=='calendar-closed-slots-v1' else None
    expected,boundaries,excluded=split_windows(data[:,0],first_label=manifest['first_label_at'],end=manifest['source_as_of'],reserved=manifest.get('reserved_intervals',()),calendar=calendar)
    for phase,indices in expected.items():
        if not np.array_equal(indices,np.load(folder/(phase+'.npy'),allow_pickle=False)):raise ValueError('Dataset target partition changed')
    if manifest['counts']!={k:len(v) for k,v in expected.items()}:raise ValueError('Dataset counts changed')
    return manifest,data


def split_windows(stamps,*,first_label,end,context=CONTEXT,horizon=HORIZON,stride=STRIDE,reserved=(),calendar=None):
    import numpy as np
    stamps=np.asarray(stamps,dtype=np.int64)
    if len(stamps)<context+horizon or (np.diff(stamps)<=0).any():raise ValueError('Insufficient or unordered data')
    first,end=int(utc(first_label).timestamp()),int(utc(end).timestamp())
    boundaries=[first+int((end-first)*f) for f in (.70,.85)]
    gaps=np.r_[0,np.cumsum(np.diff(stamps)!=300)]
    context_gaps=gaps
    if calendar:
        from types import SimpleNamespace
        bad=np.diff(stamps)!=300
        for index in np.flatnonzero(bad):
            prior=SimpleNamespace(timestamp=datetime.fromtimestamp(int(stamps[index]),timezone.utc))
            current=SimpleNamespace(timestamp=datetime.fromtimestamp(int(stamps[index+1]),timezone.utc))
            bad[index]=calendar.unexpected_gap(prior,current,300)
        context_gaps=np.r_[0,np.cumsum(bad)]
    result={k:[] for k in ('train','validation','test')};excluded={'gap':0,'cross_boundary':0,'outside':0}
    for i in range(context,len(stamps)-horizon+1,stride):
        if any(stamps[i-context]<utc(b).timestamp() and stamps[i+horizon-1]+300>utc(a).timestamp() for a,b in reserved):
            excluded['reserved']=excluded.get('reserved',0)+1;continue
        if stamps[i]<first or stamps[i+horizon-1]+300>end:
            excluded['outside']+=1;continue
        if context_gaps[i-1]!=context_gaps[i-context] or gaps[i+horizon-1]!=gaps[i-1]:
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


def export_asset(memory,root,profile,fetch,progress=lambda **kw:None,check=lambda:None):
    """Freeze up to one year of native M5; never replace the operational baseline."""
    import numpy as np
    from aurelia_fx.source_clock import validate_source_clock
    from .scope import identity
    now=datetime.now(timezone.utc);start=now-timedelta(days=365)
    archive=HistoricalRepository(memory,profile.symbol,profile=profile)
    progress(stage='dataset',message='Capturando até 365 dias M5 de '+profile.symbol+' para treino separado.')
    check();payload=fetch(profile.symbol,'M5',100_000,include_current=False)
    clock=validate_source_clock(payload,datetime.now(timezone.utc))
    if payload.get('symbol')!=profile.symbol or payload.get('timeframe')!='M5' or payload.get('pip_size')!=profile.price_unit:
        raise ValueError('TRAINING_HISTORY_INSTRUMENT_MISMATCH')
    rows=closed_rows(payload['candles'],'M5',start=start,as_of=now)
    if any(r.get('symbol',profile.symbol)!=profile.symbol for r in rows):raise ValueError('TRAINING_CANDLE_INSTRUMENT_MISMATCH')
    for offset in range(0,len(rows),1000):
        check();archive.ingest(rows[offset:offset+1000],clock=clock,timeframe='M5')
        progress(stage='dataset',message='Histórico próprio salvo no PostgreSQL.',completed=min(offset+1000,len(rows)),total=len(rows))
    known=datetime.now(timezone.utc)
    rows=closed_rows(archive.candles(clock_id=clock['clock_id'],timeframe='M5',start=start,as_of=now,known_by=known),'M5',start=start,as_of=now)
    if not rows:raise ValueError('TRAINING_HISTORY_EMPTY')
    first=utc(rows[0]['timestamp'])+timedelta(days=10)
    array=np.asarray([[utc(r['timestamp']).timestamp(),*[r[k] for k in ('open','high','low','close','volume')],r.get('spread_pips') if r.get('spread_pips') is not None else float('nan')] for r in rows],dtype=np.float64)
    splits,bounds,excluded=split_windows(array[:,0],first_label=first,end=now,calendar=profile.calendar)
    if any(len(v)<200 for v in splits.values()):raise ValueError('ASSET_TRAINING_WINDOWS_INSUFFICIENT')
    manifest=dict(version='instrument-rolling-v1',symbol=profile.symbol,profile_id=profile.fingerprint,
        research_profile=profile.as_dict(),price_unit=profile.price_unit,source_run='automatic-per-asset',
        context_policy='calendar-closed-slots-v1',target_policy='12 wall-clock M5 closes; no gaps or calendar breaks in targets',
        source_clock_id=clock['clock_id'],known_by=known.isoformat(),source_as_of=now.isoformat(),
        source_start=utc(rows[0]['timestamp']).isoformat(),first_label_at=first.isoformat(),
        boundaries=[datetime.fromtimestamp(t,timezone.utc).isoformat() for t in bounds],
        source_candles_sha256=fingerprint(rows),context=CONTEXT,horizon=HORIZON,stride=STRIDE,
        candles=len(array),counts={k:len(v) for k,v in splits.items()},excluded=excluded,reserved_intervals=[],
        prior_market_data_seen=True,split='70/15/15 chronological; gaps excluded; independent prospective evidence required',
        columns=['timestamp','open','high','low','close','volume','spread_pips'],lot=.01,contract=profile.contract.as_dict())
    identity(manifest);manifest['dataset_id']=fingerprint(manifest)
    folder=Path(root)/'data/training/datasets'/manifest['dataset_id'];folder.mkdir(parents=True,exist_ok=True)
    np.save(folder/'candles.npy',array,allow_pickle=False)
    for name,indices in splits.items():np.save(folder/(name+'.npy'),indices,allow_pickle=False)
    manifest['array_sha256']=hashlib.sha256((folder/'candles.npy').read_bytes()).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    memory.record_project_data(profile.record_type('agent_timestral_training_dataset'),manifest['dataset_id'],manifest)
    return folder,manifest

def export_rolling(memory,root,progress=lambda **kw:None):
    """New immutable snapshot per automatic run; previously researched data explicit."""
    import numpy as np
    baseline=HistoricalRepository(memory).latest()
    if not baseline:raise ValueError('HISTORY_BASELINE_REQUIRED')
    end=utc(baseline['as_of']);start=end-timedelta(days=180);known=baseline['_recorded_at']
    rows=HistoricalRepository(memory).candles(clock_id=baseline['clock_id'],timeframe='M5',start=start,as_of=end,known_by=known)
    rows=closed_rows(rows,'M5',start=start,as_of=end)
    if not rows:raise ValueError('HISTORY_EMPTY')
    start=max(start,utc(rows[0]['timestamp']));first=start+timedelta(days=10)
    with memory.pool.connection() as c:
        protocols=c.execute("SELECT payload_json FROM project_records WHERE record_type='agent_regime_study_protocol'").fetchall()
    intervals=[]
    for p in protocols:
        at=utc(json.loads(p['payload_json'])['registered_at'])
        intervals.append((at.isoformat(),(at+timedelta(days=7)).isoformat()))
    array=np.asarray([[utc(r['timestamp']).timestamp(),*[r[k] for k in ('open','high','low','close','volume')],r.get('spread_pips') if r.get('spread_pips') is not None else float('nan')] for r in rows],dtype=np.float64)
    splits,bounds,excluded=split_windows(array[:,0],first_label=first,end=end,reserved=intervals)
    if any(len(v)<200 for v in splits.values()):raise ValueError('ROLLING_WINDOWS_INSUFFICIENT')
    manifest=dict(version='eurusd-rolling-v1',source_run='automatic',baseline_id=baseline['baseline_id'],
        source_clock_id=baseline['clock_id'],known_by=known,source_as_of=end.isoformat(),source_start=start.isoformat(),
        first_label_at=first.isoformat(),boundaries=[datetime.fromtimestamp(t,timezone.utc).isoformat() for t in bounds],
        source_candles_sha256=hashlib.sha256(json.dumps(rows,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        context=CONTEXT,horizon=HORIZON,stride=STRIDE,candles=len(array),counts={k:len(v) for k,v in splits.items()},excluded=excluded,
        reserved_intervals=intervals,prior_market_data_seen=True,
        split='70/15/15 chronological; all reserved study windows excluded; prospective validation required',
        columns=['timestamp','open','high','low','close','volume','spread_pips'],lot=.01,contract=dict(trade_contract_size=100000,currency_profit='USD'))
    manifest['dataset_id']=fingerprint(manifest)
    folder=Path(root)/'data/training/datasets'/manifest['dataset_id'];folder.mkdir(parents=True,exist_ok=True)
    np.save(folder/'candles.npy',array,allow_pickle=False)
    for name,indices in splits.items():np.save(folder/(name+'.npy'),indices,allow_pickle=False)
    manifest['array_sha256']=hashlib.sha256((folder/'candles.npy').read_bytes()).hexdigest()
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    memory.record_project_data('agent_timestral_training_dataset',manifest['dataset_id'],manifest)
    progress(stage='dataset',message='Historico recente congelado para aprendizado automatico',candles=len(array))
    return folder,manifest
