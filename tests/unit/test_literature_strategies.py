from datetime import datetime, timedelta, timezone
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.literature_strategies import bias, candidate, setups
from run_literature_experiment import choose, simulate


class LiteratureStrategyTests(unittest.TestCase):
    def history(self):
        signal = datetime(2026,1,7,12,tzinfo=timezone.utc)
        def bar(t, op, cl, width=.0001):
            return Candle(t,op,max(op,cl)+width,min(op,cl)-width,cl,100,1.2)
        m5=[bar(signal-timedelta(minutes=5*(64-i)),1.1,1.1) for i in range(64)]
        m5[-2]=bar(m5[-2].timestamp,1.1002,1.1)
        m5[-1]=bar(m5[-1].timestamp,1.1,1.1006)
        h1=[bar(signal-timedelta(hours=60-i),1.09+i*.0001,1.09005+i*.0001) for i in range(60)]
        m15=[bar(signal-timedelta(minutes=15),1.1,1.1005)]
        return dict(M5=m5,H1=h1,M15=m15,H4=[])

    def mirror(self,h):
        return {tf:[Candle(b.timestamp,2.2-b.open,2.2-b.low,2.2-b.high,2.2-b.close,b.volume,b.spread_pips) for b in bars] for tf,bars in h.items()}

    def range_history(self):
        h=self.history();bars=h['M5']
        values=[-.0004,-.0002,0,.0002,.0004,.0002,0,-.0002]
        for i in range(62):
            p=1.1+values[i%8]
            bars[i]=Candle(bars[i].timestamp,p,p+.0001,p-.0001,p,100,1.2)
        bars[-2]=Candle(bars[-2].timestamp,1.0995,1.0998,1.0993,1.0997,100,1.2)
        bars[-1]=Candle(bars[-1].timestamp,1.0997,1.1002,1.0996,1.1001,100,1.2)
        return h

    def test_pullback_both_directions_without_h4_or_global_regime(self):
        for h,side in [(self.history(),'long'),(self.mirror(self.history()),'short')]:
            s=setups(h)['trend_pullback']
            self.assertEqual(s['candidate'].side,side)
            self.assertFalse(s['against_h1'])
            self.assertEqual(s['h4_bias'],0)

    def test_future_higher_timeframe_and_missing_m5_rejected(self):
        h=self.history();b=h['H1'][-1]
        h['H1'][-1]=Candle(b.timestamp+timedelta(hours=1),b.open,b.high,b.low,b.close,b.volume,b.spread_pips)
        with self.assertRaises(ValueError):setups(h)
        h=self.history();h['M5'].pop(-10)
        self.assertEqual(setups(h),{})

    def test_breakout_requires_a_later_retest_of_a_preexisting_level(self):
        h=self.history();bars=h['M5']
        bars[-3]=Candle(bars[-3].timestamp,1.1,1.1006,1.0999,1.1005,100,1.2)
        bars[-2]=Candle(bars[-2].timestamp,1.1005,1.10055,1.1,1.1003,100,1.2)
        bars[-1]=Candle(bars[-1].timestamp,1.1002,1.1008,1.10005,1.1007,100,1.2)
        result=setups(h)['breakout_retest']
        self.assertEqual(result['event'],bars[-3].timestamp.isoformat())
        b=bars[-1]
        bars[-1]=Candle(b.timestamp,1.1004,b.high,1.1003,b.close,100,1.2)
        self.assertNotIn('breakout_retest',setups(h))

    def test_range_can_trade_against_h1_only_as_its_own_family(self):
        h=self.range_history();h['H1']=self.mirror(h)['H1']
        s=setups(h)['range_failure']
        self.assertEqual(s['candidate'].side,'long')
        self.assertTrue(s['against_h1'])
        self.assertNotIn('trend_pullback',setups(h))

    def test_reversal_requires_sweep_micro_break_and_closed_m15_response(self):
        h=self.range_history();h['H1']=self.mirror(h)['H1']
        b=h['M5'][-1]
        h['M5'][-1]=Candle(b.timestamp,b.open,1.101, b.low,1.1009,100,1.2)
        self.assertEqual(setups(h)['reversal_shift']['candidate'].side,'long')
        h['M15']=self.mirror(h)['M15']
        self.assertNotIn('reversal_shift',setups(h))

    def test_quote_target_uses_only_current_quote_and_widens_tiny_stop(self):
        b=self.history()['M5'][-1]
        c=candidate(b,1,b.close-.00001,.0003)
        self.assertAlmostEqual(c.stop,b.close-.0003)
        anticipated=b.close+.00012+.00002
        self.assertAlmostEqual(c.target,anticipated+3*(anticipated-c.stop))
        self.assertEqual(c.entry,b.close)

    def test_no_development_winner_when_only_negative_or_small_samples(self):
        def r(n,net,pf,avg):
            return dict(closed_trades=n,net_pnl=net,profit_factor=pf,expectancy_usd=avg,unresolved_position=False,account_locked=False,censored_trades=0)
        self.assertIsNone(choose(dict(a=r(100,-1,.9,-.01),b=r(3,10,2,3.3))))
        self.assertEqual(choose(dict(a=r(100,10,1.2,.1),b=r(60,12,1.3,.2))),'b')

    def test_calendar_flatten_and_stress_costs(self):
        at=datetime(2026,1,2,21,45,tzinfo=timezone.utc)
        bars=[Candle(at+timedelta(minutes=5*i),1.1,1.1001,1.0999,1.1,100,1.2) for i in range(2)]
        s=dict(sample_id='test',signal_at=at.isoformat(),entry_at=at.isoformat(),
            snapshot=dict(snapshot_id='test',session=['new_york'],regime='RESEARCH'),
            candidate=dict(side='long',entry=1.1,stop=1.099,target=1.104,expires_at=(at+timedelta(minutes=5)).isoformat(),evidence=[]))
        args=dict(start=at,end=at+timedelta(hours=3))
        normal=simulate([s],bars,**args);stress=simulate([s],bars,stress=True,**args)
        self.assertEqual(normal['closed_trades'],1)
        self.assertFalse(normal['unresolved_position'])
        self.assertEqual(normal['trades'][0]['reason'],'KNOWN_SESSION_END')
        self.assertLess(stress['net_pnl'],normal['net_pnl'])
