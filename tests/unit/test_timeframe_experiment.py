from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.literature_strategies import setups
from run_literature_experiment import simulate
from run_timeframe_experiment import PROFILES
from tests.unit import test_literature_strategies as fixtures


class TimeframeExperimentTests(unittest.TestCase):
    def higher(self,tf):
        h=fixtures.LiteratureStrategyTests().history()
        known=datetime(2026,1,7,12,tzinfo=timezone.utc)
        seconds={'M15':900,'H1':3600}[tf]
        retime=lambda bars,step:[Candle(known-timedelta(seconds=(len(bars)-i)*step),b.open,b.high,b.low,b.close,b.volume,b.spread_pips) for i,b in enumerate(bars)]
        execution=retime(h['M5'],seconds)
        if tf=='M15':h['M15']=execution
        else:
            h['H4']=retime(h['H1'],14400);h['H1']=execution;h['D1']=[]
        return h,known

    def test_m15_and_h1_signals_available_only_after_their_close(self):
        for tf in ('M15','H1'):
            h,known=self.higher(tf)
            s=setups(h,**PROFILES[tf])['trend_pullback']
            self.assertEqual(s['known_at'],known.isoformat())
            self.assertEqual(s['execution_timeframe'],tf)
            self.assertEqual(s['context_timeframe'],PROFILES[tf]['context'])
            self.assertEqual(s['candidate'].expires_at,known+timedelta(seconds={'M15':900,'H1':3600}[tf]))

    def test_future_context_for_coarser_execution_fails_closed(self):
        h,known=self.higher('H1');b=h['H4'][-1]
        h['H4'][-1]=Candle(b.timestamp+timedelta(hours=4),b.open,b.high,b.low,b.close,b.volume,b.spread_pips)
        with self.assertRaises(ValueError):setups(h,**PROFILES['H1'])

    def test_larger_signal_executes_on_m5_and_keeps_stop_first(self):
        at=datetime(2026,1,7,12,tzinfo=timezone.utc)
        sample=dict(sample_id='coarse',signal_at=at.isoformat(),entry_at=at.isoformat(),
            snapshot=dict(snapshot_id='coarse',session=['london'],regime='RESEARCH'),
            candidate=dict(side='long',entry=1.1,stop=1.099,target=1.104,expires_at=(at+timedelta(hours=1)).isoformat(),evidence=[]))
        bar=Candle(at,1.1,1.105,1.098,1.1,100,1.2)
        result=simulate([sample],[bar],start=at,end=at+timedelta(days=2),holding_bars=288,purge_hours=24)
        self.assertEqual(result['closed_trades'],1)
        self.assertEqual(result['trades'][0]['reason'],'STOP_FIRST_AMBIGUOUS')
        self.assertLess(result['net_pnl'],0)
