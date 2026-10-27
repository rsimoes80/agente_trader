import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch

import numpy as np
from aurelia_fx.training.checkpoints import FeatureCheckpoint,atomic_json
from aurelia_fx.training import runtime


class FeatureRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_only_committed_prefix_survives_a_restart(self):
        shapes={'hidden':(12,1,2),'target':(12,12)}
        c=FeatureCheckpoint(self.root,'train','same',shapes)
        for a in c.arrays.values():a[:8]=3
        c.commit(8)
        for a in c.arrays.values():a[8:]=999;a.flush()
        del c
        resumed=FeatureCheckpoint(self.root,'train','same',shapes)
        self.assertEqual(resumed.completed,8)
        for a in resumed.arrays.values():np.testing.assert_array_equal(a[:8],3);a[8:]=4
        resumed.commit(12);del resumed
        final=FeatureCheckpoint(self.root,'train','same',shapes)
        self.assertEqual(final.completed,12)
        for a in final.arrays.values():np.testing.assert_array_equal(a[8:],4)
        final.arrays.clear()

    def test_signature_or_committed_data_change_blocks_resume(self):
        c=FeatureCheckpoint(self.root,'train','same',{'hidden':(8,1,2)})
        c.arrays['hidden'][:]=1;c.commit(8);c.arrays.clear()
        with self.assertRaises(ValueError):FeatureCheckpoint(self.root,'train','other',{'hidden':(8,1,2)})
        a=np.load(self.root/'train-hidden.npy',mmap_mode='r+');a[0]=2;a.flush();del a
        with self.assertRaises(ValueError):FeatureCheckpoint(self.root,'train','same',{'hidden':(8,1,2)})

    def test_uncommitted_metadata_never_advances_cursor(self):
        c=FeatureCheckpoint(self.root,'train','same',{'hidden':(8,1,2)})
        c.arrays['hidden'][:]=1;c.commit(4);c.arrays.clear()
        (self.root/'train-checkpoint.json.tmp').write_text('broken')
        c=FeatureCheckpoint(self.root,'train','same',{'hidden':(8,1,2)})
        self.assertEqual(c.completed,4);c.arrays.clear()


class TrainingRuntimeTests(unittest.TestCase):
    def test_guards_keep_existing_limits_and_reason(self):
        self.assertEqual(runtime.MIN_START_MB,384)
        self.assertEqual(runtime.resource_reason(769,500,1),'WORKER_RAM_LIMIT')
        self.assertEqual(runtime.resource_reason(300,127,1),'HOST_RAM_LOW')
        self.assertEqual(runtime.resource_reason(300,500,7201),'TIME_BUDGET')
        self.assertIsNone(runtime.resource_reason(768,128,7200))

    def test_retry_is_bounded_and_has_backoff_without_changing_experiment(self):
        at=datetime(2026,10,26,tzinfo=timezone.utc)
        state={'run_id':'same','protocol_id':'fixed','resource_retries':0,'stage':'features'}
        result=runtime.deferred(state,'HOST_RAM_LOW',at)
        self.assertEqual(result['status'],'WAITING_RESOURCES')
        self.assertEqual(result['retry_not_before'],(at+timedelta(minutes=15)).isoformat())
        self.assertNotIn('protocol_id',result)
        self.assertEqual(runtime.deferred({**state,'resource_retries':3},'HOST_RAM_LOW',at)['status'],'FAILED')
        self.assertEqual(runtime.deferred(state,'WORKER_RAM_LIMIT',at)['status'],'FAILED')

    def test_sample_is_explicitly_windows_and_does_not_fake_worker_usage(self):
        memory=Mock();s=runtime.sample(memory,{'run_id':'same'},available_mb=290)
        self.assertEqual(s['shortage_mb'],94)
        self.assertIsNone(s['worker_rss_mb'])
        self.assertEqual(s['host_role'],'windows_training_runner')
        memory.record_project_data.assert_called_once()

    def test_summary_does_not_turn_forecast_improvement_into_profit(self):
        s=runtime.learning_summary(dict(status='NOT_APPROVED',forecast_report=dict(partitions=dict(test=dict(gate=dict(pinball_improvement_pct=3)))),
            financial_report=dict(arms=dict(source=dict(net_pnl=-1),candidate=dict(net_pnl=-2))),decision=dict(reasons=['NET_PROFIT_NOT_POSITIVE'])))
        self.assertEqual(s['candidate_net'],-2)
        self.assertIn('não aprovado',s['conclusion'])
        self.assertFalse(s['live_model_changed'])

    def test_sealed_candidate_never_returns_to_training(self):
        import run_training_lab as runner
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);out=root/'data/training/runs/same';out.mkdir(parents=True)
            atomic_json(out/'selection.json',{'candidate_sha256':'sealed'})
            atomic_json(out/'sealed-report-seed.json',{'selection':{'candidate_sha256':'sealed'}})
            report=dict(evaluation_path='public',partitions=dict(test=dict(gate=dict(passed=False,reasons=['NO_GAIN']))),selection={})
            repo=Mock();state=dict(run_id='same',dataset_directory='dataset',dataset=dict(symbol='EURUSD'),automatic=True)
            with patch.object(runner,'ROOT',root),patch('psutil.Process'),patch('aurelia_fx.training.trainer.train') as train,patch('aurelia_fx.training.evaluation.evaluate',return_value=report) as evaluate:
                runner.worker(repo,state)
            train.assert_not_called();evaluate.assert_called_once()
            self.assertEqual(repo.publish.call_args.kwargs['status'],'NOT_APPROVED')


if __name__=='__main__':unittest.main()
