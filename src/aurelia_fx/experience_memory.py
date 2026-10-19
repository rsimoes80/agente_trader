"""Append-only SQLite journal and objective retrieval of comparable experiences."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import contextmanager
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

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

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

    def record_decision(self, decision: Decision, *, session: str, regime: str,
                        context: dict[str, Any] | None = None) -> None:
        payload_dict = decision.as_dict()
        if context:
            if set(context) & set(payload_dict):
                raise ValueError("Decision context cannot overwrite contract fields.")
            payload_dict.update(context)
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

    def record_event(self, table: str, event_id: str, aggregate_id: str, status: str, payload: dict[str, Any],
                     *, observed_at: datetime | None = None) -> None:
        if table not in {"hypothesis_events", "expectation_events"}:
            raise ValueError("Somente eventos de hipótese/expectativa podem ser gravados por este método.")
        text, digest = self._encode(payload)
        now = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
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
        run_id: str | None = None, before: datetime | None = None,
    ) -> SimilarityResult:
        if minimum_sample_count < 1:
            raise ValueError("minimum_sample_count precisa ser positivo.")
        with self._connect() as db:
            query = """SELECT e.experience_id, e.process_classification, e.result_in_r FROM experiences e
                JOIN decisions d ON d.decision_id=e.decision_id
                WHERE e.symbol=? AND e.session=? AND e.market_regime=? AND e.strategy_id=? AND e.strategy_version=?
                AND e.direction IS ?"""
            parameters: list[Any] = [symbol, session, market_regime, strategy_id, strategy_version, direction]
            if run_id is not None:
                query += " AND d.run_id=?"
                parameters.append(run_id)
            if before is not None:
                query += " AND e.created_at_utc < ?"
                parameters.append(before.astimezone(timezone.utc).isoformat())
            query += " ORDER BY e.created_at_utc, e.experience_id"
            rows = db.execute(query, parameters).fetchall()
        classes = Counter(row["process_classification"] for row in rows)
        returns = [row["result_in_r"] for row in rows if row["result_in_r"] is not None]
        mean_r = sum(returns) / len(returns) if len(returns) >= minimum_sample_count else None
        return SimilarityResult(
            sample_count=len(rows), minimum_sample_count=minimum_sample_count,
            sufficient_sample=len(rows) >= minimum_sample_count,
            process_classifications=dict(classes), result_in_r_mean=mean_r,
            experience_ids=tuple(row["experience_id"] for row in rows),
        )
