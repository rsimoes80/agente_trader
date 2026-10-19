"""Startup lock ordering without touching a production database."""

import threading
import unittest
from contextlib import nullcontext
from types import SimpleNamespace

from aurelia_fx.postgres_memory import PostgresMemory


class Connection:
    def __init__(self):
        self.calls = []

    def transaction(self):
        return nullcontext()

    def execute(self, query, parameters=None):
        self.calls.append(query)
        row = (
            {"relation": "metadata"}
            if "to_regclass" in query
            else {"value": "4.1"}
            if "postgres_backend_revision" in query
            else {"value": "3"}
        )
        return SimpleNamespace(fetchone=lambda: row)


class PostgresStartupTests(unittest.TestCase):
    def memory(self):
        memory = object.__new__(PostgresMemory)
        connection = Connection()
        memory.pool = SimpleNamespace(connection=lambda: nullcontext(connection))
        memory._local = threading.local()
        return memory, connection

    def test_current_schema_skips_ddl_after_exclusive_startup_lock(self):
        memory, connection = self.memory()
        memory._initialize()
        self.assertIn("pg_advisory_xact_lock(70616003)", connection.calls[0])
        self.assertTrue(all("CREATE" not in query for query in connection.calls))

    def test_writes_take_shared_lock_before_any_journal_sql(self):
        memory, connection = self.memory()
        with memory._connect() as db:
            db.execute("SELECT 1")
        self.assertIn("pg_advisory_xact_lock_shared", connection.calls[0])
        self.assertEqual(connection.calls[-1], "SELECT 1")
