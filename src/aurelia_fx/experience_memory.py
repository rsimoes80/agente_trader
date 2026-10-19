"""Append-only SQLite journal and objective retrieval of comparable experiences."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import Decision


@dataclass(frozen=True, slots=True)
class ExperienceRecord:
    experience_id: str
    created_at_utc: str
    symbol: str
    session: str
    market_regime: str
    snapshot_id: str
    decision_id: str
    strategy_id: str
    strategy_version: str
    config_version: str
    direction: str | None
    action_taken: str
    action_not_taken: str | None
    expected_behavior: str
    observed_behavior: str
    process_classification: str
    financial_result: dict[str, Any]
    process_result: dict[str, Any]
    knowledge_rule_ids: tuple[str, ...] = ()
    lessons_candidate: tuple[str, ...] = ()
    review_status: str = "needs_review"
    source_data_reference: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["knowledge_rule_ids"] = list(self.knowledge_rule_ids)
        payload["lessons_candidate"] = list(self.lessons_candidate)
        return payload


@dataclass(frozen=True, slots=True)
class SimilarityResult:
    sample_count: int
    minimum_sample_count: int
    sufficient_sample: bool
    process_classifications: dict[str, int]
    result_in_r_mean: float | None
    experience_ids: tuple[str, ...]


class ExperienceMemory:
    """Persistent memory; writes are append-only and never promote hypotheses."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    data_reference TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    action TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiences (
                    experience_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    session TEXT NOT NULL,
                    market_regime TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    config_version TEXT NOT NULL,
                    direction TEXT,
                    action_taken TEXT NOT NULL,
                    process_classification TEXT NOT NULL,
                    result_in_r REAL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES market_snapshots(snapshot_id),
                    FOREIGN KEY(decision_id) REFERENCES decisions(decision_id)
                );
                CREATE INDEX IF NOT EXISTS ix_experiences_context
                    ON experiences(symbol, session, market_regime, strategy_id, strategy_version, direction);
                CREATE TABLE IF NOT EXISTS hypothesis_events (
                    event_id TEXT PRIMARY KEY,
                    hypothesis_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS expectation_events (
                    event_id TEXT PRIMARY KEY,
                    expectation_id TEXT NOT NULL,
                    hypothesis_id TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    dataset_reference TEXT NOT NULL,
                    code_version TEXT NOT NULL,
                    strategy_version TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL
                );
            """)
            db.execute("""INSERT OR IGNORE INTO metadata(key,value) VALUES('schema_version',?)""", (str(self.SCHEMA_VERSION),))
            version = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
            if version != str(self.SCHEMA_VERSION):
                raise RuntimeError(f"SQLite schema incompatível: {version}.")
            for table in ("market_snapshots", "decisions", "experiences", "hypothesis_events", "expectation_events", "experiment_artifacts"):
                for operation in ("UPDATE", "DELETE"):
                    trigger = f"immutable_{table}_{operation.lower()}"
                    db.execute(f"""CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON {table}
                                 BEGIN SELECT RAISE(ABORT, 'journal rows are append-only'); END""")

    @staticmethod
    def _encode(payload: dict[str, Any]) -> tuple[str, str]:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return text, hashlib.sha256(text.encode("utf-8")).hexdigest()

    def record_snapshot(self, snapshot: dict[str, Any], *, session: str, regime: str, data_reference: str = "") -> None:
        payload, digest = self._encode(snapshot)
        stamp = snapshot.get("timestamp_utc")
        if not snapshot.get("snapshot_id") or not stamp or not snapshot.get("symbol") or not snapshot.get("timeframe"):
            raise ValueError("Snapshot sem ID, timestamp, symbol ou timeframe.")
        with self._connect() as db:
            db.execute("""INSERT INTO market_snapshots VALUES(?,?,?,?,?,?,?,?,?)""", (
                snapshot["snapshot_id"], stamp, snapshot["symbol"], session, regime,
                snapshot["timeframe"], data_reference, payload, digest,
            ))

    def record_decision(self, decision: Decision, *, session: str, regime: str) -> None:
        payload_dict = decision.as_dict()
        payload, digest = self._encode(payload_dict)
        with self._connect() as db:
            db.execute("""INSERT INTO decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                decision.decision_id, decision.run_id, decision.created_at.astimezone(timezone.utc).isoformat(),
                decision.symbol, session, regime, decision.strategy_id, decision.strategy_version,
                decision.action.value, decision.reason_code, payload, digest,
            ))

    def record_experience(self, record: ExperienceRecord) -> None:
        payload, digest = self._encode(record.as_dict())
        result_in_r = record.financial_result.get("result_in_r")
        if result_in_r is not None and (
            not isinstance(result_in_r, (int, float)) or isinstance(result_in_r, bool)
            or not math.isfinite(result_in_r)
        ):
            raise ValueError("financial_result.result_in_r precisa ser número finito ou nulo.")
        with self._connect() as db:
            db.execute("""INSERT INTO experiences VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                record.experience_id, record.created_at_utc, record.symbol, record.session,
                record.market_regime, record.snapshot_id, record.decision_id, record.strategy_id,
                record.strategy_version, record.config_version, record.direction, record.action_taken,
                record.process_classification, result_in_r, payload, digest,
            ))

    def record_event(self, table: str, event_id: str, aggregate_id: str, status: str, payload: dict[str, Any]) -> None:
        if table not in {"hypothesis_events", "expectation_events"}:
            raise ValueError("Somente eventos de hipótese/expectativa podem ser gravados por este método.")
        text, digest = self._encode(payload)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as db:
            if table == "hypothesis_events":
                db.execute("INSERT INTO hypothesis_events VALUES(?,?,?,?,?,?)", (event_id, aggregate_id, now, status, text, digest))
            else:
                hypothesis_id = str(payload.get("hypothesis_id", ""))
                if not hypothesis_id:
                    raise ValueError("Expectation event exige hypothesis_id.")
                db.execute("INSERT INTO expectation_events VALUES(?,?,?,?,?,?,?)", (event_id, aggregate_id, hypothesis_id, now, status, text, digest))

    def record_artifact(self, *, artifact_id: str, dataset_reference: str, code_version: str,
                        strategy_version: str, config_hash: str, status: str, payload: dict[str, Any]) -> None:
        text, digest = self._encode(payload)
        with self._connect() as db:
            db.execute("INSERT INTO experiment_artifacts VALUES(?,?,?,?,?,?,?,?,?)", (
                artifact_id, datetime.now(timezone.utc).isoformat(), dataset_reference, code_version,
                strategy_version, config_hash, status, text, digest,
            ))

    def retrieve_similar(
        self, *, symbol: str, session: str, market_regime: str, strategy_id: str,
        strategy_version: str, direction: str | None, minimum_sample_count: int = 30,
    ) -> SimilarityResult:
        if minimum_sample_count < 1:
            raise ValueError("minimum_sample_count precisa ser positivo.")
        with self._connect() as db:
            rows = db.execute("""SELECT experience_id, process_classification, result_in_r FROM experiences
                WHERE symbol=? AND session=? AND market_regime=? AND strategy_id=? AND strategy_version=?
                AND direction IS ? ORDER BY created_at_utc""",
                (symbol, session, market_regime, strategy_id, strategy_version, direction),
            ).fetchall()
        classes = Counter(row["process_classification"] for row in rows)
        returns = [row["result_in_r"] for row in rows if row["result_in_r"] is not None]
        mean_r = sum(returns) / len(returns) if len(rows) >= minimum_sample_count and returns else None
        return SimilarityResult(
            sample_count=len(rows), minimum_sample_count=minimum_sample_count,
            sufficient_sample=len(rows) >= minimum_sample_count,
            process_classifications=dict(classes), result_in_r_mean=mean_r,
            experience_ids=tuple(row["experience_id"] for row in rows),
        )
