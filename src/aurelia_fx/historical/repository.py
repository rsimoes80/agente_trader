"""Reuse append-only project_records: no second candle store or database."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .core import VERSION, utc


class HistoricalRepository:
    def __init__(self, memory, symbol='EURUSD', *, profile=None):
        if not hasattr(memory, "pool"):
            raise ValueError("Historical archive requires PostgreSQL.")
        self.memory = memory
        from ..instruments import symbol_name
        self.symbol=symbol_name(symbol)
        if profile and profile.symbol!=self.symbol:raise ValueError('HISTORY_PROFILE_SYMBOL_MISMATCH')
        self.profile=profile

    def record_type(self, kind):
        # Legacy EURUSD readers must never see the newest baseline of another
        # instrument, even before all long-running services have been reloaded.
        base=kind if self.symbol=='EURUSD' else kind+':'+self.symbol
        return self.profile.record_type(base) if self.profile else base

    @staticmethod
    def prefix(clock_id, timeframe, symbol='EURUSD'):
        identity = hashlib.sha256(clock_id.encode()).hexdigest()[:24]
        from ..instruments import symbol_name
        return f"archive:{identity}:{symbol_name(symbol)}:{timeframe}:"

    def ingest(self, rows, *, clock, timeframe):
        prefix = self.prefix(clock["clock_id"], timeframe, self.symbol)
        values = []
        for row in rows:
            if row.get('symbol',self.symbol)!=self.symbol:raise ValueError('Candle pertence a outro ativo.')
            payload = {
                **row,
                "symbol": self.symbol,
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
        prefix = self.prefix(clock_id, timeframe, self.symbol)
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
                WHERE record_type=%s AND payload_json::jsonb ->> 'version'=%s
                AND COALESCE(payload_json::jsonb ->> 'symbol','EURUSD')=%s
                AND (%s::text IS NULL OR payload_json::jsonb ->> 'clock_id'=%s)
                AND (payload_json::jsonb ->> 'as_of')::timestamptz<=%s
                AND recorded_at<=COALESCE(%s::timestamptz,clock_timestamp())
                ORDER BY recorded_at DESC LIMIT 1""",
                (
                    self.record_type('historical_baseline'),VERSION,
                    self.symbol,
                    clock_id,
                    clock_id,
                    as_of or datetime.now(timezone.utc),
                    as_of,
                ),
            ).fetchall()
        if not rows:
            return None
        result={
            **json.loads(rows[0]["payload_json"]),
            "_recorded_at": rows[0]["recorded_at"].isoformat(),
        }
        if self.profile and result.get('profile_id')!=self.profile.fingerprint:
            raise ValueError('HISTORY_PROFILE_IDENTITY_MISMATCH')
        return result

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
            pip_size=baseline.get('price_unit',0.0001),
            profile=self.profile,
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
        if baseline.get('symbol','EURUSD')!=self.symbol:raise ValueError('Baseline pertence a outro ativo.')
        if self.profile and baseline.get('profile_id')!=self.profile.fingerprint:raise ValueError('HISTORY_PROFILE_IDENTITY_MISMATCH')
        self.memory.record_project_data(
            self.record_type("historical_baseline"), baseline["baseline_id"], baseline
        )

    def frozen_candles(
        self, baseline, *, timeframe="M5", record_type=None
    ):
        """Load exactly the immutable revision described by this baseline."""
        from .core import summarize
        if baseline.get('symbol','EURUSD')!=self.symbol:raise ValueError('Baseline pertence a outro ativo.')
        if self.profile and baseline.get('profile_id')!=self.profile.fingerprint:raise ValueError('HISTORY_PROFILE_IDENTITY_MISMATCH')
        record_type=record_type or self.record_type('historical_baseline')

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
            pip_size=baseline.get('price_unit',0.0001),
            profile=self.profile,
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
                WHERE record_type IN (%s,%s)
                AND COALESCE(payload_json::jsonb ->> 'symbol','EURUSD')=%s
                ORDER BY recorded_at DESC LIMIT 30""",(self.record_type('historical_collection_status'),self.record_type('historical_hypothesis_study'),self.symbol)).fetchall()
        latest = {}
        for row in rows:
            latest.setdefault(row["record_type"].split(':',1)[0], json.loads(row["payload_json"]))
        from .core import readiness

        blocker = readiness(
            baseline,
            as_of=datetime.now(timezone.utc),
            clock_id=baseline["clock_id"] if baseline else None,
            profile=self.profile,
        )
        return dict(
            baseline=baseline,
            blocker=blocker,
            status=latest.get("historical_collection_status"),
            research=latest.get("historical_hypothesis_study"),
        )
