import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from aurelia_fx.experience_memory import ExperienceMemory


class MemoryMigrationTests(unittest.TestCase):
    def test_version_two_adds_evidence_store_without_touching_old_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "memory.sqlite3"
            memory = ExperienceMemory(path)
            memory.record_snapshot(
                {
                    "snapshot_id": "old-v2",
                    "timestamp_utc": "2026-10-19T08:00:00+00:00",
                    "symbol": "EURUSD",
                    "timeframe": "M5",
                },
                session="london",
                regime="trend",
            )
            with closing(sqlite3.connect(path)) as db:
                original = db.execute(
                    "SELECT payload_json,payload_sha256 FROM market_snapshots"
                ).fetchone()
                db.execute("DROP TABLE market_intelligence")
                db.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
                db.commit()
            ExperienceMemory(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0],
                    "3",
                )
                self.assertEqual(
                    db.execute(
                        "SELECT payload_json,payload_sha256 FROM market_snapshots"
                    ).fetchone(),
                    original,
                )
                self.assertEqual(
                    db.execute("SELECT count(*) FROM market_intelligence").fetchone()[
                        0
                    ],
                    0,
                )

    def test_observation_transaction_rolls_back_all_related_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "memory.sqlite3"
            memory = ExperienceMemory(path)
            with self.assertRaises(RuntimeError):
                with memory.transaction():
                    memory.record_snapshot(
                        {
                            "snapshot_id": "rollback",
                            "timestamp_utc": "2026-10-19T08:00:00+00:00",
                            "symbol": "EURUSD",
                            "timeframe": "M5",
                        },
                        session="london",
                        regime="trend",
                    )
                    raise RuntimeError("simulated storage failure")
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    db.execute("SELECT count(*) FROM market_snapshots").fetchone()[0], 0
                )

    def test_version_one_is_migrated_without_rewriting_old_snapshots(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "memory.sqlite3"
            memory = ExperienceMemory(path)
            snapshot = {
                "snapshot_id": "original",
                "timestamp_utc": "2026-10-19T08:00:00+00:00",
                "symbol": "EURUSD",
                "timeframe": "M5",
            }
            memory.record_snapshot(snapshot, session="london", regime="trend")
            with closing(sqlite3.connect(path)) as db:
                original = db.execute(
                    "SELECT payload_json,payload_sha256 FROM market_snapshots"
                ).fetchone()
                db.execute("DROP TABLE simulated_execution_events")
                db.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
                db.commit()
            ExperienceMemory(path)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(
                    db.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()[0],
                    "3",
                )
                self.assertEqual(
                    db.execute(
                        "SELECT payload_json,payload_sha256 FROM market_snapshots"
                    ).fetchone(),
                    original,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT count(*) FROM simulated_execution_events"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    db.execute(
                        "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name='simulated_execution_events'"
                    ).fetchone()[0],
                    2,
                )


if __name__ == "__main__":
    unittest.main()
