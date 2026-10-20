import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aurelia_fx.agent_strategy import FEATURES, attach_forecast, propose_pullback
from aurelia_fx.domain import Candle


class AgentStrategyTests(unittest.TestCase):
    def context(self):
        start = datetime(2026, 2, 2, 8, tzinfo=timezone.utc)
        history = [
            Candle(start + timedelta(minutes=5 * i), 1.1, 1.1003, 1.0997, 1.1, 100, 1)
            for i in range(64)
        ]
        history[-2] = Candle(history[-2].timestamp, 1.1004, 1.1005, 1.0996, 1.1, 100, 1)
        history[-1] = Candle(history[-1].timestamp, 1.1, 1.1010, 1.0999, 1.1008, 100, 1)
        daily = [
            Candle(
                start - timedelta(days=30 - i),
                1.1,
                1.102,
                1.099,
                1.1 + i * 0.00005,
                100,
                1,
            )
            for i in range(20)
        ]
        snapshot = SimpleNamespace(
            regime="UNKNOWN",
            session=("london",),
            context_trend=dict(direction="undefined"),
            macro_trend=dict(direction="bullish"),
            structure_trend=dict(direction="bullish"),
            invalidating_evidence=(),
            evidence_status="INSUFFICIENT",
            as_dict=lambda: dict(
                snapshot_id="synthetic", regime="UNKNOWN", session=["london"]
            ),
        )
        return snapshot, history, daily

    def test_research_can_label_a_pattern_without_authorizing_unknown_regime(self):
        snapshot, history, daily = self.context()
        setup, reason = propose_pullback(snapshot, history, daily_history=daily)
        self.assertIsNone(setup)
        self.assertEqual(reason, "REGIME_UNKNOWN")
        setup, reason = propose_pullback(
            snapshot, history, daily_history=daily, research=True
        )
        self.assertIsNone(reason)
        self.assertFalse(setup["production_eligible"])
        self.assertEqual(setup["features"]["regime_unknown"], 1)
        self.assertEqual(setup["features"]["h1_direction_known"], 0)
        features = attach_forecast(setup, dict(quantiles=[[1.1, 1.1008, 1.101]] * 12))
        self.assertEqual(set(features), set(FEATURES))

    def test_missing_daily_context_is_not_zero_filled(self):
        snapshot, history, _ = self.context()
        setup, reason = propose_pullback(snapshot, history, research=True)
        self.assertIsNone(setup)
        self.assertEqual(reason, "DAILY_CONTEXT_INSUFFICIENT")

    def test_invalidating_data_is_not_bypassed_in_research(self):
        snapshot, history, daily = self.context()
        snapshot.invalidating_evidence = ("data_invalid",)
        setup, reason = propose_pullback(
            snapshot, history, daily_history=daily, research=True
        )
        self.assertIsNone(setup)
        self.assertEqual(reason, "INVALIDATING_EVIDENCE")
