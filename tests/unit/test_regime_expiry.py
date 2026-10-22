import unittest
from dataclasses import replace
from datetime import timedelta
from aurelia_fx.regime import MarketRegimeEngine, RegimeConfig
from aurelia_fx.regime.models import BreakoutObservation, RegimeTransition
from . import test_market_regime_v4 as fixtures


class RegimeExpiryTests(unittest.TestCase):
    def scenario(self,policy='reset_pending_v1',started_minutes=0):
        cfg=RegimeConfig(window=6,confirmation_bars=3,breakout_lifetime_bars=8,
                         transition_expiry_policy=policy)
        engine=MarketRegimeEngine(cfg);bars=fixtures.range_bars(12)
        for i,b in enumerate(bars):
            before=engine.evaluate(bars[:i+1],symbol='EURUSD',timeframe='M1',
                now=b.timestamp+timedelta(minutes=1),snapshot_id=str(i))
        track=engine._tracks['EURUSD','M1']
        track['range']=replace(track['range'],status='EXIT_ACCEPTED')
        track['breakout']=BreakoutObservation('break','range','BULLISH',1.1003,
            fixtures.START.isoformat(),.0005,'OUTSIDE_ABOVE',current_status='CONFIRMED')
        track['transition']=RegimeTransition('transition','RANGE','TREND',
            (fixtures.START+timedelta(minutes=started_minutes)).isoformat(),'fixture',status='PARTIALLY_CONFIRMED')
        output=[]
        for i in [12,13,14]:
            bars.append(fixtures.candle(i,1.101+(i-12)*.00001))
            output.append(engine.evaluate(bars,symbol='EURUSD',timeframe='M1',
                now=bars[-1].timestamp+timedelta(minutes=1),snapshot_id=str(i)))
        return engine,before,output

    def test_expired_accepted_range_cannot_resurrect_transition(self):
        engine,before,states=self.scenario()
        self.assertEqual(states[0].regime,'UNKNOWN')
        self.assertEqual(states[0].subtype,'TRANSITION_EXPIRED')
        self.assertEqual(states[0].transition_status,'EXPIRED')
        self.assertFalse(states[0].range_state)
        self.assertIsNone(engine._tracks['EURUSD','M1']['range'])
        self.assertFalse(any(s.regime=='TRANSITION' and s.transition_status=='EXPIRED' for s in states))
        self.assertFalse(any(s.regime=='TREND' for s in states))
        self.assertEqual(before.regime,'RANGE')

    def test_legacy_path_reproduces_reported_bug_for_offline_comparison(self):
        _,_,states=self.scenario('legacy_research_v0')
        self.assertTrue(any(s.regime=='TRANSITION' and s.transition_status=='EXPIRED' for s in states))

    def test_active_transition_is_not_cleared_early(self):
        _,_,states=self.scenario(started_minutes=11)
        self.assertEqual(states[0].regime,'TRANSITION')
        self.assertEqual(states[0].transition_status,'PARTIALLY_CONFIRMED')
        self.assertTrue(states[0].range_state)

    def test_invalid_policy_rejected(self):
        with self.assertRaises(ValueError):RegimeConfig(transition_expiry_policy='ignore')
