from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from aurelia_fx.domain import Candle, Candidate, RiskLimits
from aurelia_fx.execution_simulator import ExecutionConfig, ExecutionSimulator, EntryRequest, classify_outcome


class ExecutionSimulatorTests(unittest.TestCase):
    def test_fixed_lot_preserves_units_instead_of_spending_full_risk_budget(self):
        self.simulator = ExecutionSimulator(replace(self.config, fixed_units=1000), self.limits)
        self.simulator.submit(self.request())
        fill = self.advance(self.bar())[0]
        self.assertEqual(fill["status"], "filled")
        self.assertEqual(fill["units"], 1000)
        self.assertLess(fill["initial_risk"], 50)

    def test_fixed_lot_above_risk_budget_is_rejected_without_resizing(self):
        self.simulator = ExecutionSimulator(replace(self.config, fixed_units=1_000_000), self.limits)
        self.simulator.submit(self.request())
        result = self.advance(self.bar())[0]
        self.assertEqual(result["status"], "rejected")
        self.assertIn("FIXED_LOT_EXCEEDS_RISK_BUDGET", result["risk"]["reasons"])
        self.assertIsNone(self.simulator.position)

    def setUp(self):
        self.start = datetime(2026, 10, 19, 8, tzinfo=timezone.utc)
        self.config = ExecutionConfig()
        self.limits = RiskLimits(.5, 2, 5, 2, 2, 5)
        self.simulator = ExecutionSimulator(self.config, self.limits)

    def request(self, side="long"):
        stop, target = (1.099, 1.103) if side == "long" else (1.101, 1.097)
        return EntryRequest("decision-1", "snapshot-1", "hypothesis-1",
            Candidate(side, 1.1, stop, target, self.start + timedelta(hours=1), ("confirmed",)),
            self.start, "london", "trend")

    def bar(self, index=0, *, opening=1.1, high=1.1004, low=1.0998, close=1.1002, spread=1):
        return Candle(self.start + timedelta(minutes=5 * index), opening, high, low, close, 100, spread)

    def advance(self, bar, **kwargs):
        return self.simulator.advance(bar, data_valid=True, active_sessions=("london",), **kwargs)

    def test_next_open_costs_and_target_accounting(self):
        self.simulator.submit(self.request())
        fills = self.advance(self.bar())
        self.assertEqual([e["status"] for e in fills], ["filled"])
        self.assertAlmostEqual(fills[0]["entry_price"], 1.10012)
        events = self.advance(self.bar(1, opening=1.1002, high=1.1031, low=1.1001, close=1.1028))
        result = events[-1]
        self.assertEqual(result["reason"], "TARGET")
        f = result["financial_result"]
        self.assertAlmostEqual(f["net_pnl"], f["gross_pnl"] - f["spread_cost"] - f["slippage_cost"] - f["commission"])
        self.assertAlmostEqual(f["net_pnl"], (result["exit_price"] - result["entry_price"]) * result["units"] - f["commission"])
        self.assertEqual(result["process_classification"], "good_process_profit")
        self.assertAlmostEqual(self.simulator.balance, 10_000 + f["net_pnl"])

    def test_both_levels_touch_stop_first_and_planned_loss_is_bounded(self):
        self.simulator.submit(self.request())
        result = self.advance(self.bar(high=1.104, low=1.098))[-1]
        self.assertEqual(result["reason"], "STOP_FIRST_AMBIGUOUS")
        self.assertAlmostEqual(result["financial_result"]["result_in_r"], -1)
        self.assertEqual(result["process_classification"], "good_process_loss")

    def test_short_exit_uses_ask_and_costs_are_not_double_counted(self):
        self.simulator.submit(self.request("short"))
        self.advance(self.bar())
        result = self.advance(self.bar(1, opening=1.1, high=1.1001, low=1.0968, close=1.097))[-1]
        self.assertEqual(result["reason"], "TARGET")
        f = result["financial_result"]
        self.assertAlmostEqual(f["net_pnl"], (result["entry_price"] - result["exit_price"]) * result["units"] - f["commission"])
        self.assertGreater(f["spread_cost"], 0)

    def test_entry_gap_revalidates_frozen_levels(self):
        self.simulator.submit(self.request())
        result = self.advance(self.bar(opening=1.104, high=1.1042, low=1.1038, close=1.104))[-1]
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "ENTRY_GAP_OUTSIDE_FROZEN_STOP_TARGET")
        self.assertEqual(self.simulator.balance, 10_000)

    def test_gap_through_stop_can_exceed_risk_without_being_bad_process(self):
        self.simulator.submit(self.request())
        self.advance(self.bar())
        result = self.advance(self.bar(1, opening=1.098, high=1.0985, low=1.0978, close=1.0982))[-1]
        self.assertEqual(result["reason"], "STOP_GAP")
        self.assertLess(result["financial_result"]["result_in_r"], -1)
        self.assertEqual(result["process_classification"], "good_process_loss")

    def test_missing_exposure_data_is_censored_and_account_locked(self):
        self.simulator.submit(self.request())
        self.advance(self.bar())
        events = self.simulator.advance(self.bar(1), data_valid=False, active_sessions=("london",))
        self.assertEqual(events[-1]["status"], "censored")
        self.assertIsNone(self.simulator.summary()["net_pnl"])
        self.assertTrue(self.simulator.account_locked)

    def test_expiry_and_end_of_data_are_explicit(self):
        self.simulator = ExecutionSimulator(replace(self.config, max_holding_bars=1), self.limits)
        self.simulator.submit(self.request())
        self.assertEqual(self.advance(self.bar())[-1]["reason"], "TIME_EXPIRY")
        self.simulator = ExecutionSimulator(self.config, self.limits)
        self.simulator.submit(self.request())
        self.assertEqual(self.simulator.finish(self.start)[-1]["reason"], "END_OF_DATA_NO_NEXT_OPEN")

    def test_profit_does_not_imply_compliant_process(self):
        self.assertEqual(classify_outcome(100, compliant=False), "poor_process_profit")
        self.assertEqual(classify_outcome(-100, compliant=True), "good_process_loss")

    def test_daily_loss_gate_uses_realized_simulated_balance(self):
        self.simulator.balance = 9_700
        self.simulator.day = self.start.date().isoformat()
        self.simulator.daily_start = 10_000
        self.simulator.submit(self.request())
        result = self.advance(self.bar())[-1]
        self.assertEqual(result["status"], "rejected")
        self.assertIn("DAILY_LOSS_LIMIT", result["risk"]["reasons"])


if __name__ == "__main__":
    unittest.main()
