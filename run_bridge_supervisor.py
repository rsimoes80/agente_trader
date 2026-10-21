"""Health supervision for this project's read-only Windows MT5 bridge."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

from run_agent_supervisor import kill_owned_tree

ROOT=Path(__file__).resolve().parent
SERVICE='Aurelia FX MT5 read-only bridge'
HEALTH_URL='http://{}:{}/health'.format(os.environ.get('AURELIA_MT5_BRIDGE_HOST','192.168.200.1'),os.environ.get('AURELIA_MT5_BRIDGE_PORT','8769'))


def health():
    try:
        with urllib.request.urlopen(HEALTH_URL,timeout=2) as response:
            value=json.load(response)
            return value.get('ok') is True and value.get('service')==SERVICE
    except (OSError,ValueError):return False


class ExistingBridge:
    def __init__(self,process):self.process=process;self.pid=process.pid
    def poll(self):
        import psutil
        try:return None if self.process.is_running() and self.process.status()!=psutil.STATUS_ZOMBIE else 0
        except psutil.NoSuchProcess:return 0
    def wait(self,timeout):return self.process.wait(timeout=timeout)


def existing_bridge():
    """Adopt only a live process whose command and directory match this project."""
    import psutil
    try:
        pid=int((ROOT/'data/mt5_bridge.pid').read_text(encoding='ascii').strip())
        process=psutil.Process(pid)
        if Path(process.cwd()).resolve()!=ROOT:return None
        if not any(Path(arg).resolve()==ROOT/'mt5_bridge.py' for arg in process.cmdline()[1:] if arg.endswith('mt5_bridge.py')):return None
        return ExistingBridge(process)
    except (OSError,ValueError,psutil.Error):return None


def supervise_once(*,probe=health,find=existing_bridge,popen=subprocess.Popen,
                   now=time.monotonic,sleep=time.sleep,kill=kill_owned_tree,limit=120):
    process=find()
    if process is None:
        # A healthy listener without verified ownership must never be terminated.
        if probe():return 'external_healthy'
        process=popen([sys.executable,'-u',str(ROOT/'mt5_bridge.py')],cwd=ROOT,
                      env=dict(os.environ,PYTHONIOENCODING='utf-8'),
                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    last_healthy=now()
    print('Bridge supervisor: health monitoring active.',flush=True)
    while process.poll() is None:
        if probe():last_healthy=now()
        if now()-last_healthy>=limit:
            print('Bridge supervisor: health deadline exceeded; restarting the read-only bridge.',flush=True)
            kill(process)
            return 'stalled'
        sleep(5)
    return 'exited'


def main():
    if not os.environ.get('AURELIA_MT5_BRIDGE_TOKEN'):
        raise RuntimeError('Token da ponte não configurado.')
    while True:
        try:supervise_once()
        except Exception as exc:
            print('Bridge supervisor recovery:',type(exc).__name__,flush=True)
        time.sleep(5)


if __name__=='__main__':main()
