from pathlib import Path
import os
from aurelia_fx.forecasting.adapter import TimestralAdapter,ModelUnavailable
from aurelia_fx.forecasting.config import ROOT,TimestralConfig

class PairedStudyAdapter(TimestralAdapter):
    def __init__(self,run_id):
        super().__init__(TimestralConfig(enabled=True,device='cpu',threads=1,memory_mb=768,
            python=str(ROOT/'.venv-training'/('Scripts/python.exe' if os.name=='nt' else 'bin/python'))))
        self.run_id=run_id
    def _command(self,python):return [python,'-u','-m','aurelia_fx.training.study_engine']
    def _options(self):return dict(root=str(ROOT),run_id=self.run_id)
    def _start(self):
        import psutil
        if self.process is None and psutil.virtual_memory().available<384*1024**2:raise ModelUnavailable('Study waiting for free RAM')
        super()._start()
