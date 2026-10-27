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
    from .checkpoints import atomic_json,digest
    from aurelia_fx.agent_model import fingerprint
    torch.set_num_threads(1);root,folder,output=Path(root),Path(folder),Path(output)
    raw_path=output/'raw-head-report.json'
    if not raw_path.exists():
        original_report=output/'forecast-report.json'
        if not original_report.exists():original_report=output/'sealed-report-seed.json'
        atomic_json(raw_path,json.loads(original_report.read_text()))
    report=json.loads(raw_path.read_text());sealed=json.loads((output/'selection.json').read_text())
    if file_hash(output/'candidate/model.safetensors')!=sealed['candidate_sha256']:raise ValueError('Sealed candidate changed')
    from .dataset import validate_dataset
    manifest,data=validate_dataset(folder)
    from .scope import assert_same
    assert_same(manifest,report)
    price_unit=manifest.get('price_unit',.0001)
    identity=fingerprint(dict(dataset=manifest,candidate=sealed['candidate_sha256'],source=report['source_sha256'],path='public-sdk-v1'))
    progress_path=output/'public-evaluation-progress.json'
    completed=json.loads(progress_path.read_text()) if progress_path.exists() else dict(identity=identity,arrays={})
    if completed['identity']!=identity:raise ValueError('Public evaluation checkpoint identity mismatch')
    source=snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,local_files_only=True,token=False,
        cache_dir=str(root/'data/training/cache'),allow_patterns=['config.json','model.safetensors','LICENSE'])
    if file_hash(Path(source)/'model.safetensors')!=report['source_sha256']:raise ValueError('Evaluation source changed')
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
            f.model.head.load_state_dict(head);key=phase+':'+name
            array_path=output/(phase+'-'+name+'-public-predictions.npy')
            saved_hash=completed['arrays'].get(key)
            if saved_hash:
                if digest(array_path)!=saved_hash:raise ValueError('Completed public predictions changed')
                predicted=np.load(array_path,allow_pickle=False)
                if predicted.shape!=(len(indices),12,len(f.quantile_levels)):raise ValueError('Public prediction shape mismatch')
            else:predicted=np.empty((len(indices),12,len(f.quantile_levels)),dtype=np.float32)
            for offset in (() if saved_hash else range(0,len(indices),8)):
                check();batch=indices[offset:offset+8]
                x=np.asarray(data[batch[:,None]+np.arange(-256,0)[None,:],4],dtype=np.float32)
                predicted[offset:offset+len(batch)]=f.forecast(x,prediction_length=12).quantiles[:,0].numpy()
                if offset%160==0:progress(status='VALIDATING',stage='validation',message='Conferindo previsoes pelo SDK publico',partition=phase+':'+name,completed=offset,total=len(indices))
            results[name],losses[name]=forecast_metrics(predicted,target,reference,f.quantile_levels,price_unit=price_unit)
            if not saved_hash:
                import os
                temporary=array_path.with_suffix('.tmp')
                with temporary.open('wb') as stream:
                    np.save(stream,predicted,allow_pickle=False);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,array_path)
                completed['arrays'][key]=digest(array_path);atomic_json(progress_path,completed)
            progress(status='VALIDATING',stage='validation',partition=key,completed=len(indices),total=len(indices),
                message='Avaliação concluída preservada',saved_checkpoint=dict(stage='validation',partition=key,completed=len(indices),total=len(indices)))
        constant=np.broadcast_to(reference[:,None,None],predicted.shape)
        results['constant'],_=forecast_metrics(constant,target,reference,f.quantile_levels,price_unit=price_unit)
        for h in results['constant']['horizons'].values():h['direction_accuracy_pct']=None
        interval=paired_day_interval(losses['source'],losses['candidate'],data[indices-1,0]+300)
        report['partitions'][phase]=dict(**results,uncertainty=interval,gate=forecast_gate(results['source'],results['candidate'],interval))
    atomic_json(output/'forecast-report.json',report)
    return report
