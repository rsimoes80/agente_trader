import copy,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from aurelia_fx.training.online_study import OnlineStudy
from aurelia_fx.domain import Candle

class OnlineModelStudyTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,1,5,10,tzinfo=timezone.utc)
        self.memory=SimpleNamespace(record_project_data=Mock())
        self.lab={};self.study=OnlineStudy(self.memory,self.lab,dict(contract_size=100000,currency_profit='USD'),'clock')
        self.study.repo=Mock();self.study.run=dict(run_id='fixture',protocol_id='fixture-protocol',forecast_report=dict(selection=dict(candidate_sha256='a'*64)))
        self.d=dict(run_id='fixture',registered_at=(self.at-timedelta(days=30)).isoformat(),pending=['prediction'],last_forecast=self.at.isoformat(),
            forecast_count=1,aggregates={},day_losses={},accounts={},closed={},max_drawdown={},uncertain=0)
        self.lab['model_study']=self.d
        values=[[1.099,1.1,1.101] for _ in range(12)]
        self.study.cache['prediction']=dict(reference=self.at.isoformat(),reference_close=1.1,generated_at=(self.at+timedelta(minutes=5,seconds=1)).isoformat(),levels=[.1,.5,.9],source=values,candidate=values,active=values)
        self.context=[Candle(self.at,1.1,1.101,1.099,1.1)]
        self.rows=[dict(timestamp=(self.at+timedelta(minutes=5*i)).isoformat(),close=1.1) for i in range(1,13)]

    def test_only_closed_future_targets_score_and_results_are_not_recounted(self):
        self.study.observe(self.context,self.rows,dict(at=(self.at+timedelta(minutes=10)).isoformat()),Mock())
        self.assertEqual(self.d['aggregates'],{});self.assertEqual(self.d['pending'],['prediction'])
        quote=dict(at=(self.at+timedelta(minutes=65)).isoformat())
        self.study.observe(self.context,self.rows,quote,Mock())
        self.assertEqual(self.d['aggregates']['candidate']['windows'],1);self.assertEqual(self.d['pending'],[])
        self.study.observe(self.context,self.rows,quote,Mock())
        self.assertEqual(self.d['aggregates']['candidate']['windows'],1)

    def prepare_eligible(self):
        self.d.update(pending=[],closed=dict(source=20,candidate=20,active=20),accounts={k:dict(balance=v) for k,v in [('source',10010.),('candidate',10100.),('active',10020.)]},
            aggregates={k:dict(windows=250) for k in ('source','candidate','active','candidate_common')},
            max_drawdown=dict(source=1.,candidate=.2,active=.5),day_losses={(self.at-timedelta(days=i)).date().isoformat():dict(n=10,source=2.,candidate=1.,active=2.,candidate_common=1.) for i in range(20)})
        self.study.accounts={k:SimpleNamespace(data=dict(position=None)) for k in ('source','candidate','active')}

    def test_candidate_that_fails_against_active_model_is_not_promoted(self):
        self.prepare_eligible()
        with tempfile.TemporaryDirectory() as tmp,patch('aurelia_fx.training.online_study.ROOT',Path(tmp)),patch('aurelia_fx.training.online_study.forecast_gate',side_effect=[dict(passed=True),dict(passed=False)]),patch('aurelia_fx.training.releases.activate') as activate:
            self.study.evaluate(dict(at=(self.at+timedelta(days=1)).isoformat()))
            activate.assert_not_called()
        self.assertEqual(self.d['status'],'NOT_APPROVED')

    def test_validated_candidate_can_advance_automatically_without_user_command(self):
        self.prepare_eligible()
        with tempfile.TemporaryDirectory() as tmp,patch('aurelia_fx.training.online_study.ROOT',Path(tmp)),patch('aurelia_fx.training.online_study.forecast_gate',return_value=dict(passed=True)),patch('aurelia_fx.training.releases.activate',return_value='fixture-release') as activate:
            self.study.evaluate(dict(at=(self.at+timedelta(days=1)).isoformat()))
            activate.assert_called_once_with(Path(tmp),'fixture')
        self.assertEqual(self.d['status'],'PROMOTED')

    def test_insufficient_trades_or_unresolved_position_never_promote(self):
        self.prepare_eligible();self.d['closed']['candidate']=19
        with patch('aurelia_fx.training.online_study.forecast_gate',return_value=dict(passed=True)),patch('aurelia_fx.training.releases.activate') as activate:
            self.study.evaluate(dict(at=(self.at+timedelta(days=1)).isoformat()));activate.assert_not_called()
        self.d['closed']['candidate']=20;self.study.accounts['candidate'].data['position']={'fixture':True}
        with patch('aurelia_fx.training.online_study.forecast_gate',return_value=dict(passed=True)),patch('aurelia_fx.training.releases.activate') as activate:
            self.study.evaluate(dict(at=(self.at+timedelta(days=1)).isoformat()));activate.assert_not_called()
