"""Synthetic quote fixtures; no broker orders and no claim of market advantage."""

import unittest
from datetime import datetime, timedelta, timezone

from aurelia_fx.agent_paper import PaperAccount
from aurelia_fx.domain import Candidate


class PaperAccountTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 1, 5, 10, tzinfo=timezone.utc)
        self.contract = dict(contract_size=100000, currency_profit="USD")
        self.account = PaperAccount("fixture", "0.01", self.contract, "model", "clock")
        self.setup = dict(
            candidate=Candidate(
                "long",
                1.1,
                1.098,
                1.105,
                self.start + timedelta(minutes=5),
                ("fixture",),
            ),
            signal_at=self.start.isoformat(),
            production_eligible=True,
            snapshot=dict(session=["london"],regime="TREND",
                          macro_trend=dict(direction="bullish",state="BULL_CONFIRMED"),
                          context_trend=dict(direction="bullish",state="BULL_CONFIRMED")),
        )

    def quote(self, seconds=0, bid=1.1, ask=1.1001):
        return dict(
            bid=bid,
            ask=ask,
            at=self.start.isoformat(),
            observed_at=(self.start + timedelta(seconds=seconds)).isoformat(),
        )

    def open(self, account=None, seconds=3):
        return (account or self.account).open(
            self.setup, {}, 0.8, self.quote(seconds), active_sessions=("london",)
        )

    def test_entry_uses_observed_ask_and_observation_time(self):
        self.assertTrue(self.open()["approved"])
        p = self.account.data["position"]
        self.assertAlmostEqual(p["entry"], 1.10012)
        self.assertEqual(p["entry_at"], self.quote(3)["observed_at"])
        self.assertEqual(p["units"], 1000)

    def test_close_quote_costs_and_checkpoint_recovery(self):
        self.open()
        restored = PaperAccount(
            "fixture",
            "0.01",
            self.contract,
            "model",
            "clock",
            checkpoint=self.account.snapshot(),
        )
        restored.mark(self.quote(8, bid=1.1051, ask=1.1052))
        event = restored.events[-1]
        self.assertEqual(event["status"], "closed")
        self.assertEqual(event["reason"], "TARGET_OBSERVED")
        self.assertAlmostEqual(event["net_pnl"], 4.89)
        self.assertFalse(event["learning_eligible"])
        self.assertIsNone(restored.data["position"])

    def test_unknown_context_and_excess_lot_do_not_open(self):
        self.setup["production_eligible"] = False
        self.assertFalse(self.open()["approved"])
        self.setup["production_eligible"] = True
        big = PaperAccount("large", "1", self.contract, "model", "clock")
        outcome = self.open(big)
        self.assertFalse(outcome["approved"])
        self.assertIn("FIXED_LOT_EXCEEDS_RISK_BUDGET", outcome["reasons"])

    def test_polling_gap_is_flagged_and_stop_uses_observed_price(self):
        self.open()
        self.account.mark(self.quote(100, bid=1.0975, ask=1.0976))
        event = self.account.events[-1]
        self.assertTrue(event["position"]["coverage_uncertain"])
        self.assertAlmostEqual(event["exit_price"], 1.09748)

    def test_session_change_does_not_reset_daily_risk_or_cash(self):
        self.open()
        self.account.mark(self.quote(10), force_close="OPERATOR_STOP")
        previous = self.account.snapshot()
        next_session = PaperAccount(
            "next", "0.02", self.contract, "model", "clock", previous_account=previous
        )
        self.assertEqual(next_session.data["balance"], previous["balance"])
        self.assertEqual(next_session.data["daily_entries"], 1)
        self.assertEqual(next_session.data["units"], 2000)

    def test_existing_position_cannot_be_discarded_or_rebound_to_other_model(self):
        self.open()
        with self.assertRaises(ValueError):
            PaperAccount(
                "new",
                "0.01",
                self.contract,
                "model",
                "clock",
                previous_account=self.account.snapshot(),
            )
        with self.assertRaises(ValueError):
            PaperAccount(
                "fixture",
                "0.01",
                self.contract,
                "other",
                "clock",
                checkpoint=self.account.snapshot(),
            )

    def test_time_cannot_move_backwards(self):
        self.account.mark(self.quote(10))
        with self.assertRaises(ValueError):
            self.account.mark(self.quote(1))
