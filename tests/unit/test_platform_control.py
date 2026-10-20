import unittest
from datetime import datetime, timedelta, timezone

from aurelia_fx.operator_auth import authorized
from aurelia_fx.platform_control import preflight

from .test_historical_context import baseline

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


class PlatformPreflightTests(unittest.TestCase):
    def observer(self):
        return dict(
            status="observing",
            checked_at=NOW.isoformat(),
            source_clock=dict(
                contract="mt5-utc-v1",
                normalized_to="UTC",
                clock_id="test-clock",
                verified_current=True,
                response_at_utc=NOW.isoformat(),
                tick_utc=NOW.isoformat(),
            ),
        )

    def test_ready_requires_fresh_source_history_and_disk(self):
        report = preflight(self.observer(), baseline(), disk_free=1024**3, now=NOW)
        self.assertTrue(report["ready"])
        self.assertFalse(report["orders_enabled"])
        self.assertFalse(report["external_llm_required"])
        self.assertFalse(
            preflight(self.observer(), None, disk_free=1024**3, now=NOW)["ready"]
        )
        self.assertFalse(
            preflight(self.observer(), baseline(), disk_free=1, now=NOW)["ready"]
        )

    def test_stale_or_unknown_tick_cannot_start_session(self):
        o = self.observer()
        o["source_clock"]["tick_utc"] = (NOW - timedelta(minutes=3)).isoformat()
        self.assertFalse(preflight(o, baseline(), disk_free=1024**3, now=NOW)["ready"])
        o = self.observer()
        o["status"] = "unavailable"
        self.assertFalse(preflight(o, baseline(), disk_free=1024**3, now=NOW)["ready"])

    def test_operator_auth_never_accepts_empty_configuration(self):
        self.assertFalse(authorized("", ""))
        self.assertFalse(authorized("token", ""))
        self.assertFalse(authorized("wrong", "configured"))
        self.assertTrue(authorized("configured", "configured"))
