"""Export the first immutable EURUSD dataset without loading a model."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))

if __name__=='__main__':
    from aurelia_fx.storage import open_memory
    from aurelia_fx.training.repository import TrainingRepository
    from aurelia_fx.training.dataset import export
    from uuid import uuid4
    m=open_memory();repo=TrainingRepository(m)
    try:
        state=repo.command('START',str(uuid4()));run_id=state['run_id']
        def progress(**kw):
            print(json.dumps(kw),flush=True);repo.publish(run_id,status='DATASET',**kw)
        folder,manifest=export(m,ROOT,progress=progress)
        repo.publish(run_id,status='WAITING_RESOURCES',stage='training',dataset=manifest,
            dataset_directory=str(folder.relative_to(ROOT)),message='Dataset verificado. Preparando ajuste fino.')
        print(json.dumps(dict(directory=str(folder),manifest=manifest)),flush=True)
    finally:m.close()
