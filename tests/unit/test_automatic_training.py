import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import Mock,patch
from aurelia_fx.training.automatic import schedule

class AutomaticTrainingTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,22,18,tzinfo=timezone.utc)
        self.repo=Mock();self.repo.latest.return_value=dict(status='NOT_APPROVED',dataset=dict(source_as_of=(self.now-timedelta(days=2)).isoformat()))
        self.repo.command.return_value=dict(run_id='fixture');self.repo.publish.return_value=dict(run_id='fixture',status='QUEUED')
        def publish(*args,**kwargs):
            self.repo.latest.return_value=dict(run_id='fixture',status='QUEUED',**kwargs)
            return self.repo.latest.return_value
        self.repo.publish.side_effect=publish
        self.agent=dict(desired='running',mode='demo',history=dict(clock_id='fixture'))
        self.baseline=dict(clock_id='fixture',as_of=self.now.isoformat(),start=(self.now-timedelta(days=30)).isoformat(),timeframes=dict(M5=dict(last=self.now.isoformat())))
    def test_stopped_agent_or_recent_attempt_does_not_fetch_or_queue(self):
        for agent,old in (({**self.agent,'desired':'stopped'},{}),(self.agent,dict(last_attempt=self.now.isoformat()))):
            with patch('aurelia_fx.training.automatic.status',return_value=old),patch('aurelia_fx.historical.collector.collect') as collect:
                schedule(self.repo,agent,Mock(),self.now);collect.assert_not_called()
        self.repo.command.assert_not_called()
    def test_weekend_elapsed_time_without_new_candles_never_retrains(self):
        with patch('aurelia_fx.training.automatic.status',return_value={}),patch('aurelia_fx.historical.collector.collect',return_value=self.baseline),patch('aurelia_fx.historical.repository.HistoricalRepository') as repository:
            repository.return_value.candles.return_value=[]
            schedule(self.repo,self.agent,Mock(),self.now)
        self.repo.command.assert_not_called()
        self.assertEqual(self.repo.memory.record_project_data.call_args.args[2]['status'],'WAITING_NEW_DATA')
    def test_new_data_queues_next_recipe_without_operator_action(self):
        with patch('aurelia_fx.training.automatic.status',return_value=dict(trial_number=1)),patch('aurelia_fx.historical.collector.collect',return_value=self.baseline),patch('aurelia_fx.historical.repository.HistoricalRepository') as repository:
            repository.return_value.candles.return_value=[{}]*288
            result=schedule(self.repo,self.agent,Mock(),self.now)
        self.repo.command.assert_called_once();self.assertTrue(self.repo.publish.call_args.kwargs['automatic'])
        self.assertEqual(self.repo.publish.call_args.kwargs['training_recipe'],'faster_head')
        self.assertEqual(result['status'],'QUEUED')
