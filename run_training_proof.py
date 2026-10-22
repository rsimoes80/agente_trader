"""Prepare or execute the small CPU proof in .venv-training only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def stop_owned(child,birth):
    """Include the Windows venv launcher child; never leave its Python orphaned."""
    import psutil
    if child.poll() is not None:return
    try:
        root_process=psutil.Process(child.pid)
        if root_process.create_time()!=birth:raise RuntimeError('Training process identity changed')
        for process in reversed(root_process.children(recursive=True)):
            try:process.kill()
            except psutil.NoSuchProcess:pass
        try:root_process.kill()
        except psutil.NoSuchProcess:pass
    except psutil.NoSuchProcess:pass
    child.wait(timeout=15)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare',action='store_true',help='Download pinned 5M weights into the training cache')
    parser.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--output',help=argparse.SUPPRESS)
    args=parser.parse_args()
    import psutil
    expected=ROOT/'.venv-training'
    if Path(sys.prefix).resolve()!=expected.resolve():
        raise SystemExit('Use .venv-training/Scripts/python.exe for this proof')
    os.environ['HF_HOME']=str(ROOT/'data/training/hf-home')
    os.environ['HF_XET_CACHE']=str(ROOT/'data/training/cache/xet')
    from aurelia_fx.training.proof import prepare,run
    if args.prepare:
        print(json.dumps(dict(prepared=str(prepare(ROOT)))));return
    if args.worker:
        process=psutil.Process()
        process.nice(psutil.IDLE_PRIORITY_CLASS if os.name=='nt' else 10)
        print(json.dumps(run(ROOT,Path(args.output))));return
    if psutil.virtual_memory().available<384*1024**2:
        raise SystemExit('Proof deferred: less than 384 MB RAM available. Trading was not interrupted.')
    output=ROOT/'data/training/proofs'/str(uuid4());output.mkdir(parents=True)
    with (output/'worker.log').open('w',encoding='utf-8') as log:
        child=subprocess.Popen([sys.executable,'-u',str(ROOT/'run_training_proof.py'),'--worker','--output',str(output)],
            cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    birth=psutil.Process(child.pid).create_time()
    started=time.monotonic();peak=0
    try:
        while child.poll() is None:
            try:
                root_process=psutil.Process(child.pid)
                rss=0
                for process in [root_process,*root_process.children(recursive=True)]:
                    try:rss+=process.memory_info().rss
                    except psutil.NoSuchProcess:pass
            except psutil.NoSuchProcess:break
            peak=max(peak,rss)
            if rss>768*1024**2 or psutil.virtual_memory().available<128*1024**2 or time.monotonic()-started>180:
                stop_owned(child,birth)
                raise RuntimeError('Proof stopped at resource limit; active trading services were not touched')
            time.sleep(.2)
        if child.wait(timeout=15)!=0:raise RuntimeError('Proof worker failed; inspect '+str(output/'worker.log'))
        result=json.loads((output/'proof.json').read_text(encoding='utf-8'))
        result.update(peak_process_tree_rss_mb=round(peak/1024**2,1),wall_seconds=round(time.monotonic()-started,2))
        (output/'proof.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(dict(output=str(output),**result)))
    finally:
        if child.poll() is None:stop_owned(child,birth)


if __name__=='__main__':main()
