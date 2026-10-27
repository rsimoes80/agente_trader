import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from aurelia_fx.decision_engine import DecisionEngine, IntelligencePolicy
from aurelia_fx.historical.core import (
    TIMEFRAMES,
    VERSION,
    closed_rows,
    readiness,
    summarize,
)
from aurelia_fx.historical.research import study
from aurelia_fx.replay_data import market_open

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def rows(count=300, seconds=300):
    first = NOW - timedelta(seconds=count * seconds)
    return [
        dict(
            timestamp=(first + timedelta(seconds=i * seconds)).isoformat(),
            open=1.1,
            high=1.101,
            low=1.099,
            close=1.1 + (i % 3 - 1) * 0.0001,
            volume=10,
            spread_pips=1,
        )
        for i in range(count)
    ]


def baseline():
    return dict(
        version=VERSION,
        days=30,
        clock_id="test-clock",
        as_of=NOW.isoformat(),
        timeframes={tf: dict(ready=True) for tf in TIMEFRAMES},
    )


class HistoricalContextTests(unittest.TestCase):
    def test_flat_future_outcomes_are_not_filtered_by_hindsight(self):
        data = rows(1000)
        for row in data:
            row["open"] = 1.1
            row["close"] = 1.1001
        result = study(data, baseline_id="flat-outcome-fixture")
        validation = [
            r
            for r in result["results"]
            if r["phase"] == "validation" and r["horizon"] == 3
        ]
        self.assertTrue(all(r["samples"] > 30 for r in validation))
        self.assertTrue(all(r["directional_accuracy"] == 0 for r in validation))


    def test_collector_fetches_all_periods_and_checks_host_clock(self):
        from unittest.mock import patch

        from aurelia_fx.historical.collector import collect

        repo = MagicMock(); repo.symbol="EURUSD"; repo.profile=None
        repo.latest.return_value = None
        repo.candles.return_value = rows(100)
        repo.ingest.return_value = {"received": 100, "inserted": 100, "unchanged": 0}

        def fetch(symbol, tf, count, **kwargs):
            self.assertFalse(kwargs["include_current"])
            return dict(
                symbol="EURUSD",
                timeframe=tf,
                candles=rows(100),
                timestamp_semantics="utc_v1",
                source_clock=dict(
                    clock_id="test-clock",
                    contract="mt5-utc-v1",
                    normalized_to="UTC",
                    verified_current=True,
                    response_at_utc=NOW.isoformat(),
                    tick_utc=NOW.isoformat(),
                ),
            )

        adapter = MagicMock(side_effect=fetch)
        with patch(
            "aurelia_fx.historical.collector.summarize", return_value={"ready": True}
        ):
            result = collect(repo, adapter, now=NOW)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(adapter.call_count, len(TIMEFRAMES))
        self.assertGreater(adapter.call_args_list[0].args[2], 40000)
        repo.record_baseline.assert_called_once()

    def test_collector_rejects_stale_source_before_persistence(self):
        from aurelia_fx.historical.collector import collect
        from aurelia_fx.source_clock import SourceClockUnavailable

        repo = MagicMock(); repo.symbol="EURUSD"; repo.profile=None
        repo.latest.return_value = None
        data = dict(
            symbol="EURUSD",
            timeframe="M1",
            candles=[],
            timestamp_semantics="utc_v1",
            source_clock=dict(
                clock_id="test",
                contract="mt5-utc-v1",
                normalized_to="UTC",
                verified_current=True,
                response_at_utc=(NOW - timedelta(days=1)).isoformat(),
                tick_utc=(NOW - timedelta(days=1)).isoformat(),
            ),
        )
        with self.assertRaises(SourceClockUnavailable):
            collect(repo, lambda *a, **k: data, now=NOW)
        repo.ingest.assert_not_called()
        repo.record_baseline.assert_not_called()

    def test_incremental_capture_reuses_archive_instead_of_refetching_month(self):
        from unittest.mock import patch

        from aurelia_fx.historical.collector import collect

        repo = MagicMock(); repo.symbol="EURUSD"; repo.profile=None
        prior = baseline()
        for tf in TIMEFRAMES:
            prior["timeframes"][tf]["last"] = (NOW - timedelta(minutes=5)).isoformat()
        repo.latest.return_value = prior
        repo.candles.return_value = rows(100)
        repo.ingest.return_value = {}

        def fetch(symbol, tf, count, **kwargs):
            return dict(
                symbol="EURUSD",
                timeframe=tf,
                candles=rows(100),
                timestamp_semantics="utc_v1",
                source_clock=dict(
                    clock_id="test-clock",
                    contract="mt5-utc-v1",
                    normalized_to="UTC",
                    verified_current=True,
                    response_at_utc=NOW.isoformat(),
                    tick_utc=NOW.isoformat(),
                ),
            )

        adapter = MagicMock(side_effect=fetch)
        with patch(
            "aurelia_fx.historical.collector.summarize", return_value={"ready": True}
        ):
            collect(repo, adapter, now=NOW)
        self.assertTrue(all(call.args[2] < 1000 for call in adapter.call_args_list))

    def test_gate_requires_month_and_blocks_stale_future_and_wrong_source(self):
        self.assertEqual(
            readiness(None, as_of=NOW, clock_id="test-clock"),
            "HISTORY_BASELINE_REQUIRED",
        )
        b = baseline()
        self.assertIsNone(readiness(b, as_of=NOW, clock_id="test-clock"))
        self.assertEqual(
            readiness(b, as_of=NOW + timedelta(hours=7), clock_id="test-clock"),
            "HISTORY_BASELINE_STALE",
        )
        self.assertEqual(
            readiness(b, as_of=NOW - timedelta(seconds=1), clock_id="test-clock"),
            "HISTORY_BASELINE_FROM_FUTURE",
        )
        self.assertEqual(
            readiness(b, as_of=NOW, clock_id="other"), "HISTORY_SOURCE_MISMATCH"
        )
        b["days"] = 5
        self.assertEqual(
            readiness(b, as_of=NOW, clock_id="test-clock"), "HISTORY_BASELINE_REQUIRED"
        )

    def test_partial_timeframes_and_coverage_block_operations(self):
        b = baseline()
        b["timeframes"]["M1"]["ready"] = False
        self.assertEqual(
            readiness(b, as_of=NOW, clock_id="test-clock"),
            "HISTORY_COVERAGE_INSUFFICIENT",
        )
        del b["timeframes"]["M1"]
        self.assertEqual(
            readiness(b, as_of=NOW, clock_id="test-clock"), "HISTORY_BASELINE_REQUIRED"
        )

    def test_decision_engine_checks_history_before_technical_gates(self):
        engine = DecisionEngine(IntelligencePolicy())
        snapshot = SimpleNamespace(timestamp_utc=NOW.isoformat())
        self.assertEqual(
            engine.context_gate(snapshot, require_history=True),
            "HISTORY_BASELINE_REQUIRED",
        )
        self.assertEqual(
            engine.context_gate(
                snapshot,
                require_history=True,
                historical_context={"baseline": baseline(), "clock_id": "test-clock"},
            ),
            "STRATEGY_REGIME_METADATA_REQUIRED",
        )

    def test_closed_only_duplicate_invalid_and_no_implicit_sort(self):
        data = rows(100)
        data.append({**data[-1], "timestamp": NOW.isoformat(), "close": 99})
        selected = closed_rows(data, "M5", start=NOW - timedelta(days=30), as_of=NOW)
        self.assertEqual(len(selected), 100)
        with self.assertRaises(ValueError):
            closed_rows(data[::-1], "M5", start=NOW - timedelta(days=30), as_of=NOW)
        data = rows()
        data[-1]["close"] = -1
        with self.assertRaises(ValueError):
            closed_rows(data, "M5", start=NOW - timedelta(days=30), as_of=NOW)

    def test_month_statistics_and_sessions_use_closed_data_only(self):
        start = NOW - timedelta(days=30)
        data = [
            r
            for r in rows(30 * 288)
            if market_open(datetime.fromisoformat(r["timestamp"]))
        ]
        result = summarize(data, "M5", start=start, as_of=NOW)
        self.assertTrue(result["ready"], result["coverage"])
        self.assertAlmostEqual(result["statistics"]["mean_spread_pips"], 1)
        self.assertTrue(result["by_session"])
        self.assertTrue(result["by_utc_hour"])
        short = summarize(data[-100:], "M5", start=start, as_of=NOW)
        self.assertFalse(short["ready"])

    def test_statistics_do_not_relabel_future_as_available(self):
        data = rows(100)
        future = {
            **data[-1],
            "timestamp": NOW.isoformat(),
            "open": 10,
            "high": 11,
            "low": 9,
            "close": 10,
        }
        a = summarize(data, "M5", start=NOW - timedelta(days=30), as_of=NOW)
        b = summarize(data + [future], "M5", start=NOW - timedelta(days=30), as_of=NOW)
        self.assertEqual(a, b)

    def test_holdout_prices_cannot_change_study_results(self):
        data = rows(1000)
        a = study(data, baseline_id="test")
        modified = copy.deepcopy(data)
        for row in modified[800:]:
            row["close"] = 50
        b = study(modified, baseline_id="test")
        self.assertEqual(a["results"], b["results"])
        self.assertFalse(a["holdout_accessed"])
        self.assertFalse(a["automatic_promotion"])
        self.assertNotEqual(
            a["partitions"]["holdout"]["sha256"], b["partitions"]["holdout"]["sha256"]
        )

    def test_study_rejects_labels_across_partition_end_and_gap(self):
        data = rows(1000)
        a = study(data, baseline_id="test")
        for result in a["results"]:
            self.assertLessEqual(
                result["samples"],
                a["partitions"][result["phase"]]["bars"] // result["horizon"],
            )
        gapped = data[:300] + data[500:]
        b = study(gapped, baseline_id="test")
        self.assertTrue(all(not r["orders_enabled"] for r in b["results"]))
