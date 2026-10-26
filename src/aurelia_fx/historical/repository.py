"""Reuse append-only project_records: no second candle store or database."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .core import VERSION, utc


class HistoricalRepository:
    def __init__(self, memory):
        if not hasattr(memory, "pool"):
            raise ValueError("Historical archive requires PostgreSQL.")
        self.memory = memory

    @staticmethod
    def prefix(clock_id, timeframe):
        identity = hashlib.sha256(clock_id.encode()).hexdigest()[:24]
        return f"archive:{identity}:EURUSD:{timeframe}:"

    def ingest(self, rows, *, clock, timeframe):
        prefix = self.prefix(clock["clock_id"], timeframe)
        values = []
        for row in rows:
            payload = {
                **row,
                "symbol": "EURUSD",
                "timeframe": timeframe,
                "source": "mt5_history_archive",
                "clock_id": clock["clock_id"],
                "broker": clock["broker"],
                "server": clock["server"],
                "time_contract": clock["contract"],
            }
            text, digest = self.memory._encode(payload)
            values.append(("closed_candle", prefix + row["timestamp"], text, digest))
        with self.memory.pool.connection() as c, c.transaction():
            with c.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO project_records
                    (record_type,record_key,payload_json,payload_sha256,recorded_at) VALUES(%s,%s,%s,%s,clock_timestamp())
                    ON CONFLICT DO NOTHING""",
                    values,
                )
                inserted = cursor.rowcount
        return dict(
            received=len(rows), inserted=inserted, unchanged=len(rows) - inserted
        )

    def candles(self, *, clock_id, timeframe, start, as_of, known_by=None):
        prefix = self.prefix(clock_id, timeframe)
        # Bound by canonical UTC key, then select the last known immutable revision.
        with self.memory.pool.connection() as c:
            rows = c.execute(
                """SELECT DISTINCT ON(record_key) payload_json FROM project_records
                WHERE record_type='closed_candle' AND record_key>=%s AND record_key<=%s
                AND recorded_at<=COALESCE(%s::timestamptz,clock_timestamp())
                ORDER BY record_key,recorded_at DESC,payload_sha256 DESC""",
                (
                    prefix + utc(start).isoformat(),
                    prefix + utc(as_of).isoformat(),
                    known_by,
                ),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def latest(self, *, as_of=None, clock_id=None):
        with self.memory.pool.connection() as c:
            rows = c.execute(
                """SELECT payload_json,recorded_at FROM project_records
                WHERE record_type='historical_baseline' AND payload_json::jsonb ->> 'version'=%s
                AND (%s::text IS NULL OR payload_json::jsonb ->> 'clock_id'=%s)
                AND (payload_json::jsonb ->> 'as_of')::timestamptz<=%s
                AND recorded_at<=COALESCE(%s::timestamptz,clock_timestamp())
                ORDER BY recorded_at DESC LIMIT 1""",
                (
                    VERSION,
                    clock_id,
                    clock_id,
                    as_of or datetime.now(timezone.utc),
                    as_of,
                ),
            ).fetchall()
        if not rows:
            return None
        return {
            **json.loads(rows[0]["payload_json"]),
            "_recorded_at": rows[0]["recorded_at"].isoformat(),
        }

    def replay_dataset(self, *, timeframe="M5"):
        from ..domain import Candle
        from ..replay_data import ReplayDataset
        from .core import closed_rows, readiness, summarize

        baseline = self.latest()
        if baseline is None or timeframe not in baseline["timeframes"]:
            raise ValueError("Arquivo histórico mensal ainda indisponível.")
        if readiness(baseline, as_of=baseline["as_of"], clock_id=baseline["clock_id"]):
            raise ValueError(
                "A cobertura histórica ainda não permite congelar um replay mensal."
            )
        rows = self.candles(
            clock_id=baseline["clock_id"],
            timeframe=timeframe,
            start=baseline["start"],
            as_of=baseline["as_of"],
            known_by=baseline["_recorded_at"],
        )
        measured = summarize(
            rows,
            timeframe,
            start=baseline["start"],
            as_of=baseline["as_of"],
            days=baseline["days"],
        )
        if (
            measured["dataset_sha256"]
            != baseline["timeframes"][timeframe]["dataset_sha256"]
        ):
            raise ValueError("Revisão do arquivo não corresponde à janela congelada.")
        rows = closed_rows(
            rows, timeframe, start=baseline["start"], as_of=baseline["as_of"]
        )
        candles = tuple(
            Candle(
                utc(r["timestamp"]),
                *(r[k] for k in ("open", "high", "low", "close")),
                r["volume"],
                r.get("spread_pips"),
            )
            for r in rows
        )
        digest = hashlib.sha256(
            json.dumps([c.as_dict() for c in candles], sort_keys=True).encode()
        ).hexdigest()
        return ReplayDataset(
            candles,
            digest,
            "postgres_mt5_history_archive",
            "postgresql:historical-baseline:"
            + baseline["baseline_id"]
            + ":"
            + timeframe,
            {
                **baseline["source_clock"],
                "historical_baseline_id": baseline["baseline_id"],
                "archive_sha256": measured["dataset_sha256"],
                "archive_cutoff": baseline["_recorded_at"],
            },
        )

    def record_baseline(self, baseline):
        self.memory.record_project_data(
            "historical_baseline", baseline["baseline_id"], baseline
        )

    def frozen_candles(
        self, baseline, *, timeframe="M5", record_type="historical_baseline"
    ):
        """Load exactly the immutable revision described by this baseline."""
        from .core import summarize

        with self.memory.pool.connection() as c:
            record = c.execute(
                """SELECT recorded_at FROM project_records
                WHERE record_type=%s AND record_key=%s
                ORDER BY recorded_at LIMIT 1""",
                (record_type, baseline["baseline_id"]),
            ).fetchone()
        if record is None:
            raise ValueError("Baseline histórica não persistida.")
        frozen = {**baseline, "_recorded_at": record["recorded_at"].isoformat()}
        rows = self.candles(
            clock_id=baseline["clock_id"],
            timeframe=timeframe,
            start=baseline["start"],
            as_of=baseline["as_of"],
            known_by=record["recorded_at"],
        )
        measured = summarize(
            rows,
            timeframe,
            start=baseline["start"],
            as_of=baseline["as_of"],
            days=baseline["days"],
        )
        if (
            measured["dataset_sha256"]
            != baseline["timeframes"][timeframe]["dataset_sha256"]
        ):
            raise ValueError(
                "Revisões dos candles divergiram da baseline; recapture o histórico."
            )
        return frozen, rows

    def summary(self):
        baseline = self.latest()
        with self.memory.pool.connection() as c:
            rows = c.execute("""SELECT record_type,payload_json FROM project_records
                WHERE record_type IN ('historical_collection_status','historical_hypothesis_study')
                ORDER BY recorded_at DESC LIMIT 30""").fetchall()
        latest = {}
        for row in rows:
            latest.setdefault(row["record_type"], json.loads(row["payload_json"]))
        from .core import readiness

        blocker = readiness(
            baseline,
            as_of=datetime.now(timezone.utc),
            clock_id=baseline["clock_id"] if baseline else None,
        )
        return dict(
            baseline=baseline,
            blocker=blocker,
            status=latest.get("historical_collection_status"),
            research=latest.get("historical_hypothesis_study"),
        )
