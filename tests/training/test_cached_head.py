import os,unittest
from pathlib import Path

@unittest.skipUnless(os.environ.get('AURELIA_TEST_TRAINING')=='1','Isolated CPU training opt-in')
class CachedHeadTests(unittest.TestCase):
    def test_cached_hidden_reconstructs_native_quantiles_and_gradient(self):
        import torch
        from timestral import TimestralForecaster
        from timestral.scaler import denormalize_quantiles
        from huggingface_hub import snapshot_download
        from aurelia_fx.training.proof import SOURCE_MODEL,SOURCE_REVISION
        root=Path(__file__).resolve().parents[2];torch.set_num_threads(1)
        path=snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,cache_dir=str(root/'data/training/cache'),local_files_only=True,token=False,allow_patterns=['config.json','model.safetensors','LICENSE'])
        f=TimestralForecaster.from_pretrained(path,device='cpu',max_context=256);model=f.model
        for p in model.parameters():p.requires_grad_(False)
        capture={};hook=model.head.register_forward_pre_hook(lambda _,args:capture.update(hidden=args[0].detach()))
        x=(1.1+torch.arange(256)*.00001).reshape(1,256);mask=torch.ones_like(x,dtype=torch.bool)
        with torch.no_grad():
            native=model.predict_block(x,mask,torch.zeros(1,dtype=torch.long),1)[:,:12]
            _,loc,scale=model.scale(x,mask)
        hook.remove()
        for p in model.head.parameters():p.requires_grad_(True)
        pred=denormalize_quantiles(model.head(capture['hidden'])[:,:12],loc[:,-32].reshape(1,1,1),scale[:,-32].reshape(1,1,1),model.config.use_asinh)
        self.assertTrue(torch.equal(native,pred));pred.sum().backward()
        self.assertTrue(any(p.grad is not None for p in model.head.parameters()))
        self.assertTrue(all(p.grad is None for n,p in model.named_parameters() if not n.startswith('head.')))
        public=f.forecast(x,prediction_length=12).quantiles
        self.assertEqual(tuple(public.shape),(1,1,12,len(f.quantile_levels)))

    def test_confirmation_reads_batch_variate_horizon_axes_and_both_horizons(self):
        import torch
        from types import SimpleNamespace
        from aurelia_fx.training.simulation import confirms
        q=torch.ones(1,1,12,3)*1.101
        fake=SimpleNamespace(model=SimpleNamespace(config=SimpleNamespace(quantile_knots=(.1,.5,.9))),forecast=lambda *a,**kw:SimpleNamespace(quantiles=q))
        self.assertTrue(confirms(fake,[],1,1.1));self.assertFalse(confirms(fake,[],-1,1.1))
        q[0,0,5,1]=1.099
        self.assertFalse(confirms(fake,[],1,1.1))
