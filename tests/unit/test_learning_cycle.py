import unittest
from datetime import datetime, timedelta, timezone

from aurelia_fx.expectations import (
    CandidateHypothesis,
    ExpectationContract,
    ExpectationStatus,
    ExpectedVsObservedEngine,
)
from aurelia_fx.hypothesis_lab import ExperimentPlan, check_experiment


class LearningCycleTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.hypothesis = CandidateHypothesis(
            "h1", "Pullback holds", "retest holds", ("break below swing",)
        )
        self.contract = ExpectationContract(
            "e1",
            "h1",
            "EURUSD",
            "london",
            "long",
            ("retest", "bullish_close"),
            ("break_below_swing",),
            self.now + timedelta(hours=1),
            "pullback",
            "0.1",
            alert_events=("momentum_fades",),
            created_at=self.now,
        )

    def test_confirmation_is_never_execution_authorization(self):
        result = ExpectedVsObservedEngine().evaluate(
            self.contract, {"retest": True, "bullish_close": True}, now=self.now
        )
        self.assertEqual(result.status, ExpectationStatus.CONFIRMED)
        self.assertFalse(result.execution_eligible)

    def test_invalidation_and_expiry(self):
        engine = ExpectedVsObservedEngine()
        invalidated = engine.evaluate(
            self.contract, {"break_below_swing": True}, now=self.now
        )
        expired = engine.evaluate(self.contract, {}, now=self.now + timedelta(hours=1))
        self.assertEqual(invalidated.status, ExpectationStatus.INVALIDATED)
        self.assertEqual(expired.status, ExpectationStatus.EXPIRED)

    def test_experiment_requires_holdout_cost_and_lookahead_review(self):
        plan = ExperimentPlan(
            "bars.csv",
            "baseline-v1",
            "expectancy",
            ">0",
            "holdout.csv",
            True,
            True,
            1,
            feature_dependence_reviewed=True,
            timeframe_lineage_recorded=True,
        )
        self.assertEqual(check_experiment(self.hypothesis, plan), ())
        incomplete = ExperimentPlan(
            "bars.csv", "baseline-v1", "expectancy", ">0", "", False, False, 1
        )
        self.assertIn(
            "UNTOUCHED_HOLDOUT_MISSING", check_experiment(self.hypothesis, incomplete)
        )


if __name__ == "__main__":
    unittest.main()
