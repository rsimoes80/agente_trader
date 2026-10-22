import copy,json,unittest
from datetime import timedelta
from aurelia_fx import continual_learning as cl
from aurelia_fx.domain import Candle
from . import test_agent_paper as fixtures

class ContinualLearningTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.PaperAccountTests();fixture.setUp();self.at=fixture.start;self.setup={**fixture.setup,'atr':.001}
        self.setup['snapshot']={**self.setup['snapshot'],'snapshot_id':'fixture-snapshot'}
        self.features=dict(side=1,h1_direction_known=1,body_atr=.8,forecast_3_atr=.1,forecast_6_atr=.2)
        self.lab={};cl.initialize(self.lab,self.at-timedelta(minutes=10),1000.)
    def bar(self,at,high=1.101,low=1.099,close=1.1):return Candle(at,1.1,high,low,close,100,.8)

    def test_alternatives_change_execution_levels_and_keep_stop_and_trend(self):
        original=cl.apply(self.setup,'baseline')['candidate'];other=cl.apply(self.setup,'target_3r')['candidate']
        self.assertEqual(other.stop,original.stop);self.assertGreater(other.target,original.target)
        self.assertFalse(cl.accepts('forecast',{**self.features,'forecast_3_atr':-1}))
        with self.assertRaises(ValueError):cl.apply({**self.setup,'snapshot':{**self.setup['snapshot'],'regime':'RANGE'}},'target_3r')

    def test_prospective_targets_are_not_scored_until_observed_and_restart_is_exact(self):
        cl.advance(self.lab,[self.bar(self.at-timedelta(minutes=5))],self.at)
        cl.consider(self.lab,self.setup,self.features)
        self.assertEqual(len(self.lab['continual']['outcomes']),0)
        restarted=json.loads(json.dumps(self.lab))
        bar=self.bar(self.at,high=1.1055,close=1.103)
        events=cl.advance(self.lab,[bar],self.at+timedelta(minutes=5))
        again=cl.advance(restarted,[bar],self.at+timedelta(minutes=5))
        self.assertEqual(events,again);self.assertGreater(len(events),0)
        self.assertEqual(self.lab['continual']['portfolios'],restarted['continual']['portfolios'])
        self.assertEqual(cl.advance(self.lab,[bar],self.at+timedelta(minutes=5)),[])

    def test_recent_real_losses_suspend_only_the_comparable_context(self):
        h=cl.choose(self.lab,self.setup,self.features,'fixture')
        for _ in range(10):cl.real_result(self.lab,h,-1.,-1.)
        blocked=cl.choose(self.lab,self.setup,self.features,'fixture')
        self.assertTrue(blocked['wait']);self.assertEqual(blocked['reason'],'LEARNED_CONTEXT_SUSPENDED')
        other={**self.setup,'atr':.0001}
        self.assertFalse(cl.choose(self.lab,other,self.features,'fixture')['wait'])

    def test_one_loss_does_not_replace_strategy_and_recent_evidence_can_recover(self):
        h=cl.choose(self.lab,self.setup,self.features,'fixture');cl.real_result(self.lab,h,-1.,-1.)
        self.assertFalse(cl.choose(self.lab,self.setup,self.features,'fixture')['wait'])
        cell={}
        for _ in range(40):cl.add_stats(cell,-1.,-1.)
        for _ in range(40):cl.add_stats(cell,1.,1.)
        self.assertGreater(cell['recent_mean_r'],0)

    def test_legacy_results_never_become_new_variant_evidence(self):
        cl.real_result(self.lab,{'id':'context_pullback'},1.,1.)
        self.assertEqual(self.lab['continual']['real'],{});self.assertEqual(self.lab['continual']['excluded_legacy'],1)

    def test_model_deterioration_requests_rollback_and_survives_lot_change(self):
        setup={**self.setup,'learning_model':'fixture-model'}
        h=cl.choose(self.lab,setup,self.features,'fixture')
        for _ in range(19):cl.real_result(self.lab,h,-1.,-1.)
        self.assertNotIn('model_rollback_request',self.lab['continual'])
        cl.real_result(self.lab,h,-1.,-1.)
        self.assertEqual(self.lab['continual']['model_rollback_request']['model_configuration'],'fixture-model')
        cl.initialize(self.lab,self.at+timedelta(days=1),2000.)
        self.assertEqual(self.lab['continual']['model_rollback_request']['samples'],20)

    def test_promotion_is_automatic_only_after_costed_future_evidence(self):
        state=self.lab['continual']
        for day in range(7):
            at=(self.at+timedelta(days=day)).isoformat()
            for _ in range(3):
                state['outcomes']+= [dict(variant='baseline',net_pnl=-1.,exit_at=at),dict(variant='target_3r',net_pnl=2.,exit_at=at)]
        cl.promote(state,self.at+timedelta(days=3));self.assertEqual(state['champion'],'baseline')
        cl.promote(state,self.at+timedelta(days=8));self.assertEqual(state['champion'],'target_3r')
        # A global winner is not blindly applied in an unseen context.
        self.assertEqual(cl.choose(self.lab,self.setup,self.features,'fixture')['variant_id'],'baseline')
        state['contexts'][cl.context(self.setup)]={'target_3r':dict(n=8,recent_mean_r=.5)}
        self.assertEqual(cl.choose(self.lab,self.setup,self.features,'fixture')['variant_id'],'target_3r')

    def test_missing_exposure_data_restarts_trial_and_never_produces_a_win(self):
        cl.advance(self.lab,[self.bar(self.at-timedelta(minutes=5))],self.at)
        cl.consider(self.lab,self.setup,self.features)
        cl.advance(self.lab,[self.bar(self.at)],self.at+timedelta(minutes=5))
        events=cl.advance(self.lab,[self.bar(self.at+timedelta(minutes=20),high=1.108,close=1.107)],self.at+timedelta(minutes=25))
        self.assertTrue(any(e['scope']=='excluded_unreliable_exposure' for e in events))
        self.assertEqual(self.lab['continual']['outcomes'],[])
