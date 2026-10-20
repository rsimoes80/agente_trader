import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aurelia_fx.domain import Candle
from aurelia_fx.forecasting.adapter import ModelUnavailable, TimestralAdapter
from aurelia_fx.forecasting.config import SDK_REVISION, TimestralConfig
from aurelia_fx.forecasting.core import build_predictions, evaluate, prepare

START = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)


def bars(count=100):
    return [
        Candle(
            START + timedelta(minutes=5 * i),
            1.1 + i * 1e-5,
            1.101 + i * 1e-5,
            1.099 + i * 1e-5,
            1.1 + i * 1e-5,
        )
        for i in range(count)
    ]


def output():
    return dict(
        model="fake-explicit-test",
        revision="test-revision",
        artifact_sha256="a" * 64,
        sdk_revision=SDK_REVISION,
        device="cpu",
        latency_ms=10,
        levels=[0.1, 0.5, 0.9],
        quantiles=[[1.1, 1.101, 1.102] for _ in range(12)],
    )


class TimestralCoreTests(unittest.TestCase):
    def setUp(self):
        self.config = TimestralConfig(enabled=True)
        self.rows = bars()
        self.as_of = self.rows[-1].timestamp + timedelta(minutes=5)

    def predictions(self):
        return build_predictions(
            self.rows,
            output(),
            self.config,
            scope="replay",
            source_id="test",
            regime="TREND",
            as_of=self.as_of,
        )

    def test_closed_candles_only_and_no_future_leak(self):
        rows = bars(105)
        first = prepare(rows, self.as_of, self.config)
        rows[-1] = Candle(rows[-1].timestamp, 10, 11, 9, 10)
        self.assertEqual(first, prepare(rows, self.as_of, self.config))
        self.assertEqual(first[-1], self.rows[-1])

    def test_three_horizons_are_endpoint_price_quantiles(self):
        values = self.predictions()
        self.assertEqual([p["horizon"] for p in values], [3, 6, 12])
        self.assertEqual(
            values[0]["target_time"],
            (self.rows[-1].timestamp + timedelta(minutes=15)).isoformat(),
        )
        self.assertAlmostEqual(
            values[0]["expected_return"], 1.101 / self.rows[-1].close - 1
        )
        self.assertEqual(values[0]["nominal_coverage"], 0.8)

    def test_missing_duplicate_naive_and_gaps(self):
        with self.assertRaises(ValueError):
            prepare(self.rows[:30], self.as_of, self.config)
        with self.assertRaises(ValueError):
            prepare(self.rows + [self.rows[-1]], self.as_of, self.config)
        with self.assertRaises(ValueError):
            prepare([{"timestamp": "2026-10-19T08:00:00"}], self.as_of, self.config)
        with self.assertRaises(ValueError):
            prepare(self.rows[:50] + self.rows[80:], self.as_of, self.config)
        broken = [c.as_dict() for c in self.rows]
        broken[-1]["close"] = None
        with self.assertRaises((ValueError, TypeError)):
            prepare(broken, self.as_of, self.config)

    def test_invalid_quantiles_rejected(self):
        value = output()
        value["quantiles"][0] = [2, 1, 3]
        with self.assertRaises(ValueError):
            build_predictions(
                self.rows,
                value,
                self.config,
                scope="live",
                source_id="x",
                regime="UNKNOWN",
                as_of=self.as_of,
            )

    def test_evaluation_cannot_access_unclosed_target(self):
        prediction = self.predictions()[0]
        target = Candle(
            datetime.fromisoformat(prediction["target_time"]), 1.1, 1.103, 1.099, 1.102
        )
        with self.assertRaises(ValueError):
            evaluate(prediction, target, observed_at=target.timestamp)
        result = evaluate(
            prediction, target, observed_at=target.timestamp + timedelta(minutes=5)
        )
        self.assertTrue(result["directional_hit"])
        self.assertTrue(result["interval_covered"])
        self.assertAlmostEqual(result["absolute_error"], 0.001)
        self.assertTrue(all(v >= 0 for v in result["pinball"].values()))

    def test_ids_idempotent_and_scope_isolated(self):
        self.assertEqual(self.predictions(), self.predictions())
        other = build_predictions(
            self.rows,
            output(),
            self.config,
            scope="live",
            source_id="test",
            regime="TREND",
            as_of=self.as_of,
        )
        self.assertNotEqual(
            self.predictions()[0]["prediction_id"], other[0]["prediction_id"]
        )

    def test_disabled_or_missing_model_safe(self):
        adapter = TimestralAdapter(TimestralConfig())
        with self.assertRaises(ModelUnavailable):
            adapter.forecast([1.1] * 64)
        self.assertIsNone(adapter.process)
        adapter = TimestralAdapter(
            replace(
                self.config,
                python=str(Path(tempfile.gettempdir()) / "missing-timestral-python"),
            )
        )
        with self.assertRaises(ModelUnavailable):
            adapter.forecast([1.1] * 64)

    def test_config_cannot_authorize_trading(self):
        with self.assertRaises(ValueError):
            TimestralConfig(mode="trade")
        with self.assertRaises(ValueError):
            TimestralConfig(timeframe="M1")
