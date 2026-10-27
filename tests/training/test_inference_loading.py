"""Numerical loader equivalence; run in the isolated Timestral environment."""
import importlib.util
from pathlib import Path
import tempfile
import unittest


@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('timestral'),
                     'Requires the isolated Timestral environment')
class InferenceLoadingTests(unittest.TestCase):
    def setUp(self):
        import torch
        from safetensors.torch import save_file
        from timestral.config import TimestralConfig
        from timestral.model import TimestralModel
        torch.set_num_threads(1);torch.manual_seed(17)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        config=TimestralConfig(patch_size=4,d_model=32,num_heads=4,mlp_hidden_dim=64,
            block_schedule=('time','time_variate'),quantile_knots=(.1,.5,.9),block_size=4,context_length=64)
        config.save(self.path/'config.json')
        self.original=TimestralModel(config)
        save_file(self.original.state_dict(),self.path/'model.safetensors')

    def test_parameters_buffers_and_forecasts_equal_the_original_sdk(self):
        import numpy as np
        import torch
        from timestral import TimestralForecaster
        from aurelia_fx.forecasting.loading import load_forecaster
        reference=TimestralForecaster.from_pretrained(self.path,device='cpu',max_context=64)
        optimized=load_forecaster(self.path,device='cpu',max_context=64)
        self.assertFalse(any(p.is_meta for p in optimized.model.parameters()))
        self.assertFalse(any(b.is_meta for b in optimized.model.buffers()))
        for key,value in reference.model.state_dict().items():
            self.assertTrue(torch.equal(value,optimized.model.state_dict()[key]),key)
        self.assertTrue(torch.equal(reference.model.transformer.rope.inv_freq,optimized.model.transformer.rope.inv_freq))
        for scale in (1.,4000.):
            context=(np.linspace(1.1,1.2,64)*scale).reshape(1,1,-1)
            a=reference.forecast(context,prediction_length=12)
            b=optimized.forecast(context,prediction_length=12)
            for q in (.1,.5,.9):self.assertTrue(torch.equal(a.quantile(q),b.quantile(q)))

    def test_incomplete_checkpoint_is_rejected_strictly(self):
        from safetensors.torch import save_file
        from aurelia_fx.forecasting.loading import load_forecaster
        weights=self.original.state_dict();weights.pop(next(iter(weights)))
        save_file(weights,self.path/'model.safetensors')
        with self.assertRaises(RuntimeError):load_forecaster(self.path,device='cpu',max_context=64)


if __name__=='__main__':unittest.main()
