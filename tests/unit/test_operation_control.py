import json
import os
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.operation_control import OperationControl, validate_lot
from aurelia_fx.operator_session import OperatorSessions
from aurelia_fx.storage import database_url


class OperationInputTests(unittest.TestCase):
    def test_lot_validates_exact_broker_step_and_bounds(self):
        contract = dict(volume_min=0.01, volume_max=10, volume_step=0.01)
        self.assertEqual(validate_lot("0.10", contract), "0.1")
        for invalid in ("NaN", "Infinity", "-1", "0", "0.015", "11"):
            with self.subTest(lot=invalid), self.assertRaises(ValueError):
                validate_lot(invalid, contract)

    def test_login_cookie_is_http_only_and_revoked_on_logout(self):
        sessions = OperatorSessions("fixture-secret")
        with self.assertRaises(ValueError):
            sessions.login("wrong", "test")
        cookie = sessions.login("fixture-secret", "test")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertTrue(sessions.authenticated(cookie))
        sessions.logout(cookie)
        self.assertFalse(sessions.authenticated(cookie))

    def test_empty_configuration_fails_closed_and_login_is_rate_limited(self):
        sessions = OperatorSessions("")
        for _ in range(11):
            with self.assertRaises(ValueError):
                sessions.login("", "test")
        self.assertFalse(sessions.authenticated(""))


@unittest.skipUnless(
    os.environ.get("TIMESTRAL_TEST_POSTGRES") == "1", "PostgreSQL integration opt-in"
)
class OperationPostgresTests(unittest.TestCase):
    def test_worker_liveness_uses_database_receipt_not_windows_clock(self):
        from datetime import datetime,timezone,timedelta
        data=dict(worker_id='fixture',at=(datetime.now(timezone.utc)+timedelta(seconds=71)).isoformat())
        encoded,digest=ExperienceMemory._encode(data)
        self.c.execute("""INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('agent_worker_heartbeat','fixture',%s,%s,clock_timestamp())""",(encoded,digest))
        status=self.control.worker_status()
        self.assertTrue(status['available'])
        self.assertEqual(status['age_basis'],'postgres_received_at')
        self.c.execute("UPDATE project_records SET recorded_at=clock_timestamp()-interval '4 minutes'")
        self.assertFalse(self.control.worker_status()['available'])

    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        self.c = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.addCleanup(self.c.close)
        self.c.execute("BEGIN")
        self.addCleanup(self.c.execute, "ROLLBACK")
        schema = "operation_test_" + uuid4().hex
        self.c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        self.c.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema))
        )
        self.c.execute("""CREATE TABLE project_records(
            record_type TEXT,record_key TEXT,payload_json TEXT,payload_sha256 TEXT,
            recorded_at TIMESTAMPTZ DEFAULT now())""")
        memory = SimpleNamespace(
            pool=SimpleNamespace(connection=lambda: nullcontext(self.c)),
            _encode=ExperienceMemory._encode,
        )
        self.control = OperationControl(memory)

    def command(self, action, key=None, **values):
        return self.control.command(
            dict(action=action, **values), key or uuid4().hex, actor="test"
        )

    def test_start_is_idempotent_and_preserves_lot(self):
        key = uuid4().hex
        first = self.command("START", key, lot="0.01")
        self.assertEqual(first, self.command("START", key, lot="0.01"))
        self.assertEqual(
            first["session_id"], self.command("START", lot="0.01")["session_id"]
        )
        with self.assertRaises(ValueError):
            self.command("START", lot="0.02")
        with self.assertRaises(ValueError):
            self.command("START", key, lot="0.02")

    def test_cancel_and_resume_reject_old_worker_generation(self):
        first = self.command("START", lot="0.01")
        self.command("PAUSE")
        self.assertIsNone(self.control.publish(first["session_id"], state="TRAINING"))
        resumed = self.command("RESUME")
        self.assertEqual(resumed["generation"], 2)
        self.assertIsNone(
            self.control.publish(
                first["session_id"], expected_generation=1, state="TRAINING"
            )
        )
        self.assertIsNotNone(
            self.control.publish(
                first["session_id"], expected_generation=2, state="LOADING_HISTORY"
            )
        )
        self.command("STOP")
        self.assertIsNone(self.control.publish(first["session_id"], state="TRAINING"))

    def test_demo_allowed_real_rejected_and_persisted_command_audit(self):
        for mode in ("live", "real"):
            with self.assertRaises(ValueError):
                self.command("START", lot="0.01", mode=mode)
        first = self.command("START", lot="0.01",mode="demo")
        self.assertEqual(first['execution_profile'],'autonomous_demo')
        self.assertFalse(first["orders_enabled"])
        record = self.c.execute(
            "SELECT payload_json FROM project_records WHERE record_type='agent_operation_command'"
        ).fetchone()
        self.assertEqual(json.loads(record["payload_json"])["request"]["actor"], "test")
