"""Select configured PostgreSQL storage, with explicit offline SQLite support."""

import json
import os
from pathlib import Path

from .experience_memory import ExperienceMemory

ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str | None:
    value = os.environ.get("AGENTE_TRADER_DATABASE_URL")
    if value:
        return value
    path = ROOT / "data/database.json"
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8"))["database_url"]
        if not isinstance(value, str) or not value.startswith(
            ("postgresql://", "postgres://")
        ):
            raise ValueError("Invalid database configuration.")
        return value
    return None


def open_memory(sqlite_path: Path | None = None) -> ExperienceMemory:
    if sqlite_path is not None:
        return ExperienceMemory(sqlite_path)
    url = database_url()
    if url:
        from .postgres_memory import PostgresMemory

        memory = PostgresMemory(url)
        try:
            memory.sync_knowledge(ROOT / "data/knowledge")
        except Exception:
            memory.close()
            raise
        return memory
    raise RuntimeError(
        "Configure AGENTE_TRADER_DATABASE_URL or data/database.json; --db is offline SQLite only."
    )
