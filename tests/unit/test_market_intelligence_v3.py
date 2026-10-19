import unittest
from dataclasses import asdict, replace
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace

from aurelia_fx.decision_engine import DecisionEngine, IntelligencePolicy
from aurelia_fx.domain import Candle
from aurelia_fx.evidence import Evidence, EvidenceEngine
from aurelia_fx.expectations import ExpectationContract, ExpectedVsObservedEngine
from aurelia_fx.levels import SupportResistanceEngine
from aurelia_fx.market_intelligence import (
    MarketIntelligenceSession,
    observation_only_result,
)
from aurelia_fx.price_action import PriceActionReader
from aurelia_fx.replay_strategy import STRATEGY_METADATA
from aurelia_fx.sessions import SessionWindow
from aurelia_fx.trend import (
    ClosedBarAggregator,
    HierarchyConfig,
    TrendHierarchyEngine,
    timeframe_seconds,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
BULL = (10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17)
BEAR = tuple(30 - p for p in BULL)


def bars(prices=BULL, tf="M1", *, end=NOW):
    seconds = timeframe_seconds(tf)
    start = end - timedelta(seconds=len(prices) * seconds)
    return tuple(
        Candle(
            start + timedelta(seconds=i * seconds), p, p + 0.01, p - 0.01, p, 100, 0.2
        )
        for i, p in enumerate(prices)
    )


class TrendTests(unittest.TestCase):
    def test_complete_reversal_requires_intermediate_states(self):
        engine = TrendHierarchyEngine(
            HierarchyConfig("M1", "M1", "M1", "M1"), swing_window=1
        )
        source = list(bars())
        for index in range(1, len(source) + 1):
            previous = engine.classify("M1", tuple(source[:index]))
        trace = [previous.state]
        for index, price in enumerate(
            (14.7, 15.5, 14, 14.8, 13.2, 14.1, 12.5, 13.4, 11.9, 12.8)
        ):
            source.append(
                Candle(
                    NOW + timedelta(minutes=index),
                    price,
                    price + 0.01,
                    price - 0.01,
                    price,
                    100,
                    0.2,
                )
            )
            state = engine.classify("M1", tuple(source))
            self.assertFalse(
                previous.state == "BULL_CONFIRMED" and state.state == "BEAR_CONFIRMED"
            )
            trace.append(state.state)
            previous = state
        self.assertIn("TRANSITION", trace)
        self.assertIn("POTENTIAL_BEAR", trace)
        self.assertEqual(trace[-1], "BEAR_CONFIRMED")

    def test_range_inside_parent_trend_is_explicit(self):
        engine = TrendHierarchyEngine(
            HierarchyConfig("M15", "M15", "M5", "M1"), swing_window=1
        )
        history = {
            "M15": bars(tf="M15"),
            "M5": bars(tf="M5"),
            "M1": bars((15, 15.6, 15.1, 15.5, 15.2, 15.4, 15.3)),
        }
        engine.evaluate({tf: values[:-1] for tf, values in history.items()})
        result = engine.evaluate(history)
        self.assertEqual(result["states"]["execution"]["state"], "RANGE")
        self.assertEqual(
            result["states"]["execution"]["relationship_with_parent"],
            "RANGE_INSIDE_TREND",
        )

    def test_configurable_aggregation_never_exposes_partial_higher_bar(self):
        config = HierarchyConfig("M10", "M5", "M5", "M1")
        aggregator = ClosedBarAggregator(config)
        source = bars(tuple(range(10, 20)))
        for bar in source[:4]:
            history = aggregator.add(bar)
            self.assertEqual(history["M5"], ())
        history = aggregator.add(source[4])
        self.assertEqual(len(history["M5"]), 1)
        self.assertEqual(history["M10"], ())
        self.assertEqual(history["M5"][0].close, 14)
        self.assertEqual(history["M5"][0].volume, 500)
        frozen = history["M5"]
        aggregator.add(source[5])
        self.assertEqual(frozen, history["M5"])
        with self.assertRaises(ValueError):
            aggregator.add(source[5])

    def test_missing_component_prevents_higher_timeframe_bar(self):
        aggregator = ClosedBarAggregator(HierarchyConfig("M10", "M5", "M5", "M1"))
        source = bars(tuple(range(10, 20)))
        for bar in source[:2] + source[3:5]:
            history = aggregator.add(bar)
        self.assertFalse(history["M5"])

    def test_future_higher_timeframe_is_rejected(self):
        engine = TrendHierarchyEngine(
            HierarchyConfig("M15", "M15", "M5", "M1"), swing_window=1
        )
        with self.assertRaises(ValueError):
            engine.evaluate(
                {
                    "M15": bars(tf="M15", end=NOW + timedelta(minutes=15)),
                    "M5": bars(tf="M5"),
                    "M1": bars(),
                },
                as_of=NOW,
            )

    def test_bullish_bearish_and_partial_reversal_without_one_bar_flip(self):
        for prices, expected in ((BULL, "BULL_CONFIRMED"), (BEAR, "BEAR_CONFIRMED")):
            engine = TrendHierarchyEngine(
                HierarchyConfig("M1", "M1", "M1", "M1"), swing_window=1
            )
            source = bars(prices)
            for index in range(1, len(source) + 1):
                state = engine.classify("M1", source[:index])
            self.assertEqual(state.state, expected)
        engine = TrendHierarchyEngine(
            HierarchyConfig("M1", "M1", "M1", "M1"), swing_window=1
        )
        source = bars()
        for index in range(1, len(source) + 1):
            state = engine.classify("M1", source[:index])
        broken = state.last_confirmed_low["price"] - 0.1
        extended = source + (
            Candle(NOW, broken, broken + 0.01, broken - 0.01, broken, 100, 0.2),
        )
        result = engine.classify("M1", extended)
        self.assertEqual(result.state, "TRANSITION")
        self.assertEqual(result.reversal_status, "partial_reversal")
        self.assertNotEqual(result.state, "BEAR_CONFIRMED")
        # Reprocessing the same closed bar cannot advance the trend confirmation counter.
        self.assertEqual(engine.classify("M1", extended), result)

    def test_lower_timeframe_correction_preserves_parent_direction(self):
        child = (16, 15.8, 15.9, 15.6, 15.7, 15.4, 15.5, 15.2, 15.3, 15, 15.1)
        for parent_prices, child_prices, direction in (
            (BULL, child, "bullish"),
            (BEAR, tuple(30 - p for p in child), "bearish"),
        ):
            engine = TrendHierarchyEngine(
                HierarchyConfig("M15", "M15", "M5", "M1"), swing_window=1
            )
            history = {
                "M15": bars(parent_prices, "M15"),
                "M5": bars(parent_prices, "M5"),
                "M1": bars(child_prices, "M1"),
            }
            engine.evaluate({tf: values[:-1] for tf, values in history.items()})
            result = engine.evaluate(history)
            self.assertEqual(result["alignment"]["dominant_direction"], direction)
            self.assertEqual(
                result["states"]["execution"]["relationship_with_parent"],
                "CORRECTING_PARENT",
            )
            self.assertEqual(result["states"]["execution"]["parent_timeframe"], "M5")


class PriceAndLevelTests(unittest.TestCase):
    def test_contraction_and_overlap_are_measured(self):
        source = list(bars((10, 10.05, 10.1)))
        source[-1] = Candle(
            source[-1].timestamp, 10.05, 10.052, 10.049, 10.051, 100, 0.2
        )
        result = PriceActionReader().read(
            source, symbol="EURUSD", timeframe="M1", now=NOW, observation_id="pa"
        )
        self.assertEqual(result.expansion_state, "contracting")
        self.assertEqual(result.overlap_state, "overlapping")

    def test_measurements_and_expansion_are_observations(self):
        reader = PriceActionReader()
        source = list(bars((10, 10.2, 10.4)))
        source[-1] = Candle(source[-1].timestamp, 10, 12, 9, 11, 100, 0.2)
        result = reader.read(
            source, symbol="EURUSD", timeframe="M1", now=NOW, observation_id="pa"
        )
        feature = result.candle_sequence_features[-1]
        self.assertEqual(feature["body"], 1)
        self.assertEqual(feature["upper_wick"], 1)
        self.assertEqual(feature["lower_wick"], 1)
        self.assertAlmostEqual(feature["close_location"], 2 / 3)
        self.assertEqual(result.expansion_state, "expanding")
        self.assertNotIn("action", result.as_dict())

    def test_failed_breakout_and_no_follow_through_are_distinct(self):
        reader = PriceActionReader()
        for prices, expected in (
            ((10, 11, 10.8), "no_bullish_follow_through"),
            ((10, 11, 9.9), "failed_bullish_breakout"),
        ):
            result = reader.read(
                bars(prices),
                symbol="EURUSD",
                timeframe="M1",
                now=NOW,
                observation_id="pa",
            )
            self.assertEqual(result.failure_status, expected)
        result = reader.read(
            bars((10, 11, 11.2)),
            symbol="EURUSD",
            timeframe="M1",
            now=NOW,
            observation_id="pa",
        )
        self.assertEqual(result.momentum_behavior, "decelerating")

    def test_zone_provenance_role_change_retest_distance_and_expiry(self):
        source = list(bars((10, 12, 11, 13, 12.1, 14)))
        source[4] = Candle(source[4].timestamp, 12.1, 12.2, 11.99, 12.1, 100, 0.2)
        engine = SupportResistanceEngine(tolerance=0.02, swing_window=1, ttl_bars=100)
        levels = engine.evaluate({"M1": tuple(source)}, symbol="EURUSD", now=NOW)
        zone = next(
            z for z in levels if abs((z.lower_bound + z.upper_bound) / 2 - 12.01) < 1e-8
        )
        self.assertEqual(zone.role, "support")
        self.assertEqual(zone.breakout_status, "bullish")
        self.assertEqual(zone.retest_status, "observed")
        self.assertEqual(zone.timeframe, "M1")
        self.assertTrue(zone.origin)
        self.assertGreaterEqual(
            datetime.fromisoformat(zone.created_at_utc),
            source[2].timestamp + timedelta(minutes=1),
        )
        obstacle = replace(zone, role="resistance")
        context = engine.context((obstacle,), 11, target=14, side="long")
        self.assertAlmostEqual(context[0]["distance"], 0.99)
        self.assertTrue(context[0]["interferes_with_target"])
        self.assertEqual(len({z.level_id for z in levels}), len(levels))
        expired = engine.evaluate(
            {"M1": tuple(source)}, symbol="EURUSD", now=NOW + timedelta(days=1)
        )
        self.assertTrue(all(z.status == "expired" for z in expired))


def fact(
    identity, direction="bullish", group="structure", status="supportive", expired=False
):
    return Evidence(
        identity,
        NOW.isoformat(),
        "EURUSD",
        "M1",
        "trend",
        "test",
        "engineering.test",
        direction,
        identity,
        status,
        "descriptive",
        "contextual",
        (),
        (NOW + timedelta(minutes=-1 if expired else 1)).isoformat(),
        "fixture",
        group,
    )


class EvidenceTests(unittest.TestCase):
    def aggregate(self, items, **kwargs):
        return EvidenceEngine().aggregate(
            items,
            snapshot_id="s",
            symbol="EURUSD",
            now=NOW,
            valid_until=NOW + timedelta(minutes=1),
            **kwargs,
        )

    def test_redundancy_is_not_confluence_and_confirmation_is_not_trigger(self):
        result = self.aggregate((fact("HHHL"), fact("same_swings_again")))
        self.assertEqual(result.evidence_quality, "WEAK")
        self.assertEqual(result.independent_feature_groups, ("structure",))
        result = self.aggregate(
            (fact("HHHL"), fact("bar_sequence", group="bar_sequence"))
        )
        self.assertEqual(result.evidence_quality, "SUPPORTIVE")
        self.assertEqual(result.confirmation_status, "not_evaluated")
        self.assertEqual(result.trigger_status, "not_evaluated")
        self.assertNotIn("probability", asdict(result))

    def test_contradictions_expiry_and_invalidations_are_preserved(self):
        result = self.aggregate((fact("bull"), fact("bear", "bearish", "bar_sequence")))
        self.assertEqual(result.evidence_quality, "CONFLICTED")
        self.assertTrue(
            result.bullish_evidence and result.bearish_evidence and result.conflicts
        )
        invalid = self.aggregate(
            result.items
            + (fact("bad_data", "neutral", "data_quality", "invalidating"),)
        )
        self.assertEqual(invalid.evidence_quality, "INVALIDATED")
        self.assertEqual(
            self.aggregate((fact("old", expired=True),)).evidence_quality,
            "INSUFFICIENT",
        )
        self.assertEqual(self.aggregate(result.items), self.aggregate(result.items))

    def test_confirmed_expectation_without_trigger_is_not_authorized(self):
        contract = ExpectationContract(
            "e",
            "h",
            "EURUSD",
            "london",
            "long",
            ("retest",),
            ("stop",),
            NOW + timedelta(hours=1),
            "test",
            "1",
            created_at=NOW - timedelta(minutes=1),
            trigger_event="close_above",
        )
        result = ExpectedVsObservedEngine().evaluate(
            contract, {"retest": True}, now=NOW
        )
        self.assertEqual(result.status.value, "confirmed")
        self.assertEqual(DecisionEngine.trigger_gate(result), "WAITING_FOR_TRIGGER")
        result = ExpectedVsObservedEngine().evaluate(
            contract,
            {"retest": True, "close_above": True},
            now=NOW,
            evidence_set=self.aggregate(
                (fact("bad", "neutral", "data_quality", "invalidating"),)
            ).as_dict(),
        )
        self.assertEqual(result.status.value, "invalidated")

    def test_transition_is_no_trade_before_risk(self):
        snapshot = SimpleNamespace(
            regime="TREND",
            regime_subtype="BULL",
            breakout_status="not_observed",
            invalidating_evidence=(),
            trend_hierarchy={
                "states": {
                    "context": {"state": "TRANSITION"},
                    "structure": {"state": "BULL_CONFIRMED"},
                }
            },
        )
        self.assertEqual(
            DecisionEngine(IntelligencePolicy(), STRATEGY_METADATA).context_gate(
                snapshot
            ),
            "TREND_TRANSITION_WAIT",
        )

    def test_structural_obstacle_vetoes_a_target(self):
        snapshot = SimpleNamespace(
            regime="TREND",
            regime_subtype="BULL",
            breakout_status="not_observed",
            invalidating_evidence=(),
            trend_hierarchy={
                "states": {
                    "context": {"state": "BULL_CONFIRMED"},
                    "structure": {"state": "BULL_CONFIRMED"},
                }
            },
            trend_alignment={
                "transition_risk": "not_observed",
                "dominant_direction": "bullish",
            },
            evidence_status="SUPPORTIVE",
            market_structure={"last_close": 1.1},
            nearby_structural_levels=(
                {"role": "resistance", "lower_bound": 1.101, "upper_bound": 1.1012},
            ),
        )
        self.assertEqual(
            DecisionEngine(IntelligencePolicy(), STRATEGY_METADATA).context_gate(
                snapshot, side="long", target=1.103
            ),
            "TARGET_OBSTRUCTED_BY_STRUCTURAL_ZONE",
        )


class StreamingTests(unittest.TestCase):
    def test_old_indicator_candidate_remains_observation_and_stale_data_is_invalidating(
        self,
    ):
        session = MarketIntelligenceSession(
            symbol="EURUSD",
            hierarchy=HierarchyConfig("M1", "M1", "M1", "M1"),
            sessions=(SessionWindow("research", "UTC", time(0), time(0)),),
            max_spread_pips=2,
            pip_size=0.0001,
            swing_window=1,
        )
        rows = [bar.as_dict() for bar in bars()]
        snapshot = session.update(rows, spread_pips=0.2, observed_at=NOW)
        result = observation_only_result(
            {"signal": "BUY", "entry": 17, "confidence_pct": 90}, snapshot
        )
        self.assertEqual(result["signal"], "WAIT")
        self.assertNotIn("confidence_pct", result)
        self.assertNotIn("entry", result)
        stale = session.update(
            rows, spread_pips=0.2, observed_at=NOW + timedelta(hours=1)
        )
        self.assertTrue(stale.invalidating_evidence)


if __name__ == "__main__":
    unittest.main()
