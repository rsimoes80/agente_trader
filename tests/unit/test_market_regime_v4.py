import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from aurelia_fx.domain import Candle, DataQuality
from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.hypothesis_lab import regime_performance_matrix
from aurelia_fx.observer import MarketObserver
from aurelia_fx.regime import MarketRegimeEngine, RegimeConfig
from aurelia_fx.regime.strategy_metadata import StrategyMetadata
from aurelia_fx.replay import ReplayConfig, run_replay
from aurelia_fx.replay_data import ReplayDataset
from aurelia_fx.sessions import SessionEngine, SessionWindow
from aurelia_fx.trend import HierarchyConfig

START = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)


def candle(i, price, half=0.0002):
    return Candle(
        START + timedelta(minutes=i), price, price + half, price - half, price, 100, 0.2
    )


def range_bars(count=24):
    return [candle(i, 1.1000 + (0.0001 if i % 2 else -0.0001)) for i in range(count)]


def trend_bars(count=24):
    return [candle(i, 1.1 + i * 0.0002, 0.00012) for i in range(count)]


class RegimeTests(unittest.TestCase):
    def setUp(self):
        self.config = RegimeConfig(
            window=6,
            confirmation_bars=2,
            breakout_acceptance_bars=3,
            boundary_tests_min=2,
            range_lifetime_bars=60,
            breakout_lifetime_bars=12,
        )

    def feed(self, bars, engine=None):
        engine = engine or MarketRegimeEngine(self.config)
        states = []
        for i, b in enumerate(bars):
            states.append(
                engine.evaluate(
                    bars[: i + 1],
                    symbol="EURUSD",
                    timeframe="M1",
                    now=b.timestamp + timedelta(minutes=1),
                    snapshot_id=f"s{i}",
                )
            )
        return engine, states

    def test_unknown_is_not_range(self):
        _, states = self.feed(trend_bars(3))
        self.assertEqual(states[-1].regime, "UNKNOWN")
        self.assertIn("REGIME_HISTORY_INSUFFICIENT", states[-1].missing_data)

    def test_range_gate_reports_narrow_and_middle_area(self):
        metadata = StrategyMetadata(
            "range",
            "research",
            allowed_regimes=("RANGE",),
            prohibited_regimes=("TREND", "UNKNOWN", "TRANSITION"),
            location_requirements=("range_boundary",),
        )
        snapshot = SimpleNamespace(
            regime="RANGE",
            regime_subtype="ESTABLISHED",
            breakout_status="not_observed",
            regime_state={"features": {"range_width_acceptable": False}},
            market_location={"relative_location": "MIDDLE_AREA"},
        )
        self.assertEqual(metadata.evaluate(snapshot)["reason"], "RANGE_TOO_NARROW")
        snapshot.regime_state["features"]["range_width_acceptable"] = True
        self.assertEqual(
            metadata.evaluate(snapshot)["reason"], "RANGE_LOCATION_UNFAVORABLE"
        )

    def test_performance_does_not_merge_classifier_versions_or_promote_small_samples(
        self,
    ):
        rows = [
            {
                "decision_id": str(i),
                "regime": "TREND",
                "regime_model_version": version,
                "financial_result": {"result_in_r": 1.0},
            }
            for i, version in enumerate(("a", "b"))
        ]
        report = regime_performance_matrix(rows + rows, minimum_samples=2)
        self.assertEqual(len(report["matrix"]), 2)
        self.assertTrue(
            all(
                r["expectancy_r"] is None and r["sample_size"] == 1
                for r in report["matrix"]
            )
        )
        self.assertFalse(report["automatic_promotion"])

    def test_trend_both_directions_deterministic(self):
        bars = trend_bars()
        _, states = self.feed(bars)
        _, again = self.feed(bars)
        self.assertEqual(states, again)
        self.assertEqual(
            (states[-1].regime, states[-1].direction), ("TREND", "BULLISH")
        )
        down = [candle(i, 1.2 - i * 0.0002, 0.00012) for i in range(24)]
        self.assertEqual(self.feed(down)[1][-1].direction, "BEARISH")

    def test_range_boundaries_frozen_and_location(self):
        engine, states = self.feed(range_bars())
        established = [s for s in states if s.subtype == "ESTABLISHED"]
        self.assertTrue(established)
        first, last = established[0], states[-1]
        self.assertEqual(
            first.range_state["upper_boundary"], last.range_state["upper_boundary"]
        )
        self.assertEqual(first.range_state["range_id"], last.range_state["range_id"])
        location = engine.location(last, last.range_state["upper_boundary"])
        self.assertEqual(location.relative_location, "UPPER_AREA")
        self.assertEqual(location.distance_to_boundary, 0)

    def test_breakout_attempt_failure_and_acceptance(self):
        bars = range_bars(12)
        bars += [candle(12, 1.1008), candle(13, 1.1)]
        _, states = self.feed(bars)
        self.assertEqual(states[-2].subtype, "BREAKOUT_ATTEMPT")
        self.assertNotEqual(states[-2].regime, "TREND")
        self.assertEqual(states[-1].breakout["current_status"], "RETURNED_TO_RANGE")
        self.assertEqual(states[-1].transition["status"], "FAILED")
        bars = range_bars(12) + [
            candle(i, 1.1008 + (i - 12) * 0.0003) for i in range(12, 24)
        ]
        _, states = self.feed(bars)
        self.assertTrue(
            any(
                s.regime == "TRANSITION" and s.subtype == "RANGE_TO_TREND"
                for s in states
            )
        )
        self.assertEqual(states[-1].regime, "TREND")
        self.assertTrue(any(s.breakout_behavior == "CONFIRMED" for s in states))

    def test_trend_weakening_then_range(self):
        bars = trend_bars(12) + [
            candle(i, 1.1022 + (0.0001 if i % 2 else -0.0001)) for i in range(12, 32)
        ]
        _, states = self.feed(bars)
        self.assertTrue(any(s.regime == "TRANSITION" for s in states))
        self.assertEqual(states[-1].regime, "RANGE")

    def test_new_range_does_not_inherit_previous_breakout(self):
        bars = range_bars(12) + [
            candle(i, 1.1008 + (i - 12) * 0.0003) for i in range(12, 24)
        ]
        bars += [
            candle(i, 1.1041 + (0.0001 if i % 2 else -0.0001)) for i in range(24, 48)
        ]
        _, states = self.feed(bars)
        self.assertEqual(states[-1].regime, "RANGE")
        self.assertEqual(states[-1].breakout, {})

    def test_no_future_or_repeated_bar_updates(self):
        bars = range_bars(12)
        engine, states = self.feed(bars)
        before = states[-1]
        repeated = engine.evaluate(
            bars,
            symbol="EURUSD",
            timeframe="M1",
            now=bars[-1].timestamp + timedelta(minutes=1),
            snapshot_id="repeat",
        )
        self.assertEqual(before.features, repeated.features)
        self.assertEqual(before.range_state, repeated.range_state)
        future = MarketRegimeEngine(self.config).evaluate(
            bars,
            symbol="EURUSD",
            timeframe="M1",
            now=bars[-1].timestamp,
            snapshot_id="future",
        )
        self.assertEqual(future.regime, "UNKNOWN")
        self.assertIn("UNCLOSED_OR_FUTURE_CANDLE", future.missing_data)
        self.assertEqual(self.feed(bars[:8])[1], self.feed(bars)[1][:8])

    def test_timeframe_gap_invalid_and_stale_data(self):
        bars = trend_bars(12)
        for kwargs in (
            {"quality_valid": False},
            {"timeframe": "M5"},
        ):
            args = dict(
                symbol="EURUSD",
                timeframe="M1",
                now=bars[-1].timestamp + timedelta(minutes=1),
                snapshot_id="s",
            )
            args.update(kwargs)
            state = MarketRegimeEngine(self.config).evaluate(bars, **args)
            self.assertEqual(state.regime, "UNKNOWN")
        engine, _ = self.feed(bars)
        stale = engine.evaluate(
            bars,
            symbol="EURUSD",
            timeframe="M1",
            now=bars[-1].timestamp + timedelta(hours=1),
            snapshot_id="s",
        )
        self.assertIn("REGIME_DATA_STALE", stale.missing_data)
        gapped = bars[:6] + bars[7:]
        self.assertIn(
            "REGIME_HISTORY_GAP_OR_ORDER", self.feed(gapped)[1][-1].missing_data
        )

    def test_strategy_metadata_before_setup(self):
        trend = StrategyMetadata("trend", "1")
        ranged = StrategyMetadata(
            "range",
            "1",
            allowed_regimes=("RANGE",),
            prohibited_regimes=("TREND", "UNKNOWN", "TRANSITION"),
        )
        for regime in ("TREND", "RANGE", "UNKNOWN", "TRANSITION"):
            snapshot = SimpleNamespace(
                regime=regime,
                regime_subtype="ESTABLISHED",
                breakout_status="not_observed",
            )
            self.assertEqual(
                trend.evaluate(snapshot)["regime_match"], regime == "TREND"
            )
            self.assertEqual(
                ranged.evaluate(snapshot)["regime_match"], regime == "RANGE"
            )
        with self.assertRaises(ValueError):
            StrategyMetadata(
                "bad", "1", allowed_regimes=("UNKNOWN",), prohibited_regimes=()
            )

    def test_version_and_parameters_are_frozen(self):
        state = self.feed(range_bars())[1][-1]
        self.assertEqual(state.regime_model_version, "0.1.0-research")
        self.assertEqual(len(state.regime_config_hash), 64)
        cfg = replace(self.config, range_efficiency_max=0.2)
        self.assertNotEqual(
            MarketRegimeEngine(cfg).config_hash, state.regime_config_hash
        )

    def test_incompatible_regime_never_calls_setup_or_risk_and_persists(self):
        bars = range_bars(35)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            memory = ExperienceMemory(root / "offline.sqlite3")
            config = ReplayConfig(
                timeframe="M1",
                hierarchy=HierarchyConfig("M1", "M1", "M1", "M1"),
                regime_config=self.config,
                sessions=(SessionWindow("research", "UTC", time(0), time(0)),),
            )
            with (
                patch(
                    "aurelia_fx.replay.propose",
                    side_effect=AssertionError("ineligible setup evaluated"),
                ),
                patch(
                    "aurelia_fx.replay.assess_candidate",
                    side_effect=AssertionError("ineligible risk called"),
                ),
            ):
                report = run_replay(
                    ReplayDataset(
                        tuple(bars), "synthetic_range", "memory", "synthetic"
                    ),
                    config=config,
                    memory=memory,
                    output_dir=root / "reports",
                )
            self.assertIn("REGIME_MISMATCH", report["reasons"])
            with memory._connect() as db:
                row = db.execute(
                    "SELECT payload_json FROM experiences ORDER BY created_at_utc DESC LIMIT 1"
                ).fetchone()
                import json

                payload = json.loads(row["payload_json"])
                self.assertEqual(payload["regime"], "RANGE")
                self.assertFalse(payload["regime_match"])
                self.assertEqual(
                    payload["strategy_regime_compatibility"]["reason"],
                    "REGIME_MISMATCH",
                )
                self.assertEqual(
                    payload["regime_model_version"], self.config.regime_model_version
                )

    def test_regime_evaluated_before_trend_and_no_lower_timeframe_assumption(self):
        observer = MarketObserver(
            SessionEngine(()),
            hierarchy_config=HierarchyConfig("H1", "M30", "M5", "M1"),
            regime_config=self.config,
        )
        calls = []
        regime_read = observer.regimes.evaluate
        trend_read = observer.trends.evaluate

        def regime(*a, **kw):
            calls.append("regime")
            return regime_read(*a, **kw)

        def trend(*a, **kw):
            calls.append("trend")
            return trend_read(*a, **kw)

        bars = trend_bars(24)
        now = bars[-1].timestamp + timedelta(minutes=1)
        with (
            patch.object(observer.regimes, "evaluate", regime),
            patch.object(observer.trends, "evaluate", trend),
        ):
            snapshot = observer.observe(
                symbol="EURUSD",
                timeframe="M1",
                candles=bars,
                quality=DataQuality(True, latest_timestamp=bars[-1].timestamp),
                spread_pips=0.2,
                observed_at=now,
                histories_by_timeframe={"M1": bars},
            )
        self.assertEqual(calls[-1], "trend")
        self.assertEqual(snapshot.regime, "UNKNOWN")
        self.assertEqual(snapshot.regime_state["timeframe"], "M30")
        self.assertTrue(
            all(
                item["regime"] in {"UNKNOWN", "TREND"}
                for item in snapshot.evidence_set["items"]
            )
        )


if __name__ == "__main__":
    unittest.main()
