"""Small differentiability/export proof, not an EURUSD performance experiment."""
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path

SOURCE_MODEL='mistralai/Timestral-5M'
SOURCE_REVISION='bdd20cfc15a3fea0e4cb5ccef37f8d3ca7aa335f'
SDK_REVISION='a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff'


def file_hash(path):
    with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def tensor_hash(items):
    digest=hashlib.sha256()
    for name,value in sorted(items):
        digest.update(name.encode());digest.update(value.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def pinball_loss(prediction,target,levels):
    import torch
    if prediction.ndim!=3 or target.shape!=prediction.shape[:2] or len(levels)!=prediction.shape[-1]:
        raise ValueError('Quantile target shape mismatch')
    q=torch.as_tensor(levels,device=prediction.device,dtype=prediction.dtype)
    error=target.unsqueeze(-1)-prediction
    return torch.maximum(q*error,(q-1)*error).mean()


def prepare(root):
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,
        cache_dir=str(Path(root)/'data/training/cache'),token=False,
        allow_patterns=['config.json','model.safetensors','LICENSE']))


def run(root,output):
    import torch
    from safetensors.torch import save_file
    from timestral import TimestralForecaster
    torch.set_num_threads(1);torch.manual_seed(31)
    root,output=Path(root),Path(output)
    if not output.resolve().is_relative_to((root/'data/training/proofs').resolve()):
        raise ValueError('Proof output must stay in training/proofs')
    active=root/'data/timestral.json'
    active_before=file_hash(active) if active.exists() else None
    # Download is an explicit preceding step; this worker stays offline.
    from huggingface_hub import snapshot_download
    source=Path(snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,token=False,
        cache_dir=str(root/'data/training/cache'),local_files_only=True,
        allow_patterns=['config.json','model.safetensors','LICENSE']))
    source_before=file_hash(source/'model.safetensors')
    forecaster=TimestralForecaster.from_pretrained(source,device='cpu',max_context=64)
    model=forecaster.model
    for parameter in model.parameters():parameter.requires_grad_(False)
    for parameter in model.head.parameters():parameter.requires_grad_(True)
    frozen=lambda:((n,p) for n,p in model.named_parameters() if not p.requires_grad)
    backbone_before=tensor_hash(frozen())
    head_before=tensor_hash(model.head.named_parameters())
    # Future targets are separate tensors; only the context reaches predict_block.
    x=torch.arange(76,dtype=torch.float32)
    values=1.1+.00003*x+.0002*torch.sin(x*.35)
    context=values[:64].reshape(1,64);target=values[64:].reshape(1,12)
    observed=torch.ones_like(context,dtype=torch.bool);groups=torch.zeros(1,dtype=torch.long)
    scale=context.diff().abs().mean().clamp_min(1e-6)
    optimizer=torch.optim.AdamW(model.head.parameters(),lr=1e-5,weight_decay=0)
    losses=[];norms=[]
    for _ in range(3):
        optimizer.zero_grad(set_to_none=True)
        prediction=model.predict_block(context,observed,groups,horizon_patches=1)[:,:12]
        loss=pinball_loss(prediction,target,model.config.quantile_knots)/scale
        if not torch.isfinite(loss):raise ValueError('Nonfinite training loss')
        loss.backward()
        if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.head.parameters()):
            raise ValueError('Nonfinite head gradient')
        norm=torch.nn.utils.clip_grad_norm_(model.head.parameters(),1.0)
        norms.append(float(norm));losses.append(float(loss.detach()))
        optimizer.step()
    head_after=tensor_hash(model.head.named_parameters())
    if head_after==head_before:raise ValueError('No head weights changed')
    if tensor_hash(frozen())!=backbone_before:raise ValueError('Frozen backbone changed')
    candidate=output/'candidate';candidate.mkdir(exist_ok=False)
    model.config.save(candidate/'config.json')
    save_file({n:v.detach().contiguous() for n,v in model.state_dict().items()},candidate/'model.safetensors')
    license_path=source/'LICENSE'
    if license_path.exists():(candidate/'LICENSE').write_bytes(license_path.read_bytes())
    expected=forecaster.forecast(context,prediction_length=12).quantiles.clone()
    trainable=sum(p.numel() for p in model.parameters() if p.requires_grad)
    total=sum(p.numel() for p in model.parameters())
    del optimizer,model,forecaster
    import gc
    gc.collect()
    reloaded=TimestralForecaster.from_pretrained(candidate,device='cpu',max_context=64)
    actual=reloaded.forecast(context,prediction_length=12).quantiles
    if not torch.equal(expected,actual):raise ValueError('Reloaded forecasts differ')
    if file_hash(source/'model.safetensors')!=source_before:raise ValueError('Source weights changed')
    if (file_hash(active) if active.exists() else None)!=active_before:raise ValueError('Active configuration changed')
    result=dict(status='TECHNICAL_PROOF_PASSED_NOT_VALIDATED',created_at=datetime.now(timezone.utc).isoformat(),
        source_model=SOURCE_MODEL,source_revision=SOURCE_REVISION,sdk_revision=SDK_REVISION,
        data='deterministic synthetic series, NOT market data',steps=3,context=64,horizon=12,
        total_parameters=total,trainable_head_parameters=trainable,losses=losses,gradient_norms=norms,
        head_changed=True,backbone_unchanged=True,source_weights_unchanged=True,
        source_sha256=source_before,candidate_sha256=file_hash(candidate/'model.safetensors'),
        reload_predictions_equal=True,active_configuration_unchanged=True,live_model_changed=False,
        trading_quality_evaluated=False,versions={p:importlib.metadata.version(p) for p in ['torch','timestral','numpy','safetensors']})
    (output/'proof.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
