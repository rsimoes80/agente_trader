"""Restart failed/stalled workers without changing the durable session intent."""
from __future__ import annotations

import os
import json
import socket
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


def reap_verified_orphan(heartbeat,age,limit,*,process_factory=None):
    """An interrupted supervisor may leave a worker holding the database lease."""
    if age is None or age<limit or heartbeat.get('host')!=socket.gethostname():return False
    if not heartbeat.get('pid') or not heartbeat.get('process_created_at'):return False
    import psutil
    try:
        worker=(process_factory or psutil.Process)(int(heartbeat['pid']))
        if worker.create_time()!=heartbeat['process_created_at']:return False
        if Path(worker.cwd()).resolve()!=ROOT:return False
        if not any(Path(arg).resolve()==ROOT/'run_agent.py' for arg in worker.cmdline()[1:] if arg.endswith('run_agent.py')):return False
        for child in reversed(worker.children(recursive=True)):
            try:child.kill()
            except psutil.NoSuchProcess:pass
        worker.kill()
        worker.wait(timeout=15)
        print('Agent watchdog: verified orphan worker stalled; restarting for reconciliation.',flush=True)
        return True
    except psutil.NoSuchProcess:return False


def recover_orphan():
    import psycopg
    from psycopg.rows import dict_row
    sys.path.insert(0,str(ROOT/'src'))
    from aurelia_fx.storage import database_url
    with psycopg.connect(database_url(),connect_timeout=5,autocommit=True,row_factory=dict_row,
                         options='-c statement_timeout=5000',keepalives=1,keepalives_idle=5,
                         keepalives_interval=2,keepalives_count=3,tcp_user_timeout=10000) as c:
        row=c.execute("""SELECT payload_json,
            EXTRACT(EPOCH FROM (clock_timestamp()-recorded_at)) AS age
            FROM project_records WHERE record_type='agent_worker_heartbeat'
            ORDER BY recorded_at DESC LIMIT 1""").fetchone()
    if row:reap_verified_orphan(json.loads(row['payload_json']),float(row['age']),stall_limit())


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
        try:
            supervise_once()
            recover_orphan()
        except Exception as exc:
            # No exception text: connection strings must never reach this log.
            print('Agent supervisor recovery:',type(exc).__name__,flush=True)
        time.sleep(10)


if __name__=='__main__':main()
