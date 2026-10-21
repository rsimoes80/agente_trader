"""Restart failed/stalled workers without changing the durable session intent."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent
PROGRESS='AFX_AGENT_PROGRESS:'


class ProgressClock:
    def __init__(self,now=time.monotonic):
        self.now=now
        self.lock=threading.Lock()
        self.last=now()

    def observe(self,line):
        if line.startswith(PROGRESS):
            with self.lock:self.last=self.now()
            return True
        return False

    def stalled(self,limit):
        with self.lock:return self.now()-self.last>=limit


def stall_limit():
    # Loading plus inference may legitimately take longer than one request.
    sys.path.insert(0,str(ROOT/'src'))
    try:
        from aurelia_fx.forecasting.config import load_config
        config=load_config()
        return max(600,config.load_timeout_seconds+config.timeout_seconds+120)
    except Exception:
        return 600


def kill_owned_tree(process):
    """Only the process we spawned and its descendants, including venv launchers."""
    import psutil
    if process.poll() is not None:return
    try:
        root=psutil.Process(process.pid)
        descendants=root.children(recursive=True)
        for child in reversed(descendants):
            try:child.kill()
            except psutil.NoSuchProcess:pass
        try:root.kill()
        except psutil.NoSuchProcess:pass
    except psutil.NoSuchProcess:pass
    process.wait(timeout=15)


def supervise_once(*,limit=None,popen=subprocess.Popen,clock_factory=ProgressClock,
                   sleep=time.sleep,kill=kill_owned_tree):
    progress=clock_factory()
    env=dict(os.environ,AURELIA_AGENT_SUPERVISED='1',PYTHONIOENCODING='utf-8')
    process=popen([sys.executable,'-u',str(ROOT/'run_agent.py')],cwd=ROOT,env=env,
                  stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,
                  encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    def read():
        for line in process.stdout:
            if not progress.observe(line):print(line,end='',flush=True)
    reader=threading.Thread(target=read,daemon=True)
    reader.start()
    limit=stall_limit() if limit is None else limit
    try:
        while process.poll() is None:
            if progress.stalled(limit):
                print('Agent watchdog: progress deadline exceeded; restarting worker for reconciliation.',flush=True)
                kill(process)
                return 'stalled'
            sleep(2)
        print('Agent worker exited; restart scheduled. Exit code:',process.returncode,flush=True)
        return 'exited'
    finally:
        if process.poll() is None:kill(process)
        reader.join(timeout=2)
        if not reader.is_alive():process.stdout.close()


def main():
    while True:
        try:supervise_once()
        except Exception as exc:
            # No exception text: connection strings must never reach this log.
            print('Agent supervisor recovery:',type(exc).__name__,flush=True)
        time.sleep(10)


if __name__=='__main__':main()
