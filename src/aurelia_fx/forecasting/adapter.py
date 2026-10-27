"""Persistent local process with hard timeout and resource supervision."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path

from .config import ROOT


class ModelUnavailable(RuntimeError):
    def __init__(self, message, *, code='MODEL_UNAVAILABLE', phase=None, details=None, retry_seconds=30):
        super().__init__(message)
        self.code, self.phase = code, phase
        self.details = details or {}
        self.retry_seconds = retry_seconds


class TimestralAdapter:
    LOW_MEMORY_GRACE_SECONDS = 10
    def __init__(self, config):
        self.config = config
        self.process = None
        self._birth = None
        self.responses = queue.Queue()
        self.lock = threading.Lock()
        self.phase = 'NOT_STARTED'
        self.retry_at = 0.
        self.last_failure = None
        self.cold = True
        self.progress = {}

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                import psutil
                try:
                    parent=psutil.Process(process.pid)
                    children=parent.children(recursive=True) if self._birth is None or parent.create_time()==self._birth else []
                    for child in reversed(children):
                        try:child.kill()
                        except psutil.NoSuchProcess:pass
                except psutil.NoSuchProcess:pass
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()
        self._birth=None

    def _read(self, process, responses):
        try:
            for line in process.stdout:
                try:
                    responses.put(json.loads(line))
                except ValueError:
                    responses.put({"ok": False, "error_type": "InvalidEngineProtocol"})
        finally:
            responses.put({"ok": False, "error_type": "EngineExited"})

    def _wait(self, timeout, *, startup=False):
        import psutil

        started=time.monotonic();deadline=started+timeout
        hard_deadline=started+max(timeout,min(900,5*timeout)) if startup else deadline
        stages=set();bytes_read=0;total_bytes=None
        low_memory_since=None
        while time.monotonic() < deadline:
            try:
                parent=psutil.Process(self.process.pid)
                if self._birth is not None and parent.create_time()!=self._birth:
                    self.close();raise ModelUnavailable('Processo Timestral mudou de identidade.',code='PROCESS_IDENTITY_CHANGED',phase=self.phase)
                rss=sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)] if p.is_running())
                available=psutil.virtual_memory().available
                if available<128*1024**2:
                    low_memory_since=time.monotonic() if low_memory_since is None else low_memory_since
                    elapsed=time.monotonic()-low_memory_since
                    if elapsed>=self.LOW_MEMORY_GRACE_SECONDS:
                        self.close();raise ModelUnavailable('Timestral aguarda memória livre após pressão persistente; nova tentativa automática.',
                            code='WAITING_RESOURCES',phase=self.phase,retry_seconds=60,
                            details=dict(available_mb=round(available/1024**2),minimum_available_mb=128,
                                rss_mb=round(rss/1024**2),pressure_seconds=round(elapsed,1)))
                else:
                    low_memory_since=None
                if rss > self.config.memory_mb * 1024**2:
                    self.close()
                    raise ModelUnavailable("Timestral excedeu limite de memória.",code='MEMORY_LIMIT',phase=self.phase,
                        details=dict(rss_mb=round(rss/1024**2),limit_mb=self.config.memory_mb),retry_seconds=60)
            except psutil.NoSuchProcess:
                raise ModelUnavailable("Processo Timestral encerrou.",code='ENGINE_EXITED',phase=self.phase) from None
            try:
                response=self.responses.get(
                    timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                )
                if response.get('progress'):
                    phase=response.get('phase')
                    if phase not in ('IMPORTING_NUMPY','IMPORTING_TORCH','IMPORTING_SDK',
                        'RESOLVING_ARTIFACT','VERIFYING_ARTIFACT','LOADING_WEIGHTS'):
                        raise ModelUnavailable('Progresso do processo Timestral inválido.',code='INVALID_ENGINE_PROTOCOL',phase=self.phase)
                    self.phase=phase
                    advanced=False
                    if self.phase not in stages:
                        stages.add(self.phase);advanced=True
                    read,total=response.get('bytes_read'),response.get('total_bytes')
                    if (self.phase=='VERIFYING_ARTIFACT' and type(read) is int and type(total) is int
                            and 0<read<=total and read>bytes_read and (total_bytes is None or total_bytes==total)):
                        bytes_read,total_bytes=read,total;advanced=True
                    self.progress=dict(phase=self.phase)
                    if total_bytes:self.progress.update(bytes_read=bytes_read,total_bytes=total_bytes)
                    if startup and advanced:deadline=min(hard_deadline,time.monotonic()+timeout)
                    continue
                return response
            except queue.Empty:
                pass
        self.close()
        raise ModelUnavailable("Timeout Timestral; nova tentativa automática.",code='LOAD_TIMEOUT' if self.phase!='INFERENCE' else 'INFERENCE_TIMEOUT',
            phase=self.phase,details=dict(timeout_seconds=timeout,startup_max_seconds=hard_deadline-started,
                **self.progress))

    def _start(self):
        if time.monotonic()<self.retry_at:
            previous=self.last_failure
            raise ModelUnavailable('Timestral aguardando a próxima tentativa automática.',
                code=previous.code if previous else 'RETRY_PENDING',phase=self.phase,
                details={**(previous.details if previous else {}),'retry_pending':True},
                retry_seconds=max(1,round(self.retry_at-time.monotonic())))
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        python = self.config.python or str(
            ROOT
            / ".venv-timestral"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if not Path(python).is_file():
            raise ModelUnavailable("Ambiente Timestral não instalado.",code='ENVIRONMENT_MISSING',phase='STARTING')
        import psutil
        available=psutil.virtual_memory().available
        if available<128*1024**2:
            raise ModelUnavailable('Timestral aguarda memória livre antes de iniciar o processo.',
                code='WAITING_RESOURCES',phase='MEMORY_ADMISSION',retry_seconds=60,
                details=dict(available_mb=round(available/1024**2),minimum_available_mb=128))
        env = dict(
            os.environ,
            PYTHONIOENCODING="utf-8",
            PYTHONPATH=str(ROOT / "src"),
            OMP_NUM_THREADS=str(self.config.threads),
            TOKENIZERS_PARALLELISM="false",
        )
        self.responses = queue.Queue()
        log_dir = ROOT / "data"
        log_dir.mkdir(exist_ok=True)
        with (log_dir / "timestral-engine.log").open("a", encoding="utf-8") as log:
            self.process = subprocess.Popen(
                self._command(python),
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    | getattr(subprocess, "NORMAL_PRIORITY_CLASS", 0),
            )
        import psutil
        self._birth=psutil.Process(self.process.pid).create_time()
        threading.Thread(
            target=self._read, args=(self.process, self.responses), daemon=True
        ).start()
        self.process.stdin.write(json.dumps(self._options()) + "\n")
        self.process.stdin.flush()
        self.phase='STARTING'
        ready = self._wait(self.config.load_timeout_seconds,startup=True)
        if not ready.get("ready"):
            self.close()
            raise ModelUnavailable(
                "Falha no carregamento Timestral: " + ready.get("error_type", "unknown"),
                code='LOAD_FAILED',phase=self.phase,details=dict(engine_error=ready.get('error_type','unknown'))
            )
        self.phase='READY'
        self.progress=dict(phase='READY')
        self.cold=True

    def _command(self,python):return [python,'-u',str(ROOT/'run_timestral.py'),'--engine']
    def _options(self):return asdict(self.config)

    def warmup(self):
        if not self.config.enabled:
            raise ModelUnavailable("Timestral desabilitado.")
        with self.lock:
            self._start()

    def forecast(self, values):
        return self._request({"values": values})

    def forecast_batch(self, contexts):
        if not 1 <= len(contexts) <= 8:
            raise ValueError(
                "Timestral aceita de 1 a 8 contextos por lote de inferência."
            )
        return self._request({"batch_values": contexts})["batch_outputs"]

    def _request(self, request):
        if not self.config.enabled:
            raise ModelUnavailable("Timestral desabilitado.")
        with self.lock:
            try:
                self._start()
                self.process.stdin.write(json.dumps(request, allow_nan=False) + "\n")
                self.process.stdin.flush()
                self.phase='INFERENCE'
                self.progress=dict(phase='INFERENCE')
                # Mapped weights are faulted into RAM on their first forward
                # pass. Use the bounded loading budget for that warm-up only.
                result = self._wait(max(self.config.timeout_seconds,self.config.load_timeout_seconds)
                    if self.cold else self.config.timeout_seconds)
                if not result.get("ok"):
                    raise ModelUnavailable(
                        "Inferência Timestral indisponível: "
                        + result.get("error_type", "unknown"),code='INFERENCE_FAILED',phase=self.phase,
                        details=dict(engine_error=result.get('error_type','unknown'))
                    )
                self.phase='READY';self.retry_at=0.;self.last_failure=None;self.cold=False
                return result
            except (OSError, ValueError, ModelUnavailable) as exc:
                self.close()
                if isinstance(exc, ModelUnavailable):
                    if not exc.details.get('retry_pending'):
                        self.retry_at=time.monotonic()+exc.retry_seconds;self.last_failure=exc
                    raise
                failure=ModelUnavailable("Falha no processo local Timestral.",code='PROCESS_IO_ERROR',phase=self.phase,
                    details=dict(error_type=type(exc).__name__))
                self.retry_at=time.monotonic()+failure.retry_seconds;self.last_failure=failure
                raise failure from None
