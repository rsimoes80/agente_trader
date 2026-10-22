"""Real CPU subprocess on temporary artifacts; never approves a project candidate."""
import json,os,shutil,tempfile,unittest
from pathlib import Path

@unittest.skipUnless(os.environ.get('AURELIA_TEST_TRAINING')=='1','Isolated CPU training opt-in')
class StudyEngineTests(unittest.TestCase):
    def test_pair_engine_loads_one_backbone_and_returns_distinct_sealed_heads(self):
        import torch
        from safetensors.torch import load_file,save_file
        from aurelia_fx.training.proof import SOURCE_REVISION,file_hash
        from aurelia_fx.training.study_adapter import PairedStudyAdapter
        from aurelia_fx.forecasting.config import ROOT
        source=ROOT/'data/training/cache/models--mistralai--Timestral-5M/snapshots'/SOURCE_REVISION
        actual=ROOT/'data/training/runs/57c6293d-3033-4c63-b52b-055f3cd15f62/candidate'
        if not source.exists() or not actual.exists():self.skipTest('Local proof artifacts required')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'data/training/runs/fixture';(folder/'candidate').mkdir(parents=True)
            cache=root/'data/training/cache/models--mistralai--Timestral-5M/snapshots'/SOURCE_REVISION;cache.mkdir(parents=True)
            for name in ('config.json','model.safetensors','LICENSE'):
                if (source/name).exists():shutil.copy2(source/name,cache/name)
                if (actual/name).exists():shutil.copy2(actual/name,folder/'candidate'/name)
            full=load_file(folder/'candidate/model.safetensors')
            save_file({k[5:]:t for k,t in full.items() if k.startswith('head.')},folder/'best-head.safetensors')
            report=dict(partitions={p:dict(gate=dict(passed=True)) for p in ('validation','test')},selection=dict(candidate_sha256=file_hash(folder/'candidate/model.safetensors')))
            (folder/'forecast-report.json').write_text(json.dumps(report));(folder/'simulation-report.json').write_text(json.dumps(dict(gate=dict(passed=True))))
            adapter=PairedStudyAdapter('fixture');adapter._options=lambda:dict(root=str(root),run_id='fixture')
            try:
                result=adapter.forecast((1.1+torch.arange(256)*.00001).tolist())
                self.assertEqual(len(result['source']),12);self.assertEqual(len(result['candidate']),12)
                self.assertNotEqual(result['source'],result['candidate'])
            finally:adapter.close()
