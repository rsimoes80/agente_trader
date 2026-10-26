"""Prospective research coverage, restart and broker-policy isolation."""
import copy
import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from aurelia_fx import continual_learning as cl, exploratory_learning as el
from . import test_continual_learning as fixtures


class ExploratoryLearningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ContinualLearningTests()
        self.fixture.setUp()
        self.at = self.fixture.at
        self.lab = self.fixture.lab
        self.parent = self.lab['continual']
        self.setup = copy.deepcopy(self.fixture.setup)
        self.setup['snapshot']['regime'] = 'RANGE'
        self.setup['features'] = self.fixture.features
        el.initialize(self.parent, self.at-timedelta(minutes=5))

    def test_blocked_candidate_is_simulated_but_not_production_eligible(self):
        before = copy.deepcopy(self.parent)
        cl.consider(self.lab, self.setup, self.fixture.features)
        self.assertEqual(self.parent['eligible_signals'], 0)
        el.consider(self.parent, self.setup, self.fixture.features)
        self.assertEqual(self.parent['exploratory']['submitted'], 1)
        self.assertEqual(sum(self.parent['exploratory']['policy_blocks'].values()), 1)
        for key in ('portfolios', 'contexts', 'outcomes', 'champion'):
            self.assertEqual(self.parent[key], before[key])
        with self.assertRaises(ValueError):
            cl.apply(self.setup, 'baseline')

    def test_future_close_has_costs_and_exact_restart_without_duplicate(self):
        el.consider(self.parent, self.setup, self.fixture.features)
        self.assertEqual(self.parent['exploratory']['closed'], 0)
        restored = json.loads(json.dumps(self.parent))
        bar = self.fixture.bar(self.at, high=1.1055, close=1.103)
        for state in (self.parent, restored):
            el.advance(state, bar, self.at+timedelta(minutes=5), ('london',))
            el.advance(state, bar, self.at+timedelta(minutes=5), ('london',))
        self.assertEqual(self.parent, restored)
        state = self.parent['exploratory']
        self.assertEqual(state['closed'], 1)
        result = state['hypothesis_review']['reviews'][0]
        self.assertGreater(result['costs'], 0)
        self.assertEqual(result['scope'], 'exploratory_shadow_not_broker')
        self.assertEqual(self.parent['outcomes'], [])

    def test_old_or_repeated_signal_is_not_submitted_twice(self):
        el.consider(self.parent, self.setup, self.fixture.features)
        el.consider(self.parent, self.setup, self.fixture.features)
        old = {**self.setup, 'signal_at': (self.at-timedelta(minutes=10)).isoformat()}
        el.consider(self.parent, old, self.fixture.features)
        self.assertEqual(self.parent['exploratory']['candidates'], 1)

    def test_incomplete_bar_is_not_consumed_by_continual_integration(self):
        el.consider(self.parent, self.setup, self.fixture.features)
        cl.advance(self.lab, [self.fixture.bar(self.at)], self.at+timedelta(seconds=1))
        self.assertEqual(self.parent['exploratory']['closed'], 0)
        self.assertIsNone(self.parent['exploratory']['last_bar'])

    def test_gap_censors_exposure_and_invalidates_cohort_without_a_loss(self):
        el.consider(self.parent, self.setup, self.fixture.features)
        el.advance(self.parent, self.fixture.bar(self.at), self.at+timedelta(minutes=5), ('london',))
        later = self.at+timedelta(minutes=15)
        el.advance(self.parent, self.fixture.bar(later), later+timedelta(minutes=5), ('london',))
        state = self.parent['exploratory']
        self.assertEqual(state['censored'], 1)
        self.assertEqual(state['closed'], 0)
        self.assertEqual(state['net_pnl'], 0)
        self.assertIsNone(state['portfolio'])

    def test_unready_history_never_generates_or_forecasts_candidate(self):
        with patch('aurelia_fx.agent_strategy.propose_pullback') as propose:
            el.observe(self.parent, None, [], [], at=self.at, ready=False,
                       source='clock', model='model', forecast=lambda: self.fail('unexpected forecast'))
        propose.assert_not_called()

    def test_forecast_failure_is_explicit_and_does_not_create_confirmation(self):
        self.setup['features'] = {'body_atr': .8}
        with patch('aurelia_fx.agent_strategy.propose_pullback', return_value=(self.setup, None)):
            el.observe(self.parent, None, [], [], at=self.at, ready=True,
                source='clock', model='model', forecast=lambda: (_ for _ in ()).throw(RuntimeError('unavailable')))
        state = self.parent['exploratory']
        self.assertEqual(state['forecast_errors'], 1)
        facts = state['portfolio']['request']['intelligence_context']['hypothesis_critique']
        self.assertEqual(state['last_forecast_error'], 'RuntimeError')
        self.assertIn('forecast', facts['missing'])
        self.assertNotIn('FORECAST_DISAGREES', facts['concerns'])
        self.assertEqual(self.setup['features'], {'body_atr': .8})

    def test_summary_omits_portfolio_and_cannot_activate_strategy(self):
        el.consider(self.parent, self.setup, self.fixture.features)
        result = el.summary(self.parent)
        self.assertNotIn('portfolio', result)
        self.assertFalse(result['automatic_activation'])
        self.assertFalse(result['hypothesis_review']['automatic_activation'])


if __name__ == '__main__':
    unittest.main()
