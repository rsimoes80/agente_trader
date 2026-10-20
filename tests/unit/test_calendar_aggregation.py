import unittest
from datetime import datetime, timedelta, timezone

from aurelia_fx.broker_calendar import slot_tradable, unexpected_broker_gap
from aurelia_fx.calendar_aggregation import CalendarBarAggregator
from aurelia_fx.domain import Candle
from aurelia_fx.replay_data import unexpected_gap
from aurelia_fx.trend import HierarchyConfig


def bar(at, close=1.1):
    return Candle(at, 1.1, max(1.101, close), min(1.099, close), close, 100, 1)


class CalendarAggregationTests(unittest.TestCase):
    def test_documented_broker_friday_close_is_not_a_missing_price(self):
        friday = datetime(2026, 10, 23, 20, 50, tzinfo=timezone.utc)
        sunday = datetime(2026, 10, 25, 21, tzinfo=timezone.utc)
        self.assertFalse(unexpected_broker_gap(bar(friday), bar(sunday), 300))
        self.assertFalse(slot_tradable(friday + timedelta(minutes=5)))
        self.assertTrue(slot_tradable(sunday))

    def test_broker_calendar_still_rejects_a_missing_tradable_bar(self):
        monday = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
        self.assertTrue(
            unexpected_broker_gap(bar(monday), bar(monday + timedelta(minutes=10)), 300)
        )

    def test_weekend_short_bars_preserve_real_data_without_future_availability(self):
        aggregation = CalendarBarAggregator(HierarchyConfig("D1", "H4", "H1", "M5"))
        friday = datetime(2026, 10, 23, 16, tzinfo=timezone.utc)
        for i in range(60):
            aggregation.add(bar(friday + timedelta(minutes=5 * i)))
        self.assertEqual(len(aggregation.history["H4"]), 1)
        sunday = datetime(2026, 10, 25, 21, tzinfo=timezone.utc)
        aggregation.add(bar(sunday, 1.2))
        self.assertEqual(len(aggregation.history["H4"]), 2)
        self.assertEqual(
            aggregation.history["H4"][-1].timestamp, friday + timedelta(hours=4)
        )
        self.assertEqual(aggregation.history["H4"][-1].close, 1.1)
        for i in range(1, 36):
            aggregation.add(bar(sunday + timedelta(minutes=5 * i)))
        self.assertEqual(len(aggregation.history["H4"]), 3)
        self.assertFalse(
            any(
                unexpected_gap(a, b, 14400)
                for a, b in zip(
                    aggregation.history["H4"], aggregation.history["H4"][1:]
                )
            )
        )

    def test_missing_tradable_slot_does_not_become_a_complete_bar(self):
        aggregation = CalendarBarAggregator(HierarchyConfig("D1", "H4", "H1", "M5"))
        monday = datetime(2026, 10, 19, tzinfo=timezone.utc)
        for i in range(48):
            if i != 20:
                aggregation.add(bar(monday + timedelta(minutes=5 * i)))
        self.assertEqual(len(aggregation.history["H4"]), 0)

    def test_dst_sunday_open_uses_calendar_instead_of_fixed_offset(self):
        aggregation = CalendarBarAggregator(HierarchyConfig("D1", "H4", "H1", "M5"))
        sunday = datetime(2026, 11, 1, 22, tzinfo=timezone.utc)
        for i in range(23):
            aggregation.add(bar(sunday + timedelta(minutes=5 * i)))
        self.assertEqual(len(aggregation.history["H4"]), 0)
        aggregation.add(bar(sunday + timedelta(minutes=115)))
        self.assertEqual(len(aggregation.history["H4"]), 1)
        self.assertEqual(aggregation.history["H4"][0].volume, 2400)
