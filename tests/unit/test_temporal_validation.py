from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.replay import ReplayConfig
from aurelia_fx.replay_data import ReplayDataset
from aurelia_fx.temporal_validation import run_temporal_validation, split_dataset
from .test_replay import scenario


class TemporalValidationTests(unittest.TestCase):
    def dataset(self):
        candle = scenario()[0]
        return ReplayDataset(tuple(replace(candle, timestamp=candle.timestamp + timedelta(minutes=5*i))
                                   for i in range(200)), "test", "synthetic-test-only", "fixture")

    def test_holdout_changes_do_not_change_earlier_partitions(self):
        dataset = self.dataset()
        first = split_dataset(dataset, warmup_bars=30)
        modified = replace(dataset, candles=dataset.candles[:-1] + (replace(dataset.candles[-1], high=2),))
        second = split_dataset(modified, warmup_bars=30)
        self.assertEqual(first["development"].sha256, second["development"].sha256)
        self.assertEqual(first["validation"].sha256, second["validation"].sha256)
        self.assertNotEqual(first["holdout"].sha256, second["holdout"].sha256)
        self.assertLess(first["development"].candles[-1].timestamp, first["validation"].candles[0].timestamp)
        self.assertLess(first["validation"].candles[-1].timestamp, first["holdout"].candles[0].timestamp)

    def test_default_validation_never_runs_holdout(self):
        dataset = self.dataset()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calls = []
            def fake_run(part, *, config, memory, output_dir, code_version):
                label = part.reference.split("#partition=")[1].split("#")[0]
                calls.append(label)
                return {"report_directory": str(output_dir / label), "run_id": label,
                        "execution": {"closed_trades": 0, "net_pnl": 0}}
            with patch("aurelia_fx.temporal_validation.run_replay", side_effect=fake_run):
                report = run_temporal_validation(dataset, config=ReplayConfig(),
                    memory=ExperienceMemory(root / "memory.sqlite3"), output_dir=root / "reports")
            self.assertEqual(calls, ["development", "validation"])
            self.assertNotIn("holdout", report["reports"])
            self.assertEqual(report["holdout_status"], "reserved_not_evaluated")
            self.assertTrue((Path(report["report_directory"]) / "plan.json").exists())

    def test_small_partitions_rejected_before_evaluation(self):
        dataset = replace(self.dataset(), candles=scenario())
        with self.assertRaises(ValueError):
            split_dataset(dataset, warmup_bars=30)


if __name__ == "__main__":
    unittest.main()
