"""One small CPU process returns original/candidate forecasts without broker access."""
import json,sys
from pathlib import Path

def main():
    try:
        import torch
        from timestral import TimestralForecaster
        from safetensors.torch import load_file
        from huggingface_hub import snapshot_download
        from .proof import SOURCE_MODEL,SOURCE_REVISION,file_hash
        options=json.loads(sys.stdin.readline());root=Path(options['root']).resolve()
        folder=(root/'data/training/runs'/options['run_id']).resolve()
        if folder.parent!=root/'data/training/runs':raise ValueError('Invalid study path')
        report=json.loads((folder/'forecast-report.json').read_text());financial=json.loads((folder/'simulation-report.json').read_text())
        from .scope import assert_same
        assert_same(report,financial,options.get('scope',dict(symbol='EURUSD',profile_id=None)))
        if not all(report['partitions'][p]['gate']['passed'] for p in ('validation','test')) or not financial['gate']['passed']:raise ValueError('Study lacks retrospective eligibility')
        if file_hash(folder/'candidate/model.safetensors')!=report['selection']['candidate_sha256']:raise ValueError('Study checkpoint changed')
        torch.set_num_threads(1)
        source=snapshot_download(SOURCE_MODEL,revision=SOURCE_REVISION,local_files_only=True,token=False,cache_dir=str(root/'data/training/cache'),allow_patterns=['config.json','model.safetensors','LICENSE'])
        f=TimestralForecaster.from_pretrained(source,device='cpu',max_context=256)
        heads={'source':{k:t.detach().clone() for k,t in f.model.head.state_dict().items()},'candidate':load_file(folder/'best-head.safetensors')}
        exported=load_file(folder/'candidate/model.safetensors')
        if any(not torch.equal(t,exported['head.'+k]) for k,t in heads['candidate'].items()):raise ValueError('Study head changed')
        del exported
        print(json.dumps(dict(ready=True,levels=f.quantile_levels)),flush=True)
        for line in sys.stdin:
            try:
                values=json.loads(line)['values'];result={}
                if not 64<=len(values)<=256:raise ValueError('Context length')
                for name,head in heads.items():
                    f.model.head.load_state_dict(head);result[name]=f.forecast(torch.tensor(values),prediction_length=12).quantiles[0,0].tolist()
                print(json.dumps(dict(ok=True,levels=f.quantile_levels,**result),allow_nan=False),flush=True)
            except Exception as exc:print(json.dumps(dict(ok=False,error_type=type(exc).__name__)),flush=True)
    except Exception as exc:print(json.dumps(dict(ready=False,error_type=type(exc).__name__)),flush=True)

if __name__=='__main__':main()
