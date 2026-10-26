from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.broker_calendar import slot_tradable
from run_timestral_timeframe_pilot import opportunities,signal


class TimeframePilotTests(unittest.TestCase):
    def case(self):
        return dict(timeframe='H1',reference=1.1,atr=.001,spread_pips=1.1,
                    signal_at='2026-03-30T08:00:00+00:00',session=['london'])

    def test_same_direction_has_distinct_cost_gate(self):
        output=dict(quantiles=[[1.099,1.1001,1.101] for _ in range(12)])
        self.assertIsNotNone(signal(self.case(),output,cost_gate=False))
        self.assertIsNone(signal(self.case(),output,cost_gate=True))

    def test_stop_target_and_next_m5_expiry_are_fixed(self):
        output=dict(quantiles=[[1.098,1.099,1.101] for _ in range(12)])
        result=signal(self.case(),output,cost_gate=True);candidate=result['candidate']
        self.assertEqual(candidate['side'],'short')
        self.assertAlmostEqual(candidate['stop'],1.1015)
        self.assertAlmostEqual(candidate['target'],1.0955)
        self.assertEqual(candidate['expires_at'],'2026-03-30T08:05:00+00:00')

    def test_missing_spread_is_not_zero_cost(self):
        output=dict(quantiles=[[1.099,1.1005,1.102] for _ in range(12)])
        self.assertIsNone(signal({**self.case(),'spread_pips':None},output,cost_gate=True))

    def test_london_schedule_and_closed_prefix_across_dst(self):
        start=datetime(2026,3,1,tzinfo=timezone.utc);end=datetime(2026,3,31,tzinfo=timezone.utc)
        bars=[];now=start
        while now<end:
            if slot_tradable(now):bars.append(Candle(now,1.1,1.101,1.099,1.1,10,1.1))
            now+=timedelta(minutes=5)
        cases=opportunities(bars,start+timedelta(days=5))
        for stamp in ('2026-03-27T09:00:00+00:00','2026-03-30T08:00:00+00:00'):
            self.assertEqual({c['timeframe'] for c in cases if c['signal_at']==stamp},{'M5','M15','H1'})
        self.assertTrue(all(len(c['values'])==64 for c in cases))
        self.assertEqual(len(cases),len({(c['timeframe'],c['signal_at']) for c in cases}))


if __name__=='__main__':unittest.main()
