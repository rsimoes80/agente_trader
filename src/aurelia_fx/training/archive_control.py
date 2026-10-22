"""Secondary 209M comparison, limited to identical archived inputs and target periods."""
from datetime import datetime,timezone
import json
from pathlib import Path

def compare(memory,root,folder,output,check=lambda:None):
    import numpy as np
    from .dataset import validate_dataset
    from aurelia_fx.agent_model import fingerprint
    from aurelia_fx.domain import Candle
    from aurelia_fx.forecasting.config import load_config
    manifest,data=validate_dataset(folder);cfg=load_config();first=manifest['boundaries'][1];end=manifest['source_as_of']
    with memory.pool.connection() as c:
        records=c.execute("""SELECT DISTINCT ON(record_key) payload_json,payload_sha256 FROM project_records
            WHERE record_type='agent_forecast_cache' AND payload_json::jsonb->>'configuration'=%s
            AND (payload_json::jsonb->>'input_last')::timestamptz>=%s
            AND (payload_json::jsonb->>'input_last')::timestamptz<%s
            ORDER BY record_key,recorded_at,payload_sha256""",(cfg.fingerprint,first,end)).fetchall()
    matches=[];seen=set()
    for record in records:
        p=json.loads(record['payload_json'])
        if memory._encode(p)[1]!=record['payload_sha256']:raise ValueError('Archived forecast integrity failure')
        if p.get('input_bars')!=256:continue
        stamp=datetime.fromisoformat(p['input_last']).timestamp();i=int(np.searchsorted(data[:,0],stamp))+1
        if i<256 or i+12>len(data) or data[i-1,0]!=stamp:continue
        if not (np.diff(data[i-256:i+12,0])==300).all():continue
        if data[i,0]<datetime.fromisoformat(first).timestamp() or data[i+11,0]+300>datetime.fromisoformat(end).timestamp():continue
        bars=[Candle(datetime.fromtimestamp(float(r[0]),timezone.utc),*map(float,r[1:5]),float(r[5]),None if np.isnan(r[6]) else float(r[6])).as_dict() for r in data[i-256:i]]
        if fingerprint(bars)!=p['input_hash'] or i in seen:continue
        archived=p['output']
        if archived.get('model')!='mistralai/Timestral-209M' or archived.get('sdk_revision')!=cfg_sdk():continue
        seen.add(i);matches.append((i,archived))
    result=dict(status='NO_MATCHED_CONTEXTS',matched_windows=len(matches),archived_records=len(records),
        scope='secondary convenience sample of exact cached 256-bar inputs; not the uniform primary test',
        model='mistralai/Timestral-209M',used_for_selection=False,live_model_changed=False)
    if matches:
        import torch
        from safetensors.torch import load_file
        from timestral import TimestralForecaster
        from huggingface_hub import snapshot_download
        from .proof import SOURCE_MODEL,SOURCE_REVISION
        from .metrics import forecast_metrics
        torch.set_num_threads(1)
        source=snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,local_files_only=True,token=False,cache_dir=str(Path(root)/'data/training/cache'),allow_patterns=['config.json','model.safetensors','LICENSE'])
        f=TimestralForecaster.from_pretrained(source,device='cpu',max_context=256)
        original={k:t.detach().clone() for k,t in f.model.head.state_dict().items()}
        candidate=load_file(Path(output)/'best-head.safetensors');indices=np.array([i for i,_ in matches])
        target=data[indices[:,None]+np.arange(12),4];reference=data[indices-1,4];metrics={}
        qindices=[f.quantile_levels.index(q) for q in (.1,.5,.9)]
        for name,head in (('source_5m',original),('candidate_5m',candidate)):
            f.model.head.load_state_dict(head);parts=[]
            for offset in range(0,len(indices),8):
                check();batch=indices[offset:offset+8];x=np.asarray(data[batch[:,None]+np.arange(-256,0),4],dtype=np.float32)
                values=f.forecast(x,prediction_length=12).quantiles[:,0].numpy()
                parts.append(values[:,:,qindices])
            metrics[name],_=forecast_metrics(np.concatenate(parts),target,reference,[.1,.5,.9])
        metrics['archived_209m'],_=forecast_metrics(np.asarray([p['quantiles'] for _,p in matches]),target,reference,[.1,.5,.9])
        result.update(status='DESCRIPTIVE_ONLY',metrics=metrics,independent_evidence=False,
            original_209m_artifact_hashes=sorted({p['artifact_sha256'] for _,p in matches}))
    (Path(output)/'archive-control.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result

def cfg_sdk():
    from aurelia_fx.forecasting.config import SDK_REVISION
    return SDK_REVISION
