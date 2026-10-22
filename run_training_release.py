"""Explicit activation or rollback of a fully validated local Timestral release."""
import argparse,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['activate','rollback']);p.add_argument('run_id');a=p.parse_args()
    from aurelia_fx.training.releases import activate,rollback
    try:print((activate if a.action=='activate' else rollback)(ROOT,a.run_id))
    except (ValueError,FileNotFoundError) as exc:raise SystemExit(str(exc))
