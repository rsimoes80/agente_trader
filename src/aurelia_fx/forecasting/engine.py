"""Heavy imports live only inside the dedicated model subprocess."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from .config import SDK_REVISION, TimestralConfig


def engine_main():
    try:
        import numpy as np
        import torch
        from huggingface_hub import snapshot_download
        from timestral import TimestralForecaster

        options = json.loads(sys.stdin.readline())
        options["horizons"] = tuple(options["horizons"])
        config = TimestralConfig(**options)
        torch.set_num_threads(config.threads)
        torch.manual_seed(0)
        device = (
            "cuda"
            if config.device in {"auto", "cuda"} and torch.cuda.is_available()
            else "cpu"
        )
        if config.device == "cuda" and device != "cuda" and not config.cpu_fallback:
            raise RuntimeError("CUDA indisponível e fallback CPU desabilitado.")
        directory = Path(
            snapshot_download(
                config.model,
                revision=config.revision,
                cache_dir=config.cache_dir or None,
                local_files_only=config.local_files_only,
                allow_patterns=["config.json", "model.safetensors"],
            )
        )
        weights = directory / "model.safetensors"
        with weights.open("rb") as handle:
            artifact = hashlib.file_digest(handle, "sha256").hexdigest()
        try:
            model = TimestralForecaster.from_pretrained(
                directory, device=device, max_context=config.context
            )
        except torch.cuda.OutOfMemoryError:
            if device != "cuda" or not config.cpu_fallback:
                raise
            torch.cuda.empty_cache()
            device = "cpu"
            model = TimestralForecaster.from_pretrained(
                directory, device=device, max_context=config.context
            )
        metadata = dict(
            model=config.model,
            revision=directory.name,
            artifact_sha256=artifact,
            sdk_revision=SDK_REVISION,
            device=device,
        )
        print(json.dumps(dict(ready=True, **metadata)), flush=True)
        for line in sys.stdin:
            try:
                request = json.loads(line)
                values = request["values"]
                if not config.min_context <= len(values) <= config.context:
                    raise ValueError("Contexto fora dos limites.")
                context = np.asarray(values, dtype=np.float64).reshape(1, 1, -1)
                if not np.isfinite(context).all() or (context <= 0).any():
                    raise ValueError("Contexto contém valores inválidos.")
                started = time.monotonic()
                forecast = model.forecast(context, prediction_length=12)
                quantiles = torch.stack(
                    [forecast.quantile(q)[0, 0] for q in (0.1, 0.5, 0.9)], dim=-1
                )
                result = dict(
                    **metadata,
                    levels=[0.1, 0.5, 0.9],
                    quantiles=quantiles.detach().cpu().double().tolist(),
                    latency_ms=(time.monotonic() - started) * 1000,
                )
                print(json.dumps(dict(ok=True, **result), allow_nan=False), flush=True)
            except Exception as exc:
                print(
                    json.dumps(dict(ok=False, error_type=type(exc).__name__)),
                    flush=True,
                )
    except Exception as exc:
        print(json.dumps(dict(ready=False, error_type=type(exc).__name__)), flush=True)
        return 2
    return 0
