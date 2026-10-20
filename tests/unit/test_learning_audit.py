import copy
import unittest

from aurelia_fx.learning_audit import assess


def row():
    return dict(
        symbol="EURUSD",
        strategy_id="fixture",
        strategy_version="4-test",
        config_hash="fixture",
        frozen_context=dict(
            regime="RANGE",
            regime_model_version="test",
            evidence_state="SUPPORTIVE",
            trade_direction_class="RANGE",
        ),
        payload_json=dict(
            status="closed",
            event_id="test-closed",
            entry_at="2026-10-20T08:00:00+00:00",
            observed_at="2026-10-20T08:05:00+00:00",
            side="long",
            financial_result=dict(
                net_pnl=1,
                result_in_r=0.1,
                initial_risk=10,
                spread_cost=0.1,
                slippage_cost=0.1,
                commission=0.1,
            ),
        ),
    )


class LearningAuditTests(unittest.TestCase):
    def test_no_trade_is_never_a_losing_training_example(self):
        report = assess([], observations=10000)
        self.assertEqual(report["eligible_samples"], 0)
        self.assertEqual(report["no_trade_observations"], 10000)
        self.assertFalse(report["training_started"])

    def test_complete_frozen_sample_is_eligible_but_never_promoted(self):
        report = assess([row()], observations=10)
        self.assertEqual(report["eligible_samples"], 1)
        self.assertFalse(report["automatic_promotion"])
        self.assertIn(
            "APPROVED_V4_TO_LEARNER_FEATURE_SCHEMA_REQUIRED", report["blockers"]
        )

    def test_incomplete_costs_context_or_outcomes_are_rejected(self):
        for change, expected in [
            (
                lambda r: r["payload_json"].update(status="censored"),
                "OUTCOME_NOT_CLOSED",
            ),
            (
                lambda r: r["payload_json"]["financial_result"].pop("commission"),
                "OUTCOME_OR_COSTS_MISSING",
            ),
            (lambda r: r.update(frozen_context={}), "FROZEN_V4_CONTEXT_MISSING"),
            (
                lambda r: r["payload_json"].update(
                    observed_at="2026-10-20T07:00:00+00:00"
                ),
                "OUTCOME_TIME_INVALID",
            ),
        ]:
            r = row()
            change(r)
            report = assess([r], observations=10)
            self.assertEqual(report["eligible_samples"], 0)
            self.assertEqual(report["excluded"][expected], 1)

    def test_replays_are_deduplicated_and_strategy_versions_separated(self):
        a = row()
        b = copy.deepcopy(a)
        b["payload_json"]["event_id"] = "another-replay"
        c = copy.deepcopy(a)
        c["strategy_version"] = "other-version"
        report = assess([a, b, c], observations=1)
        self.assertEqual(report["eligible_samples"], 2)
        self.assertEqual(report["excluded"]["DUPLICATE_REPLAY_SAMPLE"], 1)
        self.assertEqual(len(report["cohorts"]), 2)
