"""PostgreSQL journal using the same append-only contract as the local journal."""

from __future__ import annotations

import atexit
import re
import threading
from contextlib import contextmanager
from pathlib import Path

from .experience_memory import ExperienceMemory

JOURNAL_TABLES = (
    "market_snapshots",
    "decisions",
    "experiences",
    "hypothesis_events",
    "expectation_events",
    "experiment_artifacts",
    "simulated_execution_events",
    "market_intelligence",
)


class PostgresSession:
    """Translate the journal's small, controlled SQL dialect; values stay bound."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, parameters=None):
        from psycopg import Error

        query = query.replace("e.direction IS ?", "e.direction IS NOT DISTINCT FROM ?")
        query = re.sub(
            r"json_extract\(e.payload_json,'\$\.([a-z_]+)'\)",
            r"(e.payload_json::jsonb ->> '\1')",
            query,
        )
        try:
            return self.connection.execute(query.replace("?", "%s"), parameters)
        except Error as exc:
            raise RuntimeError(
                f"PostgreSQL journal operation failed (SQLSTATE {exc.sqlstate or 'connection'})."
            ) from None


class PostgresMemory(ExperienceMemory):
    def __init__(self, dsn: str):
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        self._local = threading.local()
        self.pool = ConnectionPool(
            dsn,
            min_size=1,
            max_size=4,
            open=True,
            timeout=15,
            kwargs={
                "row_factory": dict_row,
                "connect_timeout": 10,
                "keepalives": 1,
                "keepalives_idle": 15,
                "keepalives_interval": 5,
                "keepalives_count": 3,
                "tcp_user_timeout": 30000,
                "application_name": "agente_trader",
                "autocommit": True,
            },
        )
        try:
            self.pool.wait(timeout=15)
            self._initialize()
        except Exception:
            self.pool.close()
            raise
        atexit.register(self.close)

    def close(self):
        self.pool.close()

    @contextmanager
    def _connect(self):
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        with self.pool.connection() as connection:
            with connection.transaction():
                connection.execute("SELECT pg_advisory_xact_lock_shared(70616003)")
                yield PostgresSession(connection)

    def _initialize(self):
        with self.pool.connection() as connection, connection.transaction():
            db = PostgresSession(connection)
            # Serialize concurrent startup migrations without locking other databases.
            db.execute("SELECT pg_advisory_xact_lock(70616003)")
            if db.execute(
                "SELECT to_regclass('public.metadata') AS relation"
            ).fetchone()["relation"]:
                revision = db.execute(
                    "SELECT value FROM metadata WHERE key='postgres_backend_revision'"
                ).fetchone()
                version = db.execute(
                    "SELECT value FROM metadata WHERE key='schema_version'"
                ).fetchone()
                if (
                    revision
                    and revision["value"] == "4.1"
                    and version
                    and version["value"] == str(self.SCHEMA_VERSION)
                ):
                    return
            schema = (
                Path(__file__)
                .with_name("journal_schema.sql")
                .read_text(encoding="utf-8")
            )
            schema = schema.replace("result_in_r REAL", "result_in_r DOUBLE PRECISION")
            db.connection.execute(schema, prepare=False)
            db.execute("""CREATE TABLE IF NOT EXISTS project_records (
                record_type TEXT NOT NULL, record_key TEXT NOT NULL,
                payload_json TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY(record_type, record_key, payload_sha256))""")
            # Existing large deployments install this concurrently with
            # ensure_project_indexes.py before upgrading. New tables are empty.
            db.execute("""CREATE INDEX IF NOT EXISTS ix_project_records_type_recorded
                ON project_records(record_type, recorded_at DESC)""")
            db.execute(
                "INSERT INTO metadata(key,value) VALUES('schema_version',?) ON CONFLICT DO NOTHING",
                (str(self.SCHEMA_VERSION),),
            )
            version = db.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()["value"]
            if version != str(self.SCHEMA_VERSION):
                raise RuntimeError(f"PostgreSQL journal schema incompatible: {version}")
            db.execute("""CREATE OR REPLACE FUNCTION reject_journal_mutation() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'journal rows are append-only'; END $$""")
            for table in (*JOURNAL_TABLES, "project_records"):
                db.execute(f"""CREATE OR REPLACE TRIGGER immutable_{table}
                    BEFORE UPDATE OR DELETE OR TRUNCATE ON {table}
                    FOR EACH STATEMENT EXECUTE FUNCTION reject_journal_mutation()""")
            db.execute("""CREATE OR REPLACE VIEW market_regime_history AS
                SELECT snapshot_id,created_at_utc,symbol,timeframe,
                payload_json::jsonb ->> 'regime' AS regime,
                payload_json::jsonb ->> 'regime_subtype' AS regime_subtype,
                payload_json::jsonb ->> 'regime_model_version' AS regime_model_version,
                payload_json::jsonb ->> 'regime_config_hash' AS regime_config_hash,
                payload_json::jsonb -> 'regime_state' AS regime_state,
                payload_json::jsonb -> 'market_location' AS market_location
                FROM market_snapshots WHERE payload_json::jsonb ->> 'schema_version' = '4'""")
            db.execute("""CREATE OR REPLACE VIEW experience_regime_history AS
                SELECT experience_id,decision_id,created_at_utc,symbol,strategy_id,strategy_version,
                payload_json::jsonb ->> 'regime' AS regime,
                payload_json::jsonb ->> 'regime_model_version' AS regime_model_version,
                payload_json::jsonb ->> 'regime_match' AS regime_match,
                payload_json::jsonb -> 'strategy_regime_compatibility' AS strategy_regime_compatibility,
                payload_json::jsonb -> 'financial_result' AS financial_result
                FROM experiences WHERE jsonb_exists(payload_json::jsonb,'regime_model_version')""")
            db.execute(
                "INSERT INTO metadata(key,value) VALUES('postgres_backend_revision','4.1') ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value"
            )

    def record_project_data(self, record_type: str, record_key: str, payload: dict):
        text, digest = self._encode(payload)
        with self._connect() as db:
            db.execute(
                """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
                VALUES(?,?,?,?) ON CONFLICT DO NOTHING""",
                (record_type, record_key, text, digest),
            )

    def sync_knowledge(self, directory: Path):
        import json

        for name, field, key in (
            ("rules.json", "rules", "rule_id"),
            ("sources.json", "sources", "document"),
        ):
            payload = json.loads((directory / name).read_text(encoding="utf-8"))
            with self.transaction():
                for item in payload[field]:
                    self.record_project_data(field, item[key], item)
