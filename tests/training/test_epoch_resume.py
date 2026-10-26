"""Small deterministic CPU fixture; does not load Timestral or send orders."""
import tempfile
import unittest
from pathlib import Path


class EpochResumeTests(unittest.TestCase):
    def test_completed_public_evaluations_are_not_repeated_or_silently_rebuilt(self):
        import json
        import numpy as np
        import torch
        from types import SimpleNamespace
        from unittest.mock import patch
        from safetensors.torch import save_file
        from aurelia_fx.training.checkpoints import atomic_json,digest
        from aurelia_fx.training.evaluation import evaluate
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'dataset';folder.mkdir();out=root/'out';out.mkdir()
            source=root/'source';source.mkdir();(source/'model.safetensors').write_bytes(b'fixed-source')
            (out/'candidate').mkdir();head={'weight':torch.ones((1,2)), 'bias':torch.zeros(1)}
            save_file(head,out/'best-head.safetensors');save_file({'head.'+k:v for k,v in head.items()},out/'candidate/model.safetensors')
            sealed=dict(candidate_sha256=digest(out/'candidate/model.safetensors'))
            atomic_json(out/'selection.json',sealed)
            atomic_json(out/'sealed-report-seed.json',dict(source_sha256=digest(source/'model.safetensors'),selection=sealed,partitions={}))
            for phase in ('validation','test'):np.save(folder/(phase+'.npy'),np.array([256,268]))
            data=np.ones((300,7));data[:,0]=np.arange(300)*300;data[:,4]=1.1
            calls=[]
            class Fake:
                quantile_levels=[.1,.5,.9]
                def __init__(self):self.model=SimpleNamespace(head=torch.nn.Linear(2,1))
                def forecast(self,x,prediction_length):
                    calls.append(len(x));q=np.broadcast_to(np.array([1.099,1.1,1.101],dtype='float32'),(len(x),1,12,3)).copy()
                    return SimpleNamespace(quantiles=torch.from_numpy(q))
            with patch('timestral.TimestralForecaster.from_pretrained',side_effect=lambda *a,**k:Fake()),patch('huggingface_hub.snapshot_download',return_value=str(source)),patch('aurelia_fx.training.dataset.validate_dataset',return_value=({'dataset_id':'same'},data)):
                report=evaluate(root,folder,out,lambda **k:None,lambda:None)
                self.assertEqual(len(calls),4);self.assertIn('evaluation_path',report)
                calls.clear();evaluate(root,folder,out,lambda **k:None,lambda:None)
                self.assertEqual(calls,[])
                path=out/'test-candidate-public-predictions.npy'
                with path.open('ab') as f:f.write(b'changed')
                with self.assertRaises(ValueError):evaluate(root,folder,out,lambda **k:None,lambda:None)
                self.assertEqual(calls,[])

    def test_optimizer_rng_and_weights_match_uninterrupted_training(self):
        import numpy as np
        import torch
        from aurelia_fx.training.checkpoints import save_epoch,load_epoch
        torch.set_num_threads(1)
        def initialize():
            torch.manual_seed(31);m=torch.nn.Linear(2,1)
            return m,torch.optim.AdamW(m.parameters(),lr=.001),np.random.default_rng(31)
        def step(m,o,r):
            for i in r.permutation(8):
                x=torch.randn(1,2)+float(i);o.zero_grad()
                loss=(m(x)-1).square().mean();loss.backward();o.step()
        m,o,r=initialize()
        for _ in range(3):step(m,o,r)
        expected={k:v.clone() for k,v in m.state_dict().items()}
        m,o,r=initialize();step(m,o,r)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'epoch.pt'
            save_epoch(p,dict(head=m.state_dict(),optimizer=o.state_dict(),numpy_rng=r.bit_generator.state,
                             torch_rng=torch.get_rng_state(),epoch=1),'fixed')
            resumed=load_epoch(p,'fixed')
            m,o,r=initialize();m.load_state_dict(resumed['head']);o.load_state_dict(resumed['optimizer'])
            r.bit_generator.state=resumed['numpy_rng'];torch.set_rng_state(resumed['torch_rng'])
            for _ in range(resumed['epoch'],3):step(m,o,r)
            for k,v in m.state_dict().items():self.assertTrue(torch.equal(v,expected[k]))
            with self.assertRaises(ValueError):load_epoch(p,'changed')
            checkpoint=next(Path(tmp).glob('epoch.*.pt'));checkpoint.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):load_epoch(p,'fixed')


if __name__=='__main__':unittest.main()
