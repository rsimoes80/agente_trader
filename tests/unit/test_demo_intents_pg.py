"""Committed test schemas prove durability; no SDK imports or broker calls."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from aurelia_fx.demo_intents import DemoIntentJournal
from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.storage import database_url


@unittest.skipUnless(os.environ.get("TIMESTRAL_TEST_POSTGRES")=="1","PostgreSQL opt-in")
class DemoIntentTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool
        self.admin=psycopg.connect(database_url(),autocommit=True,row_factory=dict_row)
        self.addCleanup(self.admin.close)
        self.schema="demo_intent_test_"+uuid4().hex
        self.admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.drop_owned_schema)
        self.pool=ConnectionPool(database_url(),min_size=1,max_size=2,open=True,
            kwargs=dict(autocommit=True,row_factory=dict_row,options=f"-c search_path={self.schema}"))
        self.pool.wait(timeout=10);self.addCleanup(self.pool.close)
        with self.pool.connection() as c:
            c.execute("""CREATE TABLE project_records(record_type TEXT,record_key TEXT,
                payload_json TEXT,payload_sha256 TEXT,recorded_at TIMESTAMPTZ,
                PRIMARY KEY(record_type,record_key,payload_sha256))""")
        self.now=datetime.now(timezone.utc)
        self.memory=SimpleNamespace(pool=self.pool,_encode=ExperienceMemory._encode)
        self.journal=DemoIntentJournal(self.memory,now=lambda:self.now)
        self.client=uuid4().hex
        self.request=dict(action="fixture-only",symbol="EURUSD",volume=0.01,sl=1.09,tp=1.12)
        self.owner=dict(account_id="fixture-account",approval_id="fixture-approval",
                        model_id="fixture-model",session_id="fixture-session",clock_id="fixture-clock")

    def drop_owned_schema(self):
        from psycopg import sql
        # Generated schema only; never remove the production project's tables.
        assert self.schema.startswith("demo_intent_test_") and len(self.schema)==49
        self.admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_send_marker_survives_exception_and_is_visible_on_another_connection(self):
        with self.assertRaisesRegex(RuntimeError,"simulated crash"):
            with self.journal.locked() as scope:
                scope.prepare(self.client,self.request,self.owner)
                scope.begin_send(self.client)
                with self.pool.connection() as independent:
                    rows=independent.execute("SELECT payload_json FROM project_records").fetchall()
                    self.assertIn("SENDING",[json.loads(row["payload_json"])["status"] for row in rows])
                raise RuntimeError("simulated crash after durable marker")
        with self.journal.locked() as restored:
            self.assertEqual(restored.latest(self.client)["status"],"SENDING")
            with self.assertRaises(ValueError):restored.begin_send(self.client)
            restored.transition(self.client,"UNCERTAIN",evidence=dict(reason="SDK_TIMEOUT"))
            with self.assertRaises(ValueError):restored.prepare(uuid4().hex,self.request,self.owner)
            with self.assertRaises(ValueError):restored.transition(self.client,"REJECTED")

    def test_idempotency_frozen_owner_and_stale_prepared_request(self):
        with self.journal.locked() as scope:
            first=scope.prepare(self.client,self.request,self.owner)
            self.assertEqual(first,scope.prepare(self.client,self.request,self.owner))
            with self.assertRaises(ValueError):scope.prepare(self.client,{**self.request,"volume":1},self.owner)
            with self.assertRaises(ValueError):scope.prepare(self.client,self.request,{**self.owner,"model_id":"changed"})
            self.now+=timedelta(seconds=6)
            with self.assertRaises(ValueError):scope.begin_send(self.client)
            self.assertEqual(scope.latest(self.client)["status"],"CANCELLED")
            self.assertEqual(scope.pending(self.owner["account_id"]),[])

    def test_lock_is_exclusive_and_scope_cannot_be_reused_after_unlock(self):
        with self.journal.locked() as scope:
            with self.assertRaises(RuntimeError):
                with self.journal.locked():pass
        with self.assertRaises(RuntimeError):scope.latest(self.client)
        with self.journal.locked() as other:
            other.prepare(self.client,self.request,self.owner)

    def test_unprotected_position_can_only_be_closed_by_its_reconciled_ticket(self):
        with self.journal.locked() as scope:
            scope.prepare(self.client,self.request,self.owner);scope.begin_send(self.client)
            scope.transition(self.client,"UNPROTECTED",evidence=dict(position_tickets=[77]))
            close={**self.request,"position":77}
            with self.assertRaises(ValueError):scope.prepare(uuid4().hex,{**close,"position":88},self.owner,risk_reduction_for=self.client)
            close_id=uuid4().hex
            scope.prepare(close_id,close,self.owner,risk_reduction_for=self.client)
            scope.begin_send(close_id)
            scope.transition(close_id,"UNCERTAIN")
            with self.assertRaises(ValueError):scope.prepare(uuid4().hex,close,self.owner,risk_reduction_for=self.client)

    def test_logical_order_does_not_rewind_if_database_wall_clock_moves_back(self):
        with self.journal.locked() as scope:
            scope.prepare(self.client,self.request,self.owner);scope.begin_send(self.client)
            scope.connection.execute("""UPDATE project_records SET recorded_at=recorded_at-INTERVAL '1 day'
                WHERE payload_json::jsonb ->> 'status'='SENDING'""")
            self.assertEqual(scope.latest(self.client)["status"],"SENDING")
            self.assertEqual(scope.pending(self.owner["account_id"])[0]["status"],"SENDING")
