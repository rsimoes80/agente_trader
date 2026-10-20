import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aurelia_fx.replay_data import load_csv
from aurelia_fx.temporal_validation import split_dataset
from run_replay import capture_mt5


class CaptureClockLineageTests(unittest.TestCase):
    def test_capture_hash_and_temporal_partitions_preserve_clock(self):
        clock = {"contract": "mt5-utc-v1", "normalized_to": "UTC"}
        rows = [
            dict(
                timestamp=f"2026-10-20T10:{i:02d}:00+00:00",
                open=1.1,
                high=1.2,
                low=1.0,
                close=1.1,
                volume=10,
                spread_pips=1,
                source_time_epoch=123,
                source_utc_offset_seconds=10800,
            )
            for i in range(20)
        ]
        history = dict(
            symbol="EURUSD",
            pip_size=0.0001,
            candles=rows,
            source_clock=clock,
            timestamp_semantics="utc_v1",
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch("mt5_provider.fetch_history", return_value=history):
                path = capture_mt5("M1", 20, Path(directory))
            dataset = load_csv(path, source="test")
            self.assertEqual(dataset.source_clock, clock)
            parts = split_dataset(dataset, warmup_bars=1)
            self.assertTrue(all(p.source_clock == clock for p in parts.values()))
            metadata_path = path.with_suffix(".metadata.json")
            metadata = json.loads(metadata_path.read_text())
            metadata["csv_sha256"] = "wrong"
            metadata_path.write_text(json.dumps(metadata))
            with self.assertRaises(ValueError):
                load_csv(path, source="test")
