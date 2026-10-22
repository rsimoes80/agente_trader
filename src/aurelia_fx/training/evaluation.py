"""Evaluate a sealed checkpoint through production's public SDK inference path."""
import json
from pathlib import Path

def evaluate(root,folder,output,progress,check):
    import numpy as np
    import torch
    from timestral import TimestralForecaster
    from huggingface_hub import snapshot_download
    from .proof import SOURCE_MODEL,SOURCE_REVISION,file_hash
    from .metrics import forecast_metrics,paired_day_interval,forecast_gate
    torch.set_num_threads(1);root,folder,output=Path(root),Path(folder),Path(output)
    raw_path=output/'raw-head-report.json'
    if not raw_path.exists():raw_path.write_bytes((output/'forecast-report.json').read_bytes())
    report=json.loads(raw_path.read_text());sealed=json.loads((output/'selection.json').read_text())
    if file_hash(output/'candidate/model.safetensors')!=sealed['candidate_sha256']:raise ValueError('Sealed candidate changed')
    from .dataset import validate_dataset
    manifest,data=validate_dataset(folder)
    source=snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,local_files_only=True,token=False,
        cache_dir=str(root/'data/training/cache'),allow_patterns=['config.json','model.safetensors','LICENSE'])
    f=TimestralForecaster.from_pretrained(source,device='cpu',max_context=256)
    original={k:t.detach().clone() for k,t in f.model.head.state_dict().items()}
    from safetensors.torch import load_file
    candidate=load_file(output/'best-head.safetensors')
    saved=load_file(output/'candidate/model.safetensors')
    if any(not torch.equal(t,saved['head.'+k]) for k,t in candidate.items()):raise ValueError('Candidate head disagrees with sealed export')
    del saved
    report['evaluation_path']='public TimestralForecaster.forecast; symmetric averaging and nonnegative clipping'
    report['selection']['validation_objective']='context-only raw predict_block pinball; public inference evaluated after selection'
    for phase in ('validation','test'):
        indices=np.load(folder/(phase+'.npy'),allow_pickle=False)
        target=data[indices[:,None]+np.arange(12)[None,:],4];reference=data[indices-1,4]
        results={};losses={}
        for name,head in (('source',original),('candidate',candidate)):
            f.model.head.load_state_dict(head);predicted=np.empty((len(indices),12,len(f.quantile_levels)),dtype=np.float32)
            for offset in range(0,len(indices),8):
                check();batch=indices[offset:offset+8]
                x=np.asarray(data[batch[:,None]+np.arange(-256,0)[None,:],4],dtype=np.float32)
                predicted[offset:offset+len(batch)]=f.forecast(x,prediction_length=12).quantiles[:,0].numpy()
                if offset%160==0:progress(status='VALIDATING',stage='validation',message='Conferindo previsoes pelo SDK publico',partition=phase+':'+name,completed=offset,total=len(indices))
            results[name],losses[name]=forecast_metrics(predicted,target,reference,f.quantile_levels)
            np.save(output/(phase+'-'+name+'-public-predictions.npy'),predicted,allow_pickle=False)
        constant=np.broadcast_to(reference[:,None,None],predicted.shape)
        results['constant'],_=forecast_metrics(constant,target,reference,f.quantile_levels)
        for h in results['constant']['horizons'].values():h['direction_accuracy_pct']=None
        interval=paired_day_interval(losses['source'],losses['candidate'],data[indices-1,0]+300)
        report['partitions'][phase]=dict(**results,uncertainty=interval,gate=forecast_gate(results['source'],results['candidate'],interval))
    (output/'forecast-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
