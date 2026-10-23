import unittest
from datetime import datetime, timezone

from run_h1_extended_validation import qualified, uncertainty, generate


class ExtendedValidationTests(unittest.TestCase):
    def result(self, **changes):
        return dict(account_locked=False, unresolved_position=False, censored_trades=0,
                    net_pnl=10, profit_factor=1.2, closed_trades=50, **changes)

    def test_minimum_not_relaxed_for_positive_result(self):
        normal = self.result()
        normal['closed_trades'] = 49
        self.assertFalse(qualified(normal,self.result(),50))
        self.assertTrue(qualified(self.result(),self.result(),50))

    def test_censored_or_negative_stress_disqualifies(self):
        for field,value in [('account_locked',True),('unresolved_position',True),
                            ('censored_trades',1),('net_pnl',None)]:
            normal = self.result()
            normal[field] = value
            self.assertFalse(qualified(normal,self.result(),20))
        stress = self.result()
        stress['net_pnl'] = -1
        self.assertFalse(qualified(self.result(),stress,20))

    def test_day_blocks_and_reproducibility(self):
        def trade(day,pnl):
            return dict(entry_at=f'2024-01-{day:02d}T10:00:00+00:00', financial_result=dict(net_pnl=pnl))
        trades = [trade(2,10),trade(2,-3),trade(3,-5)]
        a = uncertainty(trades,100)
        self.assertEqual(a,uncertainty(trades,100))
        self.assertEqual(a['trading_days'],2)
        self.assertEqual(a['net_without_best_trade'],-8)
        self.assertIsNone(uncertainty([])['net_interval_95'])

    def test_empty_input_does_not_create_signals(self):
        self.assertEqual(generate([],datetime(2024,1,1,tzinfo=timezone.utc)),[])
