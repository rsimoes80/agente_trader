"""Instrument-scoped head fine tuning with a frozen backbone and sealed evaluation."""
from datetime import datetime,timezone
import gc
import json
from pathlib import Path

from .proof import SOURCE_MODEL,SOURCE_REVISION,SDK_REVISION,file_hash,tensor_hash,pinball_loss
from .metrics import forecast_metrics,paired_day_interval,forecast_gate


def train(root,folder,output,progress,check,recipe='conservative'):
    import numpy as np
    import torch
    from safetensors.torch import save_file,load_file
    from huggingface_hub import snapshot_download
    from timestral import TimestralForecaster
    from timestral.scaler import denormalize_quantiles
    from .protocol import RECIPES
    if recipe not in RECIPES:raise ValueError('Unknown training recipe')
    settings=RECIPES[recipe]
    torch.set_num_threads(1);torch.manual_seed(31)
    folder,output,root=Path(folder),Path(output),Path(root)
    from .dataset import validate_dataset
    manifest,data=validate_dataset(folder)
    from .scope import identity
    scope=identity(manifest);price_unit=manifest.get('price_unit',.0001)
    source=Path(snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,local_files_only=True,
        cache_dir=str(root/'data/training/cache'),token=False,allow_patterns=['config.json','model.safetensors','LICENSE']))
    source_hash=file_hash(source/'model.safetensors')
    f=TimestralForecaster.from_pretrained(source,device='cpu',max_context=256);model=f.model
    for p in model.parameters():p.requires_grad_(False)
    frozen_before=tensor_hash((n,p) for n,p in model.named_parameters() if not n.startswith('head.'))
    initial_head={n:t.detach().clone() for n,t in model.head.state_dict().items()}
    output.mkdir(parents=True,exist_ok=True);cache=output/'features';cache.mkdir(exist_ok=True)
    levels=model.config.quantile_knots;dimension=model.config.d_model
    from .checkpoints import FeatureCheckpoint,save_epoch,load_epoch,atomic_json
    from aurelia_fx.agent_model import fingerprint
    identity=fingerprint(dict(dataset=manifest,source=source_hash,sdk=SDK_REVISION,recipe=recipe,settings=settings))
    captured={}
    hook=model.head.register_forward_pre_hook(lambda module,args:captured.update(hidden=args[0].detach()))
    for phase in ('train','validation','test'):
        indices=np.load(folder/(phase+'.npy'),allow_pickle=False);n=len(indices)
        checkpoint=FeatureCheckpoint(cache,phase,identity,dict(hidden=(n,1,dimension),loc=(n,1,1),
            scale=(n,1,1),source=(n,12,len(levels)),target=(n,12)))
        arrays=checkpoint.arrays
        progress(status='TRAINING',stage='features',partition=phase,completed=checkpoint.completed,total=n,
            message='Retomando contextos validados' if checkpoint.completed else 'Extraindo contexto congelado')
        for offset in range(checkpoint.completed,n,8):
            check();batch=indices[offset:offset+8];size=len(batch)
            x=torch.from_numpy(np.asarray(data[batch[:,None]+np.arange(-256,0)[None,:],4],dtype=np.float32))
            mask=torch.ones_like(x,dtype=torch.bool)
            with torch.no_grad():
                predicted=model.predict_block(x,mask,torch.arange(size),1)[:,:12]
                _,loc,scale=model.scale(x,mask)
                reconstructed=denormalize_quantiles(model.head(captured['hidden'])[:,:12],loc[:,-32].reshape(size,1,1),scale[:,-32].reshape(size,1,1),model.config.use_asinh)
                if not torch.equal(predicted,reconstructed):raise ValueError('Cached head features disagree with native model prediction')
            arrays['hidden'][offset:offset+size]=captured['hidden'].numpy()
            arrays['loc'][offset:offset+size]=loc[:,-32].reshape(size,1,1).numpy()
            arrays['scale'][offset:offset+size]=scale[:,-32].reshape(size,1,1).numpy()
            arrays['source'][offset:offset+size]=predicted.numpy()
            arrays['target'][offset:offset+size]=data[batch[:,None]+np.arange(12)[None,:],4]
            if (offset+size)%160==0 or offset+size==n:
                checkpoint.commit(offset+size)
                progress(status='TRAINING',stage='features',message='Contextos salvos para retomada',partition=phase,completed=offset+size,total=n,
                    saved_checkpoint=dict(stage='features',partition=phase,completed=offset+size,total=n))
        del arrays,checkpoint
    hook.remove();captured.clear();gc.collect()
    def arrays(phase):return {name:np.load(cache/(phase+'-'+name+'.npy'),mmap_mode='r',allow_pickle=False) for name in ('hidden','loc','scale','source','target')}
    train_data=arrays('train');validation=arrays('validation')
    def predict_phase(a):
        output=np.empty_like(a['source'])
        with torch.no_grad():
            for i in range(0,len(output),32):
                pred=model.head(torch.tensor(a['hidden'][i:i+32]))[:,:12]
                output[i:i+32]=denormalize_quantiles(pred,torch.tensor(a['loc'][i:i+32]),torch.tensor(a['scale'][i:i+32]),model.config.use_asinh).numpy()
        return output
    def score(pred,target):
        error=np.asarray(target,dtype=np.float64)[...,None]-pred
        return float(np.maximum(np.asarray(levels)*error,(np.asarray(levels)-1)*error).mean())
    best=score(validation['source'],validation['target']);best_epoch=0
    best_path=output/'best-head.safetensors';save_file(initial_head,best_path)
    history=[dict(epoch=0,validation_pinball_pips=best/price_unit)]
    for p in model.head.parameters():p.requires_grad_(True)
    optimizer=torch.optim.AdamW(model.head.parameters(),lr=settings['learning_rate'],weight_decay=0)
    rng=np.random.default_rng(31)
    epoch_path=output/'epoch.pt';resume=load_epoch(epoch_path,identity)
    start_epoch=1
    weight_update=None
    if resume:
        model.head.load_state_dict(resume['head']);optimizer.load_state_dict(resume['optimizer'])
        rng.bit_generator.state=resume['numpy_rng'];torch.set_rng_state(resume['torch_rng'])
        best=resume['best'];best_epoch=resume['best_epoch'];history=resume['history']
        weight_update=resume.get('weight_update')
        save_file(resume['best_head'],best_path);start_epoch=resume['epoch']+1
        progress(status='TRAINING',stage='training',message='Retomando após a última época concluída',epoch=resume['epoch'],epochs=settings['epochs'],**(dict(weight_update=weight_update) if weight_update else {}))
    for epoch in range(start_epoch,settings['epochs']+1):
        order=rng.permutation(len(train_data['hidden']));losses=[];last_gradient_at=None;steps=0
        for offset in range(0,len(order),32):
            check();idx=order[offset:offset+32];optimizer.zero_grad(set_to_none=True)
            pred=model.head(torch.tensor(train_data['hidden'][idx]))[:,:12]
            loc=torch.tensor(train_data['loc'][idx]);scale=torch.tensor(train_data['scale'][idx])
            raw=denormalize_quantiles(pred,loc,scale,model.config.use_asinh)
            target=torch.tensor(train_data['target'][idx])
            loss=pinball_loss((raw-loc)/scale,(target-loc.squeeze(-1))/scale.squeeze(-1),levels)
            if not torch.isfinite(loss):raise ValueError('Nonfinite training objective')
            loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.head.parameters(),1.,error_if_nonfinite=True)
            optimizer.step();losses.append(float(loss.detach()));steps+=1
            last_gradient_at=datetime.now(timezone.utc).isoformat()
            if offset%320==0:progress(status='TRAINING',stage='training',message='Ajustando somente a saida',epoch=epoch,epochs=settings['epochs'],completed=offset,total=len(order))
        value=score(predict_phase(validation),validation['target'])
        history.append(dict(epoch=epoch,training_normalized_pinball=float(np.mean(losses)),validation_pinball_pips=value/price_unit))
        if value<best:
            best=value;best_epoch=epoch;save_file({n:t.detach().contiguous() for n,t in model.head.state_dict().items()},best_path)
        weight_update=dict(epoch=epoch,optimizer_steps_in_epoch=steps,last_gradient_at=last_gradient_at,
            checkpoint_at=datetime.now(timezone.utc).isoformat(),
            head_tensor_sha256=tensor_hash(model.head.state_dict().items()),
            source_head_tensor_sha256=tensor_hash(initial_head.items()))
        weight_update['changed_from_source']=weight_update['head_tensor_sha256']!=weight_update['source_head_tensor_sha256']
        save_epoch(epoch_path,dict(epoch=epoch,head=model.head.state_dict(),optimizer=optimizer.state_dict(),
            numpy_rng=rng.bit_generator.state,torch_rng=torch.get_rng_state(),best=best,best_epoch=best_epoch,
            history=history,best_head=load_file(best_path),weight_update=weight_update),identity)
        progress(status='TRAINING',stage='training',epoch=epoch,epochs=settings['epochs'],completed=len(order),total=len(order),
            saved_checkpoint=dict(stage='training',epoch=epoch,epochs=settings['epochs']),weight_update=weight_update,message='Época concluída e salva')
    save_file({n:t.detach().contiguous() for n,t in model.head.state_dict().items()},output/'last-trained-head.safetensors')
    model.head.load_state_dict(load_file(best_path));model.eval()
    if tensor_hash((n,p) for n,p in model.named_parameters() if not n.startswith('head.'))!=frozen_before:raise ValueError('Frozen backbone changed')
    candidate=output/'candidate';candidate.mkdir(exist_ok=True)
    model.config.save(candidate/'config.json')
    save_file({n:t.detach().contiguous() for n,t in model.state_dict().items()},candidate/'model.safetensors')
    if (source/'LICENSE').exists():(candidate/'LICENSE').write_bytes((source/'LICENSE').read_bytes())
    selected_head=model.head.state_dict()
    sealed=dict(selected_epoch=best_epoch,selected_by='validation only',candidate_sha256=file_hash(candidate/'model.safetensors'),sealed_at=datetime.now(timezone.utc).isoformat(),
        candidate_weights_changed=any(not torch.equal(t,selected_head[n]) for n,t in initial_head.items()))
    # From this point on the head is immutable. A restart evaluates this same
    # candidate; it cannot return to fitting after seeing the test period.
    atomic_json(output/'sealed-report-seed.json',dict(**scope,price_unit=price_unit,dataset_id=manifest['dataset_id'],source_model=SOURCE_MODEL,
        source_revision=SOURCE_REVISION,sdk_revision=SDK_REVISION,source_sha256=source_hash,selection=sealed,
        epochs=history,partitions={},prior_market_data_seen=True,backbone_unchanged=True,
        live_model_changed=False,recipe=recipe,training_settings=settings,weight_update=weight_update))
    atomic_json(output/'selection.json',sealed)
    progress(status='VALIDATING',stage='validation',message='Avaliando o teste cronologico apos congelar o candidato',selection=sealed)
    report=dict(**scope,price_unit=price_unit,dataset_id=manifest['dataset_id'],source_model=SOURCE_MODEL,source_revision=SOURCE_REVISION,
                sdk_revision=SDK_REVISION,source_sha256=source_hash,selection=sealed,epochs=history,partitions={},
                prior_market_data_seen=True,backbone_unchanged=True,live_model_changed=False,recipe=recipe,training_settings=settings,weight_update=weight_update)
    for phase in ('validation','test'):
        a=arrays(phase);idx=np.load(folder/(phase+'.npy'),allow_pickle=False)
        predicted=predict_phase(a);target=data[idx[:,None]+np.arange(12)[None,:],4]
        reference=data[idx-1,4];times=data[idx-1,0]+300
        original,la=forecast_metrics(a['source'],target,reference,levels,price_unit=price_unit)
        tuned,lb=forecast_metrics(predicted,target,reference,levels,price_unit=price_unit)
        constant=np.broadcast_to(reference[:,None,None],predicted.shape)
        baseline,_=forecast_metrics(constant,target,reference,levels,price_unit=price_unit)
        for h in baseline['horizons'].values():h['direction_accuracy_pct']=None
        interval=paired_day_interval(la,lb,times)
        np.save(output/(phase+'-predictions.npy'),predicted,allow_pickle=False)
        report['partitions'][phase]=dict(source=original,candidate=tuned,constant=baseline,
            uncertainty=interval,gate=forecast_gate(original,tuned,interval))
    # Check the saved artifact through the public inference loader, not the training path.
    last_idx=int(np.load(folder/'test.npy',allow_pickle=False)[-1]);context=np.asarray(data[last_idx-256:last_idx,4],dtype=np.float32)
    expected=f.forecast(context,prediction_length=12).quantiles.clone()
    del optimizer,train_data,validation,model,f;gc.collect()
    reloaded=TimestralForecaster.from_pretrained(candidate,device='cpu',max_context=256)
    actual=reloaded.forecast(context,prediction_length=12).quantiles
    if not torch.equal(expected,actual):raise ValueError('Export/reload prediction mismatch')
    if file_hash(source/'model.safetensors')!=source_hash:raise ValueError('Original source changed')
    report['reload_predictions_equal']=True
    atomic_json(output/'forecast-report.json',report)
    return report
