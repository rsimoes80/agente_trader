import copy
import unittest
from aurelia_fx.entry_trend import entry_blocker
from aurelia_fx.trend_experiment import eligible, replay, wilson


class TrendExperimentTests(unittest.TestCase):
    def sample(self):
        return dict(candidate=dict(side='long'),snapshot=dict(regime='TREND',
            context_trend=dict(direction='bullish',state='BULL_CONFIRMED'),
            macro_trend=dict(direction='bearish',state='BEAR_CONFIRMED')))

    def test_only_h4_requirement_changes(self):
        s=self.sample()
        self.assertTrue(eligible(s,'h1'))
        self.assertFalse(eligible(s,'h4_h1'))
        s['snapshot']['macro_trend']=copy.deepcopy(s['snapshot']['context_trend'])
        self.assertTrue(eligible(s,'h4_h1'))
        for p in ['h1','h4_h1']:
            s['snapshot']['regime']='RANGE'
            self.assertFalse(eligible(s,p))

    def test_experiment_cannot_enable_counter_h1_or_unconfirmed_entries(self):
        for change in ['side','state']:
            s=self.sample()
            if change=='side':s['candidate']['side']='short'
            else:s['snapshot']['context_trend']['state']='POTENTIAL_BULL'
            self.assertFalse(eligible(s,'h1'))
        # Calling the experiment never relaxes the live policy.
        s=self.sample();eligible(s,'h1')
        self.assertEqual(entry_blocker(s['snapshot'],'long'),'TREND_TIMEFRAME_CONFLICT')

    def test_empty_sample_is_not_reported_as_zero_percent_accuracy(self):
        r=replay([],[],policy='h1',start='2026-01-01T00:00:00+00:00',end='2026-02-01T00:00:00+00:00',units=1000)
        self.assertIsNone(r['win_rate_pct'])
        self.assertIsNone(r['win_rate_wilson_95_pct'])
        self.assertEqual(r['closed_trades'],0)
        self.assertFalse(r['unresolved_position'])
        self.assertIsNone(wilson(0,0))
        self.assertGreater(wilson(0,2)[1],50)

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):eligible(self.sample(),'unsupported')
