import json
import os
import unittest
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
from aurelia_fx.training.dataset import split_windows
from aurelia_fx.training.metrics import forecast_metrics,forecast_gate,paired_day_interval
from aurelia_fx.training.repository import TrainingRepository,Cancelled


class TrainingDataTests(unittest.TestCase):
    def test_targets_are_purged_and_context_never_uses_future(self):
        first=datetime(2025,1,1,tzinfo=timezone.utc);end=first+timedelta(days=10)
        stamps=np.arange(int(first.timestamp())-256*300,int(end.timestamp()),300)
        partitions,bounds,excluded=split_windows(stamps,first_label=first,end=end,stride=1)
        self.assertGreater(excluded['cross_boundary'],0)
        for phase,upper in zip(('train','validation','test'),[*bounds,int(end.timestamp())]):
            indices=partitions[phase]
            self.assertTrue((stamps[indices+11]+300<upper).all())
            self.assertTrue((stamps[indices-1]<stamps[indices]).all())
        self.assertFalse(set(partitions['train'])&set(partitions['test']))

    def test_weekend_and_feed_gaps_are_never_bridged_by_training_windows(self):
        first=datetime(2025,1,1,tzinfo=timezone.utc)
        stamps=np.arange(int(first.timestamp()),int(first.timestamp())+300*3000,300)
        stamps[1500:]+=86400
        partitions,_,excluded=split_windows(stamps,first_label=first,end=datetime.fromtimestamp(int(stamps[-1]+300),timezone.utc),stride=1)
        self.assertGreater(excluded['gap'],0)
        for indices in partitions.values():
            for i in indices:self.assertTrue((np.diff(stamps[i-256:i+12])==300).all())

    def test_metrics_and_gates_reject_zero_improvement(self):
        target=np.ones((240,12))*1.1;ref=np.ones(240)*1.1
        p=np.broadcast_to(np.array([1.099,1.1,1.101]),(240,12,3))
        metrics,loss=forecast_metrics(p,target,ref,[.1,.5,.9])
        self.assertAlmostEqual(metrics['horizons']['3']['mae_pips'],0)
        interval=paired_day_interval(loss,loss,np.arange(240)*86400)
        gate=forecast_gate(metrics,metrics,interval)
        self.assertFalse(gate['passed']);self.assertIn('PINBALL_IMPROVEMENT_BELOW_2_PERCENT',gate['reasons'])
        self.assertIn('PAIRED_DAY_EVIDENCE_INCONCLUSIVE',gate['reasons'])

    def test_crossed_quantiles_and_nan_targets_rejected(self):
        p=np.ones((5,12,3));y=np.ones((5,12));r=np.ones(5)
        p[...,0]=2
        with self.assertRaises(ValueError):forecast_metrics(p,y,r,[.1,.5,.9])
        p[:]=1;y[0,0]=np.nan
        with self.assertRaises(ValueError):forecast_metrics(p,y,r,[.1,.5,.9])


@unittest.skipUnless(os.environ.get('TIMESTRAL_TEST_POSTGRES')=='1','PostgreSQL integration opt-in')
class TrainingQueueTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from aurelia_fx.storage import database_url
        from aurelia_fx.experience_memory import ExperienceMemory
        self.c=psycopg.connect(database_url(),autocommit=True,row_factory=dict_row)
        self.addCleanup(self.c.close);self.c.execute('BEGIN');self.addCleanup(self.c.execute,'ROLLBACK')
        schema='training_test_'+uuid4().hex
        self.c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        self.c.execute(sql.SQL('SET LOCAL search_path TO {}').format(sql.Identifier(schema)))
        self.c.execute('CREATE TABLE project_records(record_type TEXT,record_key TEXT,payload_json TEXT,payload_sha256 TEXT,recorded_at TIMESTAMPTZ DEFAULT clock_timestamp())')
        self.repo=TrainingRepository(SimpleNamespace(pool=SimpleNamespace(connection=lambda:nullcontext(self.c)),_encode=ExperienceMemory._encode))

    def test_start_is_single_and_commands_idempotent(self):
        key=uuid4().hex;a=self.repo.command('START',key)
        self.assertEqual(a,self.repo.command('START',key))
        self.assertEqual(a['run_id'],self.repo.command('START',uuid4().hex)['run_id'])
        with self.assertRaises(ValueError):self.repo.command('CANCEL',key)

    def test_cancel_fences_worker_and_next_run(self):
        a=self.repo.command('START',uuid4().hex);self.repo.command('CANCEL',uuid4().hex)
        with self.assertRaises(Cancelled):self.repo.publish(a['run_id'],status='TRAINING')
        self.repo.finish_cancel(a['run_id']);b=self.repo.command('START',uuid4().hex)
        self.assertNotEqual(a['run_id'],b['run_id'])
        with self.assertRaises(Cancelled):self.repo.publish(a['run_id'],status='NOT_APPROVED')

    def test_state_tampering_is_not_silently_accepted(self):
        self.repo.command('START',uuid4().hex)
        self.c.execute("UPDATE project_records SET payload_json='{}' WHERE record_type='agent_training_lab_state'")
        with self.assertRaises(ValueError):self.repo.latest()
