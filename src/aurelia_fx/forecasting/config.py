from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK_REVISION = "a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff"


@dataclass(frozen=True)
class TimestralConfig:
    enabled: bool = False
    model: str = "mistralai/Timestral-209M"
    revision: str = "main"
    device: str = "auto"
    cpu_fallback: bool = True
    timeframe: str = "M5"
    horizons: tuple[int, ...] = (3, 6, 12)
    mode: str = "observe_only"
    context: int = 256
    min_context: int = 64
    timeout_seconds: float = 45
    load_timeout_seconds: float = 180
    memory_mb: int = 4096
    threads: int = 2
    local_files_only: bool = True
    python: str = ""
    cache_dir: str = ""

    def __post_init__(self):
        if any(
            type(getattr(self, key)) is not bool
            for key in ("enabled", "cpu_fallback", "local_files_only")
        ):
            raise ValueError("Ativação e opções Timestral exigem booleanos JSON.")
        if any(
            type(getattr(self, key)) is not int
            for key in ("context", "min_context", "memory_mb", "threads")
        ):
            raise ValueError("Contagens Timestral exigem inteiros.")
        if self.mode != "observe_only" or self.timeframe != "M5":
            raise ValueError("Timestral suporta somente M5 observe_only.")
        if self.horizons != (3, 6, 12):
            raise ValueError("Horizontes Timestral devem ser 3,6,12.")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("Dispositivo Timestral inválido.")
        if not 32 <= self.min_context <= self.context <= 2048:
            raise ValueError("Contexto Timestral fora dos limites.")
        if (
            not 1 <= self.timeout_seconds <= 600
            or not 1 <= self.load_timeout_seconds <= 900
        ):
            raise ValueError("Timeout Timestral inválido.")
        if not 512 <= self.memory_mb <= 32768 or not 1 <= self.threads <= 8:
            raise ValueError("Limites de recursos Timestral inválidos.")

    @property
    def fingerprint(self):
        # Paths and activation switches do not change the numerical model contract.
        data = asdict(self)
        for key in (
            "python",
            "cache_dir",
            "enabled",
            "timeout_seconds",
            "load_timeout_seconds",
            "memory_mb",
        ):
            data.pop(key)
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def load_config(path: Path | None = None) -> TimestralConfig:
    path = path or ROOT / "data/timestral.json"
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for name, value in os.environ.items():
        if not name.startswith("TIMESTRAL_"):
            continue
        key = name[10:].lower()
        if key not in TimestralConfig.__dataclass_fields__:
            continue
        default = getattr(TimestralConfig(), key)
        if isinstance(default, bool):
            if value.lower() not in {"true", "false"}:
                raise ValueError(f"{name} exige true/false.")
            data[key] = value.lower() == "true"
        elif isinstance(default, int):
            data[key] = int(value)
        elif isinstance(default, float):
            data[key] = float(value)
        elif key == "horizons":
            data[key] = tuple(int(v) for v in value.split(","))
        else:
            data[key] = value
    if "horizons" in data:
        data["horizons"] = tuple(data["horizons"])
    return TimestralConfig(**data)
