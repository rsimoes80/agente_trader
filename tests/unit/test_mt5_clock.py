import tempfile
import unittest
from unittest.mock import patch
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aurelia_fx.mt5_clock import (
    ClockCalibrationPending,
    ClockUnavailable,
    MT5Clock,
    wall_to_utc,
)

BROKER = "TF Global Markets (Aust) Pty Ltd"
SERVER = "ThinkMarkets-Demo"
SUMMER = datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc)


class MT5ClockTests(unittest.TestCase):
    def test_transient_windows_replace_lock_is_retried(self):
        actual=os.replace
        calls=[]
        def replace(source,target):
            calls.append(1)
            if len(calls)<3:raise PermissionError('sharing violation')
            actual(source,target)
        with patch('aurelia_fx.mt5_clock.os.replace',side_effect=replace),patch('aurelia_fx.mt5_clock.time.sleep'):
            self.clock._save('fixture',{'mode':'utc'})
        self.assertEqual(len(calls),3)
        self.assertEqual(self.clock._load()['fixture']['mode'],'utc')

    def test_persistent_lock_preserves_cache_and_is_recoverable(self):
        self.clock._save('fixture',{'mode':'utc'})
        with patch('aurelia_fx.mt5_clock.os.replace',side_effect=PermissionError('locked')),patch('aurelia_fx.mt5_clock.time.sleep'):
            with self.assertRaises(ClockUnavailable):self.clock._save('fixture',{'mode':'broker_wall'})
        self.assertEqual(self.clock._load()['fixture']['mode'],'utc')
        self.assertEqual(list(self.path.parent.glob('*.tmp')),[])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "clock.json"
        self.clock = MT5Clock(self.path)

    def calibrate(self, now=SUMMER, offset=10800, broker=BROKER, server=SERVER):
        raw = int(now.timestamp()) + offset
        with self.assertRaises(ClockCalibrationPending):
            self.clock.resolve(broker, server, raw, now=now)
        return self.clock.resolve(
            broker, server, raw + 2, now=now + timedelta(seconds=2)
        )

    def test_three_hours_are_normalized_without_hardcoding_current_date(self):
        clock = self.calibrate()
        self.assertEqual(clock["mode"], "broker_wall")
        self.assertEqual(clock["offset_seconds"], 10800)
        self.assertTrue(clock["verified_current"])
        stamp, raw, offset = self.clock.normalize_bars(
            [{"time": int(SUMMER.timestamp()) + 10800}], clock, now=SUMMER
        )[0]
        self.assertEqual(stamp, SUMMER.isoformat())
        self.assertEqual(offset, 10800)

    def test_winter_two_hours_and_native_utc_are_supported(self):
        winter = datetime(2026, 1, 20, 12, tzinfo=timezone.utc)
        clock = self.calibrate(winter, 7200)
        self.assertEqual(clock["offset_seconds"], 7200)
        # Different native API/server identity: UTC must not be shifted again.
        native = self.calibrate(SUMMER, 0, server="ThinkMarkets-Live")
        self.assertEqual(native["mode"], "utc")
        self.assertEqual(native["offset_seconds"], 0)

    def test_historical_offsets_are_date_specific(self):
        winter = datetime(2026, 1, 20, 12, tzinfo=timezone.utc)
        summer = SUMMER
        clock = self.calibrate()
        bars = [
            {"time": int(winter.timestamp()) + 7200},
            {"time": int(summer.timestamp()) + 10800},
        ]
        normalized = self.clock.normalize_bars(bars, clock, now=summer)
        self.assertEqual([x[2] for x in normalized], [7200, 10800])
        self.assertEqual(
            [x[0] for x in normalized], [winter.isoformat(), summer.isoformat()]
        )

    def test_us_dst_uses_correct_offsets_on_march_and_november_mondays(self):
        for month, day, offset in [
            (3, 6, 7200),
            (3, 9, 10800),
            (10, 30, 10800),
            (11, 2, 7200),
        ]:
            utc = datetime(2026, month, day, 12, tzinfo=timezone.utc)
            self.assertEqual(wall_to_utc(int(utc.timestamp()) + offset), utc)

    def test_ambiguous_and_nonexistent_dst_wall_labels_are_rejected(self):
        for wall in [
            datetime(2026, 3, 8, 9, 30, tzinfo=timezone.utc),
            datetime(2026, 11, 1, 8, 30, tzinfo=timezone.utc),
        ]:
            with self.assertRaises(ClockUnavailable):
                wall_to_utc(int(wall.timestamp()))

    def test_unknown_broker_is_never_guessed_as_utc_plus_three(self):
        with self.assertRaises(ClockUnavailable):
            self.clock.resolve(
                "Other Broker",
                "Other-Demo",
                int(SUMMER.timestamp()) + 10800,
                now=SUMMER,
            )
        self.assertFalse(self.path.exists())

    def test_nonadvancing_quote_cannot_calibrate_even_if_it_looks_current(self):
        raw = int(SUMMER.timestamp()) + 10800
        for sec in [0, 0.2, 0.5, 1, 2, 5]:
            with self.assertRaises(ClockCalibrationPending):
                self.clock.resolve(
                    BROKER, SERVER, raw, now=SUMMER + timedelta(seconds=sec)
                )
        self.assertFalse(self.path.exists())

    def test_frequent_requests_do_not_starve_calibration(self):
        raw = int(SUMMER.timestamp()) + 10800
        for sec in [0, 0.2, 0.5]:
            with self.assertRaises(ClockCalibrationPending):
                self.clock.resolve(
                    BROKER, SERVER, raw, now=SUMMER + timedelta(seconds=sec)
                )
        self.assertTrue(
            self.clock.resolve(
                BROKER, SERVER, raw + 2, now=SUMMER + timedelta(seconds=2)
            )["verified_current"]
        )

    def test_restart_revalidates_saved_mode_and_keeps_same_identity(self):
        first = self.calibrate()
        restarted = MT5Clock(self.path)
        current = restarted.resolve(
            BROKER,
            SERVER,
            int(SUMMER.timestamp()) + 10804,
            now=SUMMER + timedelta(seconds=4),
        )
        self.assertEqual(first["clock_id"], current["clock_id"])
        self.assertTrue(current["verified_current"])

    def test_stale_cache_does_not_make_an_old_quote_fresh(self):
        self.calibrate()
        old = int(SUMMER.timestamp()) + 10802
        result = MT5Clock(self.path).resolve(
            BROKER, SERVER, old, now=SUMMER + timedelta(days=2)
        )
        self.assertFalse(result["verified_current"])
        self.assertEqual(result["status"], "cached_stale_quote")
        with self.assertRaises(ClockUnavailable):
            self.clock.resolve(BROKER, SERVER, old + 1, now=SUMMER + timedelta(days=2))

    def test_changed_server_cannot_reuse_old_calibration(self):
        self.calibrate()
        with self.assertRaises(ClockCalibrationPending):
            MT5Clock(self.path).resolve(
                BROKER,
                "ThinkMarkets-Other",
                int(SUMMER.timestamp()) + 10804,
                now=SUMMER + timedelta(seconds=4),
            )

    def test_corrupted_cache_requires_new_calibration(self):
        for text in ("not json", "[]", '{"contract":"mt5-utc-v1","sources":[]}'):
            self.path.write_text(text, encoding="utf-8")
            clock = MT5Clock(self.path)
            with self.assertRaises(ClockCalibrationPending):
                clock.resolve(
                    BROKER, SERVER, int(SUMMER.timestamp()) + 10800, now=SUMMER
                )

    def test_unexpected_clock_jump_and_future_bars_fail_closed(self):
        clock = self.calibrate()
        with self.assertRaises(ClockUnavailable):
            self.clock.resolve(
                BROKER, SERVER, int(SUMMER.timestamp()) + 10800 + 1800, now=SUMMER
            )
        for bars in [
            [{"time": int(SUMMER.timestamp()) + 10860}],
            [
                {"time": int(SUMMER.timestamp()) + 10800},
                {"time": int(SUMMER.timestamp()) + 10800},
            ],
        ]:
            with self.assertRaises(ClockUnavailable):
                self.clock.normalize_bars(bars, clock, now=SUMMER)
