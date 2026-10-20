import os
import unittest
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.historical.repository import HistoricalRepository
from aurelia_fx.storage import database_url

from .test_historical_context import NOW, rows


@unittest.skipUnless(
    os.environ.get("TIMESTRAL_TEST_POSTGRES") == "1", "PostgreSQL integration opt-in"
)
class HistoricalPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        self.c = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.addCleanup(self.c.close)
        self.c.execute("BEGIN")
        self.addCleanup(self.c.execute, "ROLLBACK")
        schema = "history_test_" + uuid4().hex
        self.c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        self.c.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema))
        )
        self.c.execute("""CREATE TABLE project_records(record_type TEXT NOT NULL,record_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(record_type,record_key,payload_sha256))""")
        self.memory = SimpleNamespace(
            pool=SimpleNamespace(connection=lambda: nullcontext(self.c)),
            _encode=ExperienceMemory._encode,
        )
        self.repo = HistoricalRepository(self.memory)
        self.clock = dict(
            clock_id="test",
            broker="Test fixture",
            server="Test-only",
            contract="mt5-utc-v1",
        )

    def candles(self, known_by=None, clock="test"):
        return self.repo.candles(
            clock_id=clock,
            timeframe="M5",
            start=NOW - timedelta(days=30),
            as_of=NOW,
            known_by=known_by,
        )

    def test_idempotent_archive_and_source_isolation(self):
        first = self.repo.ingest(rows(100), clock=self.clock, timeframe="M5")
        again = self.repo.ingest(rows(100), clock=self.clock, timeframe="M5")
        self.assertEqual(first["inserted"], 100)
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(len(self.candles()), 100)
        self.assertEqual(self.candles(clock="other"), [])

    def test_revisions_preserve_original_and_known_by_cutoff(self):
        data = rows(100)
        self.repo.ingest(data, clock=self.clock, timeframe="M5")
        cutoff = self.c.execute("SELECT clock_timestamp() AS cutoff").fetchone()[
            "cutoff"
        ]
        revised = [{**data[-1], "close": 1.1005}]
        self.repo.ingest(revised, clock=self.clock, timeframe="M5")
        self.assertEqual(
            self.c.execute("SELECT COUNT(*) AS n FROM project_records").fetchone()["n"],
            101,
        )
        self.assertEqual(self.candles()[-1]["close"], 1.1005)
        self.assertEqual(self.candles(known_by=cutoff)[-1]["close"], data[-1]["close"])

    def test_baseline_cannot_be_seen_before_its_actual_ingestion(self):
        from .test_historical_context import baseline

        current = self.c.execute("SELECT clock_timestamp() AS current_time").fetchone()[
            "current_time"
        ]
        payload = baseline()
        payload["as_of"] = (current - timedelta(minutes=1)).isoformat()
        text, digest = self.memory._encode(payload)
        self.c.execute(
            """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('historical_baseline','test',%s,%s,clock_timestamp())""",
            (text, digest),
        )
        self.assertIsNone(self.repo.latest(as_of=current - timedelta(seconds=1)))
        self.assertIsNotNone(self.repo.latest(as_of=current + timedelta(seconds=1)))

    def test_invalid_json_cannot_partially_write_batch(self):
        data = rows(100)
        data[-1]["close"] = float("nan")
        with self.assertRaises(ValueError):
            self.repo.ingest(data, clock=self.clock, timeframe="M5")
        self.assertEqual(
            self.c.execute("SELECT COUNT(*) AS n FROM project_records").fetchone()["n"],
            0,
        )
