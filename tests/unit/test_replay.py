"""Synthetic bars deliberately exercise causality and persistence, not performance."""

from dataclasses import replace
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json
import sqlite3
import tempfile
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.replay import ReplayConfig, run_replay
from aurelia_fx.replay_data import ReplayDataset, load_csv
from aurelia_fx.sessions import SessionWindow


def scenario(*, spread=0.2, invalidate=False):
    start = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
    bars = []
    for i in range(31):
        price = 1.1 + (i // 4) * .0001 + (0, .0003, .0006, .0002)[i % 4]
        bars.append(Candle(start + timedelta(minutes=5 * i), price, price + .00004,
                           price - .00004, price, 100, spread))
    price = bars[-1].close
    bars.append(Candle(start + timedelta(minutes=155), price, price + .00002,
                       1.099 if invalidate else price - .0002, price - .00005, 100, spread))
    bars.append(Candle(start + timedelta(minutes=160), price, price + .0003,
                       price - .00001, price + .00025, 100, spread))
    return tuple(bars)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "memory.sqlite3"
        self.memory = ExperienceMemory(self.db)
        self.config = ReplayConfig(swing_window=1)

    def tearDown(self):
        self.temp.cleanup()

    def run_scenario(self, bars=None, config=None):
        return run_replay(ReplayDataset(bars or scenario(), "test-synthetic", "synthetic-test-only", "synthetic-fixture"),
            config=config or self.config, memory=self.memory, output_dir=self.root / "reports", code_version="test")

    def decisions(self, report):
        return [json.loads(line) for line in (Path(report["report_directory"]) / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_full_cycle_persists_across_restart_and_reruns_are_equivalent(self):
        first = self.run_scenario()
        self.assertEqual(first["actions"].get("HYPOTHETICAL_SIGNAL"), 1)
        self.memory = ExperienceMemory(self.db)
        second = self.run_scenario()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["decision_digest"], second["decision_digest"])
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM decisions").fetchone()[0], first["bars"] * 2)
            self.assertEqual(db.execute("SELECT count(*) FROM experiences").fetchone()[0], first["bars"] * 2)
            self.assertIsNone(db.execute("SELECT max(result_in_r) FROM experiences").fetchone()[0])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM decisions")
        self.assertTrue((Path(first["report_directory"]) / "report.html").exists())

    def test_future_changes_do_not_change_past_decisions(self):
        first = self.decisions(self.run_scenario())
        changed = list(scenario())
        changed[-1] = replace(changed[-1], high=1.5, close=1.4)
        second = self.decisions(self.run_scenario(tuple(changed)))
        def semantics(rows):
            return [{k: v for k, v in row.items() if k not in {"run_id", "decision_id", "snapshot_id", "hypothesis_id"}}
                    for row in rows]
        self.assertEqual(semantics(first[:-1]), semantics(second[:-1]))

    def test_confirmed_hypothesis_can_be_vetoed_by_risk(self):
        report = self.run_scenario(scenario(spread=5))
        last = self.decisions(report)[-1]
        self.assertEqual(last["action"], "NO_TRADE")
        self.assertEqual(last["reason_code"], "RISK_VETO")
        self.assertIn("SPREAD_LIMIT", last["risk"]["reasons"])

    def test_invalidation_prevents_later_confirmation(self):
        report = self.run_scenario(scenario(invalidate=True))
        rows = self.decisions(report)
        self.assertEqual(rows[-2]["reason_code"], "EXPECTATION_INVALIDATED")
        self.assertNotIn("HYPOTHETICAL_SIGNAL", report["actions"])

    def test_missing_bar_cancels_hypothesis_and_restarts_warmup(self):
        bars = list(scenario())
        bars[-1] = replace(bars[-1], timestamp=bars[-1].timestamp + timedelta(minutes=5))
        rows = self.decisions(self.run_scenario(tuple(bars)))
        self.assertEqual(rows[-1]["reason_code"], "INVALID_MARKET_DATA")
        self.assertEqual(rows[-1]["action"], "NO_TRADE")

    def test_trigger_at_session_close_cannot_authorize_entry(self):
        config = replace(self.config, sessions=(SessionWindow("research", "UTC", time(8), time(10, 45)),))
        report = self.run_scenario(config=config)
        rows = self.decisions(report)
        self.assertEqual(rows[-1]["reason_code"], "SESSION_NOT_AUTHORIZED")
        self.assertNotIn("HYPOTHETICAL_SIGNAL", report["actions"])

    def test_expiry_and_no_session_are_valid_no_trade_results(self):
        report = self.run_scenario(config=replace(self.config, lifetime_bars=1))
        self.assertIn("EXPECTATION_EXPIRED", report["reasons"])
        weekend = tuple(replace(c, timestamp=c.timestamp + timedelta(days=5)) for c in scenario())
        report = self.run_scenario(weekend)
        self.assertEqual(report["reasons"], {"SESSION_NOT_AUTHORIZED": len(weekend)})

    def test_csv_rejects_naive_timestamps_and_duplicate_data(self):
        path = self.root / "invalid.csv"
        path.write_text("timestamp,open,high,low,close\n2026-01-01T08:00:00,1,2,1,2\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_csv(path, source="test")
        line = "2026-01-01T08:00:00+00:00,1,2,1,2\n"
        path.write_text("timestamp,open,high,low,close\n" + line + line, encoding="utf-8")
        with self.assertRaises(ValueError):
            load_csv(path, source="test")

    def test_journal_failure_aborts_and_records_failed_run(self):
        with patch.object(self.memory, "record_experience", side_effect=sqlite3.OperationalError("disk unavailable")):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_scenario()
        with closing(sqlite3.connect(self.db)) as db:
            statuses = [row[0] for row in db.execute("SELECT status FROM experiment_artifacts")]
        self.assertEqual(statuses, ["started", "failed"])
        self.assertFalse(list((self.root / "reports").glob("*/report.html")))


if __name__ == "__main__":
    unittest.main()
