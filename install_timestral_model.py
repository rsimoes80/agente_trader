"""One-time public model download. No credentials or paid API required."""

import json
from pathlib import Path

from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parent


def main():
    path = ROOT / "data/timestral.json"
    config = json.loads(path.read_text()) if path.exists() else {"enabled": False}
    model = config.get("model", "mistralai/Timestral-209M")
    revision = HfApi().model_info(model, revision=config.get("revision", "main")).sha
    cache = ROOT / "data/models/timestral"
    snapshot_download(
        model,
        revision=revision,
        cache_dir=cache,
        allow_patterns=["config.json", "model.safetensors", "LICENSE"],
    )
    config.update(
        model=model, revision=revision, cache_dir=str(cache), local_files_only=True
    )
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print("Modelo instalado, revisão fixa:", revision)


if __name__ == "__main__":
    main()
