import copy
from datetime import datetime,timezone
from types import SimpleNamespace
import unittest

from aurelia_fx.forecasting.config import TimestralConfig
from aurelia_fx.training.visibility import evolution,model_view,select_model,use_result


class ModelVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,27,13,tzinfo=timezone.utc)
        self.config=TimestralConfig(enabled=True,revision='base')
        self.account=SimpleNamespace(data=dict(session_id='session'))
        select_model(self.account,self.config,symbol='EURUSD',profile_id=None,worker_id='worker',now=self.now)
        self.agent=dict(symbol='EURUSD',session_id='session',model_runtime=self.account.data['model_runtime'])
        self.worker=dict(available=True,heartbeat=dict(worker_id='worker'))
        self.state=dict(symbol='EURUSD',run_id='run',status='TRAINING',stage='features')

    def view(self,**changes):
        return evolution({**self.state,**changes},self.agent,self.worker)

    def result(self,digest='a'*64,source='engine'):
        use_result(self.account,self.config,dict(model='mistralai/Timestral-209M',revision='base',artifact_sha256=digest,
            execution_evidence=dict(source=source,computed_at=self.now.isoformat(),cache_key='cache')),now=self.now)

    def test_preparation_or_resource_wait_never_means_weights_adjusted(self):
        e=self.view(status='WAITING_RESOURCES',resource_reason='HOST_RAM_LOW')
        self.assertEqual(e['weights']['status'],'NOT_RECORDED')
        self.assertEqual(e['decision']['application'],'PENDING_EVALUATION')
        self.assertEqual(e['reasons'][0]['phase'],'execution')
        self.assertEqual(e['model']['status'],'CONFIGURED')

    def test_actual_forecast_and_cache_use_are_distinct_and_bound_to_worker(self):
        self.result(source='cache')
        view=model_view(self.agent,self.worker)
        self.assertEqual(view['status'],'CONFIRMED_RESULT')
        self.assertEqual(view['last_result']['source'],'cache')
        select_model(self.account,self.config,symbol='EURUSD',profile_id=None,worker_id='replacement',now=self.now)
        self.agent['model_runtime']=self.account.data['model_runtime']
        view=model_view(self.agent,dict(available=True,heartbeat=dict(worker_id='replacement')))
        self.assertEqual(view['status'],'CONFIGURED')
        self.assertFalse(view['result_matches_selected'])

    def test_unknown_or_other_instrument_is_never_reported_as_current_model(self):
        agent={**self.agent,'symbol':'XAUUSD','profile_id':'b'*64}
        view=model_view(agent,self.worker)
        self.assertEqual(view['status'],'UNKNOWN')
        self.assertIsNone(view['selected'])
        with self.assertRaisesRegex(ValueError,'SYMBOL_MISMATCH'):evolution(self.state,agent,self.worker)

    def test_approved_is_not_applied_until_matching_artifact_is_used(self):
        selected=self.account.data['model_runtime']['selected'];selected['artifact_sha256']='a'*64
        self.assertEqual(self.view(status='PROMOTED',selection=dict(candidate_sha256='a'*64))['decision']['application'],'APPROVED_PENDING_USE')
        self.result()
        self.assertEqual(self.view(status='PROMOTED',selection=dict(candidate_sha256='a'*64))['decision']['application'],'IN_USE')
        self.worker['available']=False
        self.assertEqual(self.view(status='PROMOTED',selection=dict(candidate_sha256='a'*64))['decision']['application'],'APPROVED_PENDING_USE')

    def test_epoch_zero_does_not_hide_real_training_or_claim_candidate_changed(self):
        update=dict(epoch=3,last_gradient_at=self.now.isoformat(),changed_from_source=True)
        e=self.view(weight_update=update,selection=dict(selected_epoch=0,candidate_weights_changed=False))
        self.assertEqual(e['weights']['update'],update)
        self.assertFalse(e['weights']['candidate_changed'])
        self.assertIn('época zero',e['weights']['message'])

    def test_legacy_training_is_shown_without_inventing_an_adjustment_date(self):
        e=self.view(forecast_report=dict(epochs=[dict(epoch=1)],selection=dict(selected_epoch=1)))
        self.assertEqual(e['weights']['status'],'LEGACY_REPORT')
        self.assertIsNone(e['weights']['update'])

    def test_comparison_has_correct_direction_and_missing_results_are_not_zero(self):
        report=dict(partitions=dict(test=dict(source=dict(mean_pinball_pips=4.,horizons={}),
            candidate=dict(mean_pinball_pips=3.,horizons={}),gate=dict(reasons=['MAE_DEGRADED_12']))))
        financial=dict(arms=dict(source=dict(net_pnl=2,max_close_equity_drawdown_pct=1),
            candidate=dict(net_pnl=-1,max_close_equity_drawdown_pct=2)))
        original=copy.deepcopy(report)
        e=self.view(status='NOT_APPROVED',forecast_report=report,financial_report=financial)
        self.assertEqual(e['comparisons'][0]['change'],'IMPROVED')
        self.assertEqual(e['comparisons'][1]['change'],'UNAVAILABLE')
        self.assertIsNone(e['comparisons'][1]['source'])
        self.assertEqual(e['comparisons'][-2]['change'],'WORSE')
        self.assertEqual(e['comparisons'][-1]['change'],'WORSE')
        self.assertIn('60 minutos',e['reasons'][0]['message'])
        self.assertEqual(report,original)

    def test_no_training_job_still_shows_own_instrument(self):
        e=evolution(dict(symbol='XAUUSD',status='NOT_STARTED'),dict(symbol='XAUUSD'),dict(available=False))
        self.assertEqual(e['trace']['symbol'],'XAUUSD')
        self.assertEqual(e['decision']['application'],'NO_CANDIDATE')


if __name__=='__main__':unittest.main()
