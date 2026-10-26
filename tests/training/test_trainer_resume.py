"""Pinned Timestral-5M, tiny synthetic data, isolated CPU; no broker or PG writes."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('AURELIA_TEST_TRAINING')=='1','Small real-model CPU opt-in')
class TrainerResumeTests(unittest.TestCase):
    def test_completed_epoch_resume_exports_identical_candidate(self):
        import numpy as np
        import psutil
        from aurelia_fx.training.trainer import train
        from aurelia_fx.training.checkpoints import digest
        root=Path(__file__).resolve().parents[2]
        data=np.ones((500,7));data[:,0]=np.arange(500)*300
        data[:,4]=1.1+np.sin(np.arange(500)/20)*.001
        manifest=dict(dataset_id='synthetic-resume-fixture-v1')
        def check():
            if psutil.virtual_memory().available<128*1024**2 or psutil.Process().memory_info().rss>768*1024**2:
                raise RuntimeError('Fixture stopped at production memory guard')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'dataset';folder.mkdir()
            for name,indices in [('train',[256,268,280,292]),('validation',[352,364]),('test',[400,412])]:
                np.save(folder/(name+'.npy'),np.array(indices))
            full=Path(tmp)/'full';resumed=Path(tmp)/'resumed'
            with patch('aurelia_fx.training.dataset.validate_dataset',return_value=(manifest,data)):
                a=train(root,folder,full,lambda **kw:None,check)
                def interrupt(**kw):
                    if (kw.get('saved_checkpoint') or {}).get('epoch')==1:raise RuntimeError('Fixture interruption after saved epoch')
                with self.assertRaisesRegex(RuntimeError,'Fixture interruption'):
                    train(root,folder,resumed,interrupt,check)
                observed=[]
                b=train(root,folder,resumed,lambda **kw:observed.append(kw),check)
            self.assertEqual(digest(full/'candidate/model.safetensors'),digest(resumed/'candidate/model.safetensors'))
            self.assertEqual(a['selection']['selected_epoch'],b['selection']['selected_epoch'])
            self.assertEqual(a['epochs'],b['epochs'])
            feature_starts=[r for r in observed if r.get('stage')=='features']
            self.assertTrue(feature_starts)
            self.assertTrue(all(r['completed']==r['total'] for r in feature_starts))
            self.assertFalse(any((r.get('saved_checkpoint') or {}).get('epoch')==1 for r in observed))


if __name__=='__main__':unittest.main()
