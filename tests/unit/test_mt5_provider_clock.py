import importlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
provider = importlib.import_module("mt5_provider")

NOW = datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc)


class FakeSDK:
    ACCOUNT_TRADE_MODE_DEMO = 0

    def __init__(self):
        self.available = True
        self.history_available = True
        self.shutdown_count = 0
        self.tick = SimpleNamespace(
            time=int(NOW.timestamp()) + 10800, bid=1.1, ask=1.1001, last=1.1
        )
        self.rows = np.array(
            [
                (
                    int((NOW.replace(minute=0) - timedelta(minutes=5 * i)).timestamp())
                    + 10800,
                    1.1,
                    1.1002,
                    1.0998,
                    1.1,
                    10,
                    10,
                )
                for i in reversed(range(102))
            ],
            dtype=[
                ("time", "i8"),
                ("open", "f8"),
                ("high", "f8"),
                ("low", "f8"),
                ("close", "f8"),
                ("tick_volume", "i8"),
                ("spread", "i8"),
            ],
        )

    def initialize(self, **kwargs):
        return self.available

    def shutdown(self):
        self.shutdown_count += 1

    def last_error(self):
        return (-1, "fake terminal unavailable")

    def terminal_info(self):
        return SimpleNamespace(connected=True, name="MT5")

    def account_info(self):
        return SimpleNamespace(
            company="TF Global Markets (Aust) Pty Ltd",
            server="ThinkMarkets-Demo",
            currency="USD",
            trade_mode=0,
        )

    def symbols_get(self):
        return [SimpleNamespace(name="EURUSD")]

    def symbol_info(self, symbol):
        return SimpleNamespace(visible=True, point=0.00001, digits=5)

    def symbol_select(self, *_):
        return True

    def symbol_info_tick(self, *_):
        return self.tick

    def copy_rates_from_pos(self, symbol, tf, position, count):
        if not self.history_available:
            return None
        rows = self.rows[:-position] if position else self.rows
        return rows[-count:]


class ProviderClockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        from src.aurelia_fx.mt5_clock import MT5Clock

        self.clock = MT5Clock(Path(self.temp.name) / "clock.json")
        # Seed a previously verified source, then verify again at the request instant.
        try:
            self.clock.resolve(
                "TF Global Markets (Aust) Pty Ltd",
                "ThinkMarkets-Demo",
                int(NOW.timestamp()) + 10798,
                now=NOW - timedelta(seconds=2),
            )
        except RuntimeError:
            pass
        self.clock.resolve(
            "TF Global Markets (Aust) Pty Ltd",
            "ThinkMarkets-Demo",
            int(NOW.timestamp()) + 10800,
            now=NOW,
        )
        real = self.clock
        adapter = SimpleNamespace(
            resolve=lambda *args: real.resolve(*args, now=NOW),
            normalize_bars=lambda *args: real.normalize_bars(*args, now=NOW),
        )
        self.sdk = FakeSDK()
        p = patch.object(provider, "mt5", self.sdk)
        p.start()
        self.addCleanup(p.stop)
        p = patch.object(provider, "_CLOCK", adapter)
        p.start()
        self.addCleanup(p.stop)

    def test_provider_preserves_raw_time_and_returns_real_utc(self):
        data = provider.fetch_history("EUR/USD", "M5", 100, include_current=True)
        self.assertEqual(data["candles"][-1]["timestamp"], "2026-10-20T12:00:00+00:00")
        self.assertEqual(data["quote"]["time"], NOW.isoformat())
        self.assertEqual(data["source_clock"]["offset_seconds"], 10800)
        self.assertEqual(data["timestamp_semantics"], "utc_v1")
        self.assertEqual(data["candles"][-1]["source_utc_offset_seconds"], 10800)
        self.assertEqual(self.sdk.shutdown_count, 1)

    def test_closed_capture_excludes_current_candle_after_conversion(self):
        data = provider.fetch_history("EUR/USD", "M5", 100, include_current=False)
        self.assertEqual(data["candles"][-1]["timestamp"], "2026-10-20T11:55:00+00:00")

    def test_terminal_closed_then_open_reconnects_on_next_request(self):
        self.sdk.available = False
        with self.assertRaises(RuntimeError):
            provider.fetch_history("EUR/USD", "M5", 100)
        self.sdk.available = True
        self.assertEqual(
            len(provider.fetch_history("EUR/USD", "M5", 100)["candles"]), 100
        )
        self.assertEqual(self.sdk.shutdown_count, 2)

    def test_history_loading_error_does_not_poison_next_request(self):
        self.sdk.history_available = False
        with self.assertRaises(RuntimeError):
            provider.fetch_history("EUR/USD", "M5", 100)
        self.sdk.history_available = True
        self.assertEqual(
            len(provider.fetch_history("EUR/USD", "M5", 100)["candles"]), 100
        )
        self.assertEqual(self.sdk.shutdown_count, 2)
