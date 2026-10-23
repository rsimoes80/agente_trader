import copy
from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.correction_experiment import phase,replay
from aurelia_fx.domain import Candle
from aurelia_fx.entry_trend import entry_blocker
from aurelia_fx.levels import SupportResistanceEngine
from aurelia_fx.research_levels import ResearchLevels


class CorrectionExperimentTests(unittest.TestCase):
    def fixture(self,bearish=False):
        at=datetime(2026,1,5,tzinfo=timezone.utc)
        prices=[1.1000]*60+[1.1040,1.1035,1.1030,1.1060]
        bars=[]
        for i,close in enumerate(prices):
            opening=close+.0001 if 60<=i<=62 else close-.0001
            high=max(opening,close)+.0001;low=min(opening,close)-.0001
            if bearish:opening,close,high,low=2.2-opening,2.2-close,2.2-low,2.2-high
            bars.append(Candle(at+timedelta(minutes=5*i),opening,high,low,close,100,1))
        tr=dict(direction='bearish' if bearish else 'bullish',
                state='BEAR_CONFIRMED' if bearish else 'BULL_CONFIRMED',data_quality=dict(valid=True))
        tr['last_confirmed_high' if bearish else 'last_confirmed_low']=dict(
            price=1.11 if bearish else 1.09,confirmed_at=at.isoformat())
        return dict(regime='UNKNOWN',regime_state=dict(missing_data=[]),
                    macro_trend=copy.deepcopy(tr),context_trend=tr),bars

    def test_confirmed_aligned_correction_resumes_both_directions(self):
        for bearish in (False,True):
            snapshot,bars=self.fixture(bearish)
            result=phase(snapshot,bars)
            self.assertEqual(result['phase'],'RESUMPTION')
            self.assertTrue(result['allowed'])
            # Experiment must never modify the production blocker or original regime.
            self.assertEqual(snapshot['regime'],'UNKNOWN')
            self.assertEqual(entry_blocker(snapshot),'TREND_REGIME_REQUIRED')

    def test_range_unconfirmed_and_conflicting_context_never_add_entries(self):
        snapshot,bars=self.fixture()
        for change in ('range','unconfirmed','conflict','missing'):
            s=copy.deepcopy(snapshot)
            if change=='range':s['regime']='RANGE'
            elif change=='unconfirmed':s['context_trend']['state']='POTENTIAL_BULL'
            elif change=='missing':s['regime_state']['missing_data']=['REGIME_DATA_STALE']
            else:s['macro_trend'].update(direction='bearish',state='BEAR_CONFIRMED')
            self.assertFalse(phase(s,bars)['allowed'],change)

    def test_structural_break_and_future_confirmation_are_blocked(self):
        s,bars=self.fixture()
        s['context_trend']['last_confirmed_low']['price']=1.104
        self.assertEqual(phase(s,bars)['reason'],'H1_PROTECTED_SWING_BROKEN')
        s,bars=self.fixture()
        s['context_trend']['last_confirmed_low']['confirmed_at']=(bars[-1].timestamp+timedelta(hours=1)).isoformat()
        self.assertEqual(phase(s,bars)['reason'],'FUTURE_SWING_REJECTED')

    def test_no_trigger_means_wait_and_zero_samples_not_zero_accuracy(self):
        s,bars=self.fixture()
        bars=bars[:-1]
        self.assertFalse(phase(s,bars)['allowed'])
        r=replay([],[],arm='strict_current',start='2026-01-01T00:00:00Z',end='2026-02-01T00:00:00Z',units=1000)
        self.assertIsNone(r['win_rate_pct'])
        self.assertEqual(r['closed_trades'],0)

    def test_cached_levels_match_reference_including_expiry_and_ranking(self):
        from math import sin
        at=datetime(2026,1,5,tzinfo=timezone.utc)
        bars=[]
        for i in range(40):
            close=1.1+.002*sin(i)
            bars.append(Candle(at+timedelta(hours=i),close,close+.0002,close-.0002,close,100,1))
        original=SupportResistanceEngine(tolerance=.0002,ttl_bars=30)
        cached=ResearchLevels(tolerance=.0002,ttl_bars=30)
        for end,elapsed in ((25,25),(25,26),(40,40),(40,45)):
            now=at+timedelta(hours=elapsed)
            expected=original.evaluate({'H1':bars[:end]},symbol='EURUSD',now=now)
            actual=cached.evaluate({'H1':bars[:end]},symbol='EURUSD',now=now)
            self.assertEqual(expected,actual)
            for price in (1.09,1.1,1.11):
                for limit in (None,1,12):
                    for side,target in (('long',1.12),('short',1.08)):
                        self.assertEqual(original.context(expected,price,limit=limit,side=side,target=target),
                                         cached.context(actual,price,limit=limit,side=side,target=target))

    def test_common_signals_same_portfolio_and_missing_exposure_is_censored(self):
        start=datetime(2026,1,5,13,tzinfo=timezone.utc)
        sample=dict(sample_id='fixture',signal_at=start.isoformat(),entry_at=start.isoformat(),
            arms=['strict_current','strict_or_guarded_correction'],
            snapshot=dict(snapshot_id='fixture',session=['london'],regime='TREND'),
            candidate=dict(side='long',entry=1.1,stop=1.098,target=1.105,
                           expires_at=(start+timedelta(minutes=5)).isoformat(),evidence=[]))
        bars=[Candle(start,1.1,1.1005,1.0995,1.1002,100,1),
              Candle(start+timedelta(minutes=5),1.1002,1.1055,1.1001,1.105,100,1)]
        args=dict(start=start,end=start+timedelta(hours=3),units=1000)
        left=replay([sample],bars,arm='strict_current',**args)
        right=replay([sample],bars,arm='strict_or_guarded_correction',**args)
        self.assertEqual(left,right)
        self.assertEqual(left['closed_trades'],1)
        self.assertGreater(left['spread_cost_closed'],0)
        self.assertGreater(left['commission_closed'],0)
        gapbar=Candle(start+timedelta(minutes=15),1.1002,1.1055,1.1001,1.105,100,1)
        censored=replay([sample],[bars[0],gapbar],arm='strict_current',**args)
        self.assertTrue(censored['account_locked'])
        self.assertIsNone(censored['net_pnl'])
        self.assertEqual(censored['censored_trades'],1)


if __name__=='__main__':unittest.main()
