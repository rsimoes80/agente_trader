"""PostgreSQL-only extension, using the application's existing connection pool."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .core import evaluate, utc

MIGRATIONS = Path(__file__).with_name("migrations")


def migrate(connection):
    sql = (MIGRATIONS / "001_timestral.up.sql").read_text(encoding="utf-8")
    digest = hashlib.sha256(sql.encode()).hexdigest()
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(70616021)")
        connection.execute("""CREATE TABLE IF NOT EXISTS timestral_schema_migrations (
            version INTEGER PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        row = connection.execute(
            "SELECT checksum FROM timestral_schema_migrations WHERE version=1"
        ).fetchone()
        if row:
            if row["checksum"] != digest:
                raise RuntimeError("Checksum da migration Timestral divergente.")
            return
        connection.execute(sql, prepare=False)
        connection.execute(
            "INSERT INTO timestral_schema_migrations(version,checksum) VALUES(1,%s)",
            (digest,),
        )


class ForecastRepository:
    def __init__(self, memory):
        if not hasattr(memory, "pool"):
            raise ValueError("Timestral exige o PostgreSQL oficial.")
        self.memory = memory

    def installed(self):
        with self.memory.pool.connection() as c:
            return (
                c.execute(
                    "SELECT to_regclass('timestral_predictions') AS name"
                ).fetchone()["name"]
                is not None
            )

    def migrate(self):
        with self.memory.pool.connection() as c:
            migrate(c)

    def has_batch(self, scope, source_id, reference, config_hash):
        with self.memory.pool.connection() as c:
            row = c.execute(
                """SELECT COUNT(*) AS count FROM timestral_predictions
                WHERE scope=%s AND source_id=%s AND reference_time=%s AND config_hash=%s""",
                (scope, source_id, reference, config_hash),
            ).fetchone()
        return row["count"] == 3

    def save(self, predictions, config):
        from psycopg.types.json import Jsonb

        if len(predictions) != 3:
            raise ValueError("O lote Timestral exige os três horizontes.")
        first = predictions[0]
        with self.memory.pool.connection() as c, c.transaction():
            c.execute(
                """INSERT INTO timestral_model_registry
                (model_key,model,revision,artifact_sha256,sdk_revision,status,config)
                VALUES(%s,%s,%s,%s,%s,'observe_only',%s) ON CONFLICT DO NOTHING""",
                (
                    *(
                        first[k]
                        for k in (
                            "model_key",
                            "model",
                            "revision",
                            "artifact_sha256",
                            "sdk_revision",
                        )
                    ),
                    Jsonb(config),
                ),
            )
            for p in predictions:
                c.execute(
                    """INSERT INTO timestral_predictions
                    (prediction_id,scope,source_id,symbol,timeframe,reference_time,as_of,target_time,horizon,
                     model_key,config_hash,median,expected_return,direction,latency_ms,regime,payload)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    (
                        *(
                            p[k]
                            for k in (
                                "prediction_id",
                                "scope",
                                "source_id",
                                "symbol",
                                "timeframe",
                                "reference_time",
                                "as_of",
                                "target_time",
                                "horizon",
                                "model_key",
                                "config_hash",
                                "median",
                                "expected_return",
                                "direction",
                                "latency_ms",
                                "regime",
                            )
                        ),
                        Jsonb(p),
                    ),
                )
                old = c.execute(
                    "SELECT payload FROM timestral_predictions WHERE prediction_id=%s",
                    (p["prediction_id"],),
                ).fetchone()
                if not old or old["payload"]["input_sha256"] != p["input_sha256"]:
                    raise ValueError(
                        "Colisão ou revisão de dados: previsão original preservada."
                    )

    def evaluate_available(self, rows, *, scope, source_id, observed_at):
        from psycopg.types.json import Jsonb

        mapping = {
            utc(r.timestamp if hasattr(r, "timestamp") else r["timestamp"]): r
            for r in rows
        }
        if not mapping:
            return 0
        with self.memory.pool.connection() as c, c.transaction():
            pending = c.execute(
                """SELECT p.payload,p.created_at FROM timestral_predictions p
                LEFT JOIN timestral_evaluations e ON e.prediction_id=p.prediction_id
                WHERE e.prediction_id IS NULL AND p.scope=%s AND p.source_id=%s AND p.target_time<=%s
                ORDER BY p.target_time LIMIT 2000""",
                (scope, source_id, max(mapping)),
            ).fetchall()
            count = 0
            for item in pending:
                p = item["payload"]
                target = utc(p["target_time"])
                if target not in mapping or target + timedelta(seconds=300) > utc(
                    observed_at
                ):
                    continue
                # Never score late live backfills whose outcome was already knowable at issuance.
                if scope == "live" and item["created_at"] >= target + timedelta(
                    seconds=300
                ):
                    continue
                result = evaluate(p, mapping[target], observed_at=observed_at)
                row = c.execute(
                    """INSERT INTO timestral_evaluations
                    (evaluation_id,prediction_id,observed_time,observed_at,actual_price,absolute_error,
                     return_error,directional_hit,interval_covered,payload)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING evaluation_id""",
                    (
                        *(
                            result[k]
                            for k in (
                                "evaluation_id",
                                "prediction_id",
                                "observed_time",
                                "observed_at",
                                "actual_price",
                                "absolute_error",
                                "return_error",
                                "directional_hit",
                                "interval_covered",
                            )
                        ),
                        Jsonb(result),
                    ),
                ).fetchone()
                count += bool(row)
        return count

    def optional_evidence(self, *, scope, source_id, as_of):
        """Read-only V4 port. Caller must explicitly choose source and cutoff."""
        if not self.installed():
            return []
        with self.memory.pool.connection() as c:
            rows = c.execute(
                """SELECT payload FROM timestral_predictions WHERE scope=%s AND source_id=%s
                AND as_of<=%s AND target_time+INTERVAL '5 minutes'>%s
                AND (scope='replay' OR created_at<=%s)
                ORDER BY reference_time DESC,horizon LIMIT 3""",
                (scope, source_id, as_of, as_of, as_of),
            ).fetchall()
        return [r["payload"] for r in rows]

    def summary(self, *, scope="live", source_id=None):
        if scope not in {"live", "replay"}:
            raise ValueError("Escopo Timestral inválido.")
        if not self.installed():
            return dict(
                installed=False,
                predictions=[],
                metrics=[],
                status={"status": "disabled"},
            )
        with self.memory.pool.connection() as c:
            latest = c.execute(
                """SELECT source_id,reference_time,model_key FROM timestral_predictions
                WHERE scope=%s AND (%s::text IS NULL OR source_id=%s)
                ORDER BY reference_time DESC,created_at DESC LIMIT 1""",
                (scope, source_id, source_id),
            ).fetchone()
            status = c.execute("""SELECT payload_json,recorded_at FROM project_records
                WHERE record_type='timestral_status' ORDER BY recorded_at DESC LIMIT 1""").fetchone()
            state = (
                json.loads(status["payload_json"]) if status else {"status": "disabled"}
            )
            if (
                status
                and (datetime.now(timezone.utc) - status["recorded_at"]).total_seconds()
                > 120
            ):
                state = {
                    **state,
                    "status": "offline",
                    "message": "Coletor sem atualização recente.",
                }
            if not latest:
                return dict(installed=True, predictions=[], metrics=[], status=state)
            predictions = c.execute(
                """SELECT payload FROM timestral_predictions
                WHERE scope=%s AND source_id=%s AND reference_time=%s AND model_key=%s
                ORDER BY horizon""",
                (
                    scope,
                    latest["source_id"],
                    latest["reference_time"],
                    latest["model_key"],
                ),
            ).fetchall()
            metrics = c.execute(
                """SELECT p.horizon,p.regime,COUNT(*) AS evaluated,
                AVG(e.absolute_error) AS mae,AVG(ABS(e.return_error)) AS return_mae,
                AVG(e.directional_hit::int)::double precision AS directional_accuracy,
                AVG(e.interval_covered::int)::double precision AS interval_coverage,
                AVG((e.payload->>'baseline_persistence_error')::double precision) AS baseline_mae,
                AVG((e.payload->>'baseline_drift_error')::double precision) AS drift_mae,
                AVG(p.latency_ms) AS latency_ms
                FROM timestral_evaluations e JOIN timestral_predictions p USING(prediction_id)
                WHERE p.scope=%s AND p.model_key=%s AND (%s::text IS NULL OR p.source_id=%s)
                GROUP BY p.horizon,p.regime ORDER BY p.horizon,p.regime""",
                (scope, latest["model_key"], source_id, source_id),
            ).fetchall()
        return dict(
            installed=True,
            scope=scope,
            source_id=latest["source_id"],
            predictions=[r["payload"] for r in predictions],
            metrics=metrics,
            status=state,
        )
