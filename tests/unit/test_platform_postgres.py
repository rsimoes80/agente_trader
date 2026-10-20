import os
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.platform_control import ObservationController
from aurelia_fx.storage import database_url


@unittest.skipUnless(
    os.environ.get("TIMESTRAL_TEST_POSTGRES") == "1", "PostgreSQL integration opt-in"
)
class PlatformPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        self.c = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.addCleanup(self.c.close)
        self.c.execute("BEGIN")
        self.addCleanup(self.c.execute, "ROLLBACK")
        schema = "platform_test_" + uuid4().hex
        self.c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        self.c.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema))
        )
        self.c.execute("""CREATE TABLE project_records(record_type TEXT NOT NULL,record_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY(record_type,record_key,payload_sha256))""")
        memory = SimpleNamespace(
            pool=SimpleNamespace(connection=lambda: nullcontext(self.c)),
            _encode=ExperienceMemory._encode,
        )
        self.healthy = True
        self.controller = ObservationController(
            memory, lambda: dict(ready=self.healthy, orders_enabled=False)
        )

    def command(self, action, key=None, **extra):
        return self.controller.command(
            dict(action=action, actor="test", reason="Test fixture", **extra),
            key or uuid4().hex,
            origin="test",
        )

    def test_double_start_same_or_different_key_has_one_session(self):
        key = uuid4().hex
        a = self.command("START", key)
        b = self.command("START", key)
        c = self.command("START")
        self.assertEqual(a, b)
        self.assertEqual(a["session_id"], c["session_id"])
        self.assertEqual(
            self.c.execute(
                "SELECT COUNT(*) AS n FROM project_records WHERE record_type='observation_session_event'"
            ).fetchone()["n"],
            2,
        )
        with self.assertRaises(ValueError):
            self.command("PAUSE", key)

    def test_pause_resume_stop_and_emergency_latch(self):
        self.command("START")
        self.command("PAUSE")
        self.assertIsNone(self.controller.observation_reference())
        self.command("RESUME")
        self.assertIsNotNone(self.controller.observation_reference())
        self.command("EMERGENCY_STOP")
        with self.assertRaises(ValueError):
            self.command("START")
        with self.assertRaises(ValueError):
            self.command("RESUME")
        self.command("RESET")
        self.assertEqual(self.controller.status()["state"], "STOPPED")
        self.command("START")
        self.command("STOP")
        self.assertIsNone(self.controller.observation_reference())

    def test_preconditions_and_live_mode_are_fail_closed(self):
        self.healthy = False
        self.assertEqual(self.command("START")["state"], "ERROR")
        with self.assertRaises(ValueError):
            self.command("START", mode="live")
        self.assertIsNone(self.controller.observation_reference())

    def test_restart_requires_explicit_resume_and_failures_pause(self):
        started = self.command("START")
        new = ObservationController(self.controller.memory, self.controller.check)
        new.recover()
        self.assertEqual(new.status()["state"], "RECOVERY_REQUIRED")
        self.assertIsNone(new.observation_reference())
        response = new.command(
            dict(action="RESUME", actor="test", reason="Review after restart"),
            uuid4().hex,
            origin="test",
        )
        self.assertEqual(response["session_id"], started["session_id"])
        new.pause_on_failure("TEST_SOURCE_LOST")
        self.assertEqual(new.status()["state"], "PAUSED_BY_DATA")
        self.assertIsNone(new.observation_reference())

    def test_session_does_not_claim_prior_observations(self):
        self.command("START")
        old = datetime.now(timezone.utc) - timedelta(days=1)
        self.assertIsNone(self.controller.observation_reference(old))
