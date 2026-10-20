"""Opt-in PostgreSQL tests: DDL/data live only in a transaction-rolled-back schema."""

import os
import unittest
from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from aurelia_fx.forecasting.repository import MIGRATIONS, ForecastRepository, migrate
from aurelia_fx.storage import database_url

from . import test_timestral_core as fixtures


@unittest.skipUnless(
    os.environ.get("TIMESTRAL_TEST_POSTGRES") == "1", "PostgreSQL integration opt-in"
)
class TimestralPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        self.connection = psycopg.connect(
            database_url(), autocommit=True, row_factory=dict_row
        )
        self.addCleanup(self.connection.close)
        self.connection.execute("BEGIN")
        self.addCleanup(self.connection.execute, "ROLLBACK")
        schema = "timestral_test_" + uuid4().hex
        self.connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
        )
        self.connection.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema))
        )
        self.memory = SimpleNamespace(
            pool=SimpleNamespace(connection=lambda: nullcontext(self.connection))
        )
        self.repo = ForecastRepository(self.memory)
        self.repo.migrate()
        fixture = fixtures.TimestralCoreTests()
        fixture.setUp()
        self.predictions = fixture.predictions()

    def test_migration_idempotence_and_reversible_when_empty(self):
        self.repo.migrate()
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) AS n FROM timestral_schema_migrations"
            ).fetchone()["n"],
            1,
        )
        self.connection.execute(
            (MIGRATIONS / "001_timestral.down.sql").read_text(), prepare=False
        )
        self.assertFalse(self.repo.installed())
        migrate(self.connection)
        self.assertTrue(self.repo.installed())

    def test_migration_checksum_detects_drift(self):
        self.connection.execute(
            "UPDATE timestral_schema_migrations SET checksum='changed-test-only'"
        )
        with self.assertRaisesRegex(RuntimeError, "Checksum"):
            self.repo.migrate()

    def test_prediction_recovery_idempotence_and_immutable(self):
        self.repo.save(self.predictions, {})
        self.repo.save(self.predictions, {})
        self.assertTrue(
            self.repo.has_batch(
                "replay",
                "test",
                self.predictions[0]["reference_time"],
                self.predictions[0]["config_hash"],
            )
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) AS n FROM timestral_predictions"
            ).fetchone()["n"],
            3,
        )
        import psycopg

        with self.assertRaises(psycopg.Error), self.connection.transaction():
            self.connection.execute("UPDATE timestral_predictions SET median=2")
        with self.assertRaises(psycopg.Error), self.connection.transaction():
            self.connection.execute(
                (MIGRATIONS / "001_timestral.down.sql").read_text(), prepare=False
            )

    def test_transaction_rolls_back_entire_batch(self):
        broken = [dict(p) for p in self.predictions]
        broken[1]["median"] = -1
        import psycopg

        with self.assertRaises(psycopg.Error):
            self.repo.save(broken, {})
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) AS n FROM timestral_predictions"
            ).fetchone()["n"],
            0,
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT count(*) AS n FROM timestral_model_registry"
            ).fetchone()["n"],
            0,
        )

    def test_evaluation_saved_once_after_target_closes(self):
        from aurelia_fx.domain import Candle
        from aurelia_fx.forecasting.core import utc

        self.repo.save(self.predictions, {})
        stamp = utc(self.predictions[0]["target_time"])
        bar = Candle(stamp, 1.1, 1.103, 1.099, 1.102)
        self.assertEqual(
            self.repo.evaluate_available(
                [bar], scope="replay", source_id="test", observed_at=stamp
            ),
            0,
        )

        self.assertEqual(
            self.repo.evaluate_available(
                [bar],
                scope="replay",
                source_id="test",
                observed_at=stamp + timedelta(minutes=5),
            ),
            1,
        )
        self.assertEqual(
            self.repo.evaluate_available(
                [bar],
                scope="replay",
                source_id="test",
                observed_at=stamp + timedelta(minutes=5),
            ),
            0,
        )

    @unittest.skipUnless(
        os.environ.get("TIMESTRAL_TEST_MODEL") == "1", "Real model opt-in"
    )
    def test_real_model_and_postgres(self):
        from dataclasses import replace

        from aurelia_fx.forecasting.adapter import TimestralAdapter
        from aurelia_fx.forecasting.config import load_config
        from aurelia_fx.forecasting.service import ForecastService

        rows = fixtures.bars()
        config = replace(load_config(), enabled=True)
        engine = TimestralAdapter(config)
        try:
            service = ForecastService(config, self.repo, engine)
            result = service.observe(
                rows,
                as_of=rows[-1].timestamp + timedelta(minutes=5),
                scope="replay",
                source_id="real-model-integration-test",
            )
            self.assertEqual(result["status"], "observing", result)
            self.assertEqual(len(result["predictions"]), 3)
            self.assertEqual(
                self.connection.execute(
                    "SELECT COUNT(*) AS n FROM timestral_predictions"
                ).fetchone()["n"],
                3,
            )
        finally:
            engine.close()

    def test_collision_preserves_original_and_v4_cutoff(self):
        from aurelia_fx.forecasting.core import utc

        self.repo.save(self.predictions, {})
        broken = [dict(p) for p in self.predictions]
        broken[0]["input_sha256"] = "revised"
        with self.assertRaises(ValueError):
            self.repo.save(broken, {})
        as_of = utc(self.predictions[0]["as_of"])
        self.assertEqual(
            self.repo.optional_evidence(
                scope="replay", source_id="test", as_of=as_of - timedelta(seconds=1)
            ),
            [],
        )
        self.assertEqual(
            len(
                self.repo.optional_evidence(
                    scope="replay", source_id="test", as_of=as_of
                )
            ),
            3,
        )
