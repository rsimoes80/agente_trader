import copy
import unittest

from aurelia_fx.entry_trend import entry_blocker
from . import test_agent_paper as paper_fixtures


class EntryTrendTests(unittest.TestCase):
    def snapshot(self, direction='bullish'):
        state='BULL_CONFIRMED' if direction=='bullish' else 'BEAR_CONFIRMED'
        return dict(regime='TREND',session=['london'],
                    macro_trend=dict(direction=direction,state=state),
                    context_trend=dict(direction=direction,state=state))

    def test_only_matching_side_is_allowed_in_both_directions(self):
        for trend,side,opposite in [('bullish','long','short'),('bearish','short','long')]:
            with self.subTest(trend=trend):
                self.assertIsNone(entry_blocker(self.snapshot(trend),side))
                self.assertEqual(entry_blocker(self.snapshot(trend),opposite),'COUNTERTREND_ENTRY_BLOCKED')

    def test_unknown_range_transition_and_partial_confirmation_fail_closed(self):
        self.assertEqual(entry_blocker(None),'TREND_CONTEXT_MISSING')
        for regime in ['RANGE','TRANSITION','UNKNOWN',None]:
            self.assertEqual(entry_blocker({**self.snapshot(),'regime':regime}),'TREND_REGIME_REQUIRED')
        for role in ['context_trend','macro_trend']:
            for state in ['POTENTIAL_BULL','BULL_WEAKENING','UNKNOWN',None]:
                s=self.snapshot();s[role]['state']=state
                self.assertEqual(entry_blocker(s),'TREND_CONFIRMATION_REQUIRED')
        s=self.snapshot();s['macro_trend']=self.snapshot('bearish')['macro_trend']
        self.assertEqual(entry_blocker(s),'TREND_TIMEFRAME_CONFLICT')

    def test_research_hypothesis_cannot_override_entry_guard(self):
        from aurelia_fx.autonomous_lab import AutonomousLab
        fixture=paper_fixtures.PaperAccountTests();fixture.setUp()
        lab=AutonomousLab('fixture')
        features=dict(side=1,h1_direction_known=1,forecast_3_atr=1,forecast_6_atr=1)
        hypothesis=lab.select(features,self.snapshot(),{})
        account=__import__('aurelia_fx.agent_paper',fromlist=['PaperAccount']).PaperAccount(
            'test','0.01',fixture.contract,lab.protocol_id,'clock',research_mode=True)
        setup=copy.deepcopy(fixture.setup);setup['snapshot']=self.snapshot('bearish')
        result=account.open(setup,features,None,fixture.quote(3),active_sessions=['london'],hypothesis=hypothesis)
        self.assertEqual(result,dict(approved=False,reasons=['COUNTERTREND_ENTRY_BLOCKED']))
        self.assertIsNone(account.data['position'])

    def test_legacy_rewards_do_not_select_current_policy(self):
        from aurelia_fx.autonomous_lab import AutonomousLab
        lab=AutonomousLab('fixture')
        state={'live':{'RANGE|H1:1|london':{'context_pullback':dict(n=3,wins=1,losses=2)}}}
        summary=lab.summary(state)
        self.assertEqual(summary['previous_policy_results'],3)
        self.assertEqual(sum(row['n'] for row in summary['hypotheses']),0)
