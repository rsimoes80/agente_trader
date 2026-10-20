import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from aurelia_fx.agent_forecast_view import forecast_view


class ForecastViewTests(unittest.TestCase):
    def setUp(self):
        self.at = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
        self.context = [SimpleNamespace(timestamp=self.at, close=1.1)]
        self.output = dict(quantiles=[[1.09, 1.1, 1.11]] * 12)

    def view(self):
        return forecast_view(self.output, self.context, clock_id="fixture-clock",
                             configuration="frozen-config", generated_at=self.at + timedelta(minutes=5))

    def test_prediction_targets_closes_and_expires_before_next_analysis(self):
        view = self.view()
        self.assertEqual(view["reference_at"], (self.at + timedelta(minutes=5)).isoformat())
        self.assertEqual(view["points"][0]["at"], (self.at + timedelta(minutes=10)).isoformat())
        self.assertEqual(view["points"][-1]["at"], (self.at + timedelta(minutes=65)).isoformat())
        self.assertEqual(view["valid_until"], (self.at + timedelta(minutes=10)).isoformat())
        self.assertEqual(view["clock_id"], "fixture-clock")

    def test_nonfinite_or_unordered_quantiles_cannot_be_drawn(self):
        for invalid in ([1.11, 1.1, 1.09], [1.09, float("nan"), 1.11], [1, 2]):
            self.output["quantiles"][0] = invalid
            with self.assertRaises(ValueError): self.view()
