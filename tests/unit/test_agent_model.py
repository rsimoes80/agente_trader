"""Synthetic fixtures only; these tests make no statement about market edge."""

import copy
import unittest
from datetime import datetime, timedelta, timezone

from aurelia_fx.agent_model import (
    fit_model,
    partition_samples,
    predict,
    probability_metrics,
)
from aurelia_fx.agent_strategy import FEATURES


def fixtures(count=200):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        dict(
            sample_id=f"synthetic-{i}",
            entry_at=(start + timedelta(minutes=10 * i)).isoformat(),
            exit_at=(start + timedelta(minutes=10 * i + 5)).isoformat(),
            net_pnl=1 if i % 2 else -1,
            features={
                key: float(i % 2) if key == "body_atr" else 0.0 for key in FEATURES
            },
        )
        for i in range(count)
    ]


class AgentModelTests(unittest.TestCase):
    def test_fit_uses_separate_development_calibration_and_no_input_mutation(self):
        samples = fixtures()
        original = copy.deepcopy(samples)
        model = fit_model(samples)
        self.assertEqual(samples, original)
        self.assertEqual(model["training_samples"], 160)
        self.assertEqual(model["calibration"]["samples"], 40)
        self.assertLess(
            predict(model, samples[0]["features"]),
            predict(model, samples[1]["features"]),
        )

    def test_missing_schema_is_rejected_instead_of_zero_filled(self):
        model = fit_model(fixtures())
        with self.assertRaises(ValueError):
            predict(model, {})
        model["spec_hash"] = "other-spec"
        with self.assertRaises(ValueError):
            predict(model, fixtures(1)[0]["features"])

    def test_insufficient_and_single_class_samples_do_not_create_model(self):
        with self.assertRaises(ValueError):
            fit_model(fixtures(20))
        samples = fixtures()
        for sample in samples:
            sample["net_pnl"] = 1
        with self.assertRaises(ValueError):
            fit_model(samples)

    def test_labels_crossing_phase_boundary_are_purged(self):
        samples = fixtures(10)
        first = samples[5]["entry_at"]
        samples[4]["exit_at"] = first
        second = samples[8]["entry_at"]
        result = partition_samples(samples, first, second)
        self.assertEqual(len(result["development"]), 4)
        self.assertEqual(len(result["validation"]), 3)
        self.assertEqual(len(result["final"]), 2)
        self.assertEqual(len(result["purged"]), 1)

    def test_metrics_separate_probability_error_from_financial_profit(self):
        model = fit_model(fixtures())
        metrics = probability_metrics(model, fixtures(40))
        self.assertEqual(metrics["samples"], 40)
        self.assertGreater(metrics["brier_improvement"], 0)
        self.assertNotIn("net_pnl", metrics)
