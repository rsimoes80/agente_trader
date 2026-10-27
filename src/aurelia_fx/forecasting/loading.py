"""Load the pinned Timestral SDK without allocating throwaway weight copies.

Same float32 weights and forecaster defaults as SDK load_model. The sole
nonpersistent RoPE buffer is rebuilt on the destination device, as in the SDK.
"""
from pathlib import Path


def load_forecaster(directory, *, device, max_context):
    import torch
    from safetensors.torch import load_file
    from timestral.config import TimestralConfig
    from timestral.model import TimestralModel
    from timestral import TimestralForecaster

    directory=Path(directory)
    config=TimestralConfig.load(directory/'config.json')
    with torch.device('meta'):
        model=TimestralModel(config)
    weights=load_file(directory/'model.safetensors',device='cpu')
    model.load_state_dict(weights,strict=True,assign=True)
    del weights
    # The pinned SDK intentionally omits inv_freq from the checkpoint. Do not
    # materialize any unknown meta buffers with uninitialized values.
    for name,buffer in model.named_buffers():
        if buffer.is_meta and name!='transformer.rope.inv_freq':
            raise RuntimeError('UNSUPPORTED_TIMESTRAL_META_BUFFER')
    rope=model.transformer.rope
    rope.inv_freq=torch.empty(rope.inv_freq.shape,device=device,dtype=torch.float32)
    model.to(device=device,dtype=torch.float32)
    rope.rebuild_inv_freq()
    if any(p.is_meta for p in model.parameters()) or any(b.is_meta for b in model.buffers()):
        raise RuntimeError('TIMESTRAL_WEIGHTS_NOT_MATERIALIZED')
    model.eval()
    return TimestralForecaster(model,max_context=max_context)
