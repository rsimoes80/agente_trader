"""Synthetic causal-cycle checks; financial fixtures do not prove market edge."""
import copy
import json
import unittest
from dataclasses import replace
from datetime import timedelta
from unittest.mock import patch

from aurelia_fx import hypothesis_review as hr, continual_learning as cl
from . import test_continual_learning as fixtures


class HypothesisReviewTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ContinualLearningTests(); fixture.setUp()
        self.fixture = fixture
        self.at = fixture.at
        self.state = {}

    def closed(self, index, *, pnl=-1., gross=-.8, at=None, signal=None, concerns=None, context='ctx'):
        at = at or self.at+timedelta(hours=index)
        signal = signal or at-timedelta(minutes=10)
        facts = dict(spec_hash=hr.SPEC_HASH, signal_at=signal.isoformat(), concerns=concerns or ['WEAK_BODY'])
        result = dict(variant='baseline',context=context,entry_at=signal.isoformat(),exit_at=at.isoformat(),
                      net_pnl=pnl,result_in_r=pnl,event_id=str(index))
        event = dict(intelligence_context=dict(hypothesis_critique=facts), rule_compliance=True,
                     financial_result=dict(net_pnl=pnl,gross_pnl=gross))
        hr.review(self.state,event,result)
        return event,result

    def discover(self):
        for i in range(20):self.closed(i)
        return self.state['hypothesis_review']['proposal']

    def test_missing_forecasts_are_not_disagreement(self):
        facts=hr.critique(self.fixture.setup,dict(body_atr=.8))
        self.assertNotIn('FORECAST_DISAGREES',facts['concerns'])
        self.assertIn('forecast',facts['missing'])

    def test_positive_direction_below_cost_is_explicitly_distinguished(self):
        features={**self.fixture.features,'stop_atr':2.,'spread_stop':.055}
        facts=hr.critique(self.fixture.setup,features)
        self.assertNotIn('FORECAST_DISAGREES',facts['concerns'])
        self.assertIn('FORECAST_BELOW_COST',facts['concerns'])
        self.assertAlmostEqual(facts['cost_comparison']['estimated_round_trip_cost'],.00022)
        self.assertAlmostEqual(facts['cost_comparison']['projected_move'],.0002)
        strong=hr.critique(self.fixture.setup,{**features,'forecast_6_atr':1.})
        self.assertNotIn('FORECAST_BELOW_COST',strong['concerns'])

    def test_missing_spread_is_not_fabricated_as_zero_cost(self):
        facts=hr.critique(self.fixture.setup,self.fixture.features)
        self.assertIsNone(facts['cost_comparison'])
        self.assertIn('forecast_cost_comparison',facts['missing'])

    def test_snapshot_conflicts_are_not_lost_when_candidate_has_none(self):
        setup={**self.fixture.setup,'snapshot':{**self.fixture.setup['snapshot'],'conflicting_evidence':['higher timeframe disagrees']}}
        facts=hr.critique(setup,self.fixture.features)
        self.assertIn('CONTRADICTIONS',facts['concerns'])
        self.assertIn('higher timeframe disagrees',facts['contradictions'])

    def test_filtered_portfolio_can_take_opportunity_while_base_is_busy(self):
        p=self.discover();p['formed_at']=(self.at-timedelta(hours=1)).isoformat()
        p['ends_at']=(self.at+timedelta(days=14)).isoformat()
        self.state['units']=1000.
        setup=self.fixture.setup
        hr.consider_portfolios(self.state,setup,{**self.fixture.features,'body_atr':.1},'ctx')
        self.assertIsNotNone(p['portfolios']['base']['request'])
        self.assertIsNone(p['portfolios']['filtered']['request'])
        hr.advance_portfolios(self.state,self.fixture.bar(self.at),True,('london',))
        self.assertIsNotNone(p['portfolios']['base']['position'])
        signal=self.at+timedelta(minutes=5)
        next_setup={**setup,'signal_at':signal.isoformat(),
                    'candidate':replace(setup['candidate'],expires_at=signal+timedelta(minutes=5))}
        hr.consider_portfolios(self.state,next_setup,self.fixture.features,'ctx')
        self.assertIsNotNone(p['portfolios']['base']['position'])
        self.assertIsNotNone(p['portfolios']['filtered']['request'])

    def test_replay_gap_invalidates_future_portfolio(self):
        p=self.discover();p['formed_at']=(self.at-timedelta(hours=1)).isoformat()
        p['ends_at']=(self.at+timedelta(days=14)).isoformat();self.state['units']=1000.
        hr.consider_portfolios(self.state,self.fixture.setup,self.fixture.features,'ctx')
        hr.advance_portfolios(self.state,self.fixture.bar(self.at),True,('london',))
        hr.advance_portfolios(self.state,self.fixture.bar(self.at+timedelta(minutes=20)),False,('london',))
        self.assertEqual(p['status'],'INVALIDATED_DATA_GAP')

    def test_costs_separated_and_duplicate_idempotent(self):
        event,result=self.closed(0,pnl=-.1,gross=.1)
        hr.review(self.state,event,result)
        research=self.state['hypothesis_review']
        self.assertEqual(research['reviewed'],1)
        self.assertEqual(research['reviews'][0]['assessment'],'COSTS_CONSUMED_GROSS_GAIN')
        self.assertAlmostEqual(research['reviews'][0]['costs'],.2)

    def test_parallel_variant_is_not_independent(self):
        event,result=self.closed(0)
        hr.review(self.state,event,{**result,'variant':'forecast','event_id':'other'})
        self.assertEqual(self.state['hypothesis_review']['reviewed'],1)

    def test_future_window_is_frozen_and_late_old_signals_excluded(self):
        proposal=self.discover();frozen=copy.deepcopy(proposal)
        formed=hr.utc(proposal['formed_at'])
        self.closed(50,at=formed+timedelta(hours=1),signal=formed-timedelta(minutes=1))
        self.closed(51,at=formed+timedelta(hours=2),context='another')
        self.assertEqual(proposal['validation'],[])
        self.closed(52,at=formed+timedelta(hours=3))
        self.assertEqual(len(proposal['validation']),1)
        self.assertEqual(proposal['ends_at'],frozen['ends_at'])
        self.assertEqual(proposal['rule'],frozen['rule'])

    def test_restart_preserves_state(self):
        self.discover()
        self.assertEqual(hr.summary(self.state),hr.summary(json.loads(json.dumps(self.state))))

    def test_small_future_sample_is_not_promoted(self):
        p=self.discover()
        hr.evaluate(self.state,hr.utc(p['ends_at'])+timedelta(days=1))
        self.assertEqual(p['status'],'INSUFFICIENT_FUTURE_SAMPLE')
        self.assertFalse(p['automatic_activation'])

    def test_summary_does_not_send_portfolio_checkpoints_to_browser(self):
        self.discover()
        self.assertNotIn('portfolios',hr.summary(self.state)['proposal'])
        self.assertNotIn('portfolio_results',hr.summary(self.state)['proposal'])

    def test_positive_ablation_without_portfolio_evidence_is_not_validated(self):
        p=self.discover()
        p['validation']=[dict(net_pnl=-1.,concerns=['WEAK_BODY']) for _ in range(20)]
        p['validation'] += [dict(net_pnl=1.,concerns=[]) for _ in range(10)]
        hr.evaluate(self.state,hr.utc(p['ends_at'])+timedelta(days=1))
        self.assertEqual(p['status'],'PORTFOLIO_BENEFIT_NOT_ESTABLISHED')
        self.assertFalse(p['automatic_activation'])

    def test_no_future_evaluation_before_fixed_deadline(self):
        p=self.discover()
        p['validation']=[dict(net_pnl=-1.,concerns=['WEAK_BODY']) for _ in range(30)]
        hr.evaluate(self.state,hr.utc(p['ends_at']))
        self.assertEqual(p['status'],'COLLECTING_FUTURE')

    def test_positive_portfolio_still_requires_independent_confirmation(self):
        p=self.discover()
        p['validation']=[dict(net_pnl=-1.,concerns=['WEAK_BODY']) for _ in range(20)]
        p['validation'] += [dict(net_pnl=1.,concerns=[]) for _ in range(10)]
        p['portfolio_results']=[dict(arm='base',net_pnl=-1.) for _ in range(30)]
        p['portfolio_results'] += [dict(arm='filtered',net_pnl=1.) for _ in range(30)]
        hr.evaluate(self.state,hr.utc(p['ends_at'])+timedelta(days=1))
        self.assertEqual(p['status'],'PROMISING_REQUIRES_INDEPENDENT_CONFIRMATION')
        self.assertFalse(p['automatic_activation'])

    def test_changed_protocol_does_not_mix_old_experiences(self):
        self.closed(0)
        self.state['hypothesis_review']['spec_hash']='old'
        fresh=hr.state_for(self.state)
        self.assertEqual(fresh['reviews'],[])
        self.assertEqual(self.state['previous_hypothesis_review']['spec_hash'],'old')

    def test_completed_trial_does_not_repeat_same_rule_until_it_wins(self):
        p=self.discover();end=hr.utc(p['ends_at'])+timedelta(days=1)
        hr.evaluate(self.state,end)
        for i in range(30):self.closed(100+i,at=end+timedelta(hours=i+1))
        self.assertEqual(self.state['hypothesis_review']['proposal']['id'],p['id'])
        self.assertEqual(len(self.state['hypothesis_review']['attempted']),1)

    def test_fresh_context_can_be_researched_after_terminal_trial(self):
        p=self.discover();end=hr.utc(p['ends_at'])+timedelta(days=1)
        hr.evaluate(self.state,end)
        for i in range(20):self.closed(100+i,at=end+timedelta(hours=i+1),context='new_context')
        research=self.state['hypothesis_review']
        self.assertNotEqual(research['proposal']['id'],p['id'])
        self.assertEqual(research['proposal']['context'],'new_context')
        self.assertEqual(len(research['history']),1)
        self.assertEqual(research['proposal']['validation'],[])

    def test_metadata_cannot_change_existing_fills(self):
        fixture=self.fixture
        plain=copy.deepcopy(fixture.lab);enabled=copy.deepcopy(fixture.lab)
        with patch.object(cl.hypothesis_review,'critique',return_value={}):
            cl.consider(plain,fixture.setup,fixture.features)
        cl.consider(enabled,fixture.setup,fixture.features)
        bars=[fixture.bar(fixture.at,high=1.1055,close=1.103)]
        self.assertEqual(cl.advance(plain,bars,fixture.at+timedelta(minutes=5)),
                         cl.advance(enabled,bars,fixture.at+timedelta(minutes=5)))
        self.assertGreater(hr.summary(enabled['continual'])['reviewed'],0)

    def test_reject_financial_mismatch_before_appending(self):
        self.closed(0)
        event,result=self.closed(1)
        broken={**result,'event_id':'broken','net_pnl':999}
        with self.assertRaises(ValueError):hr.review(self.state,event,broken)


if __name__=='__main__':unittest.main()
