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
    pass


class TimestralAdapter:
    def __init__(self, config):
        self.config = config
        self.process = None
        self._birth = None
        self.responses = queue.Queue()
        self.lock = threading.Lock()

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

    def _wait(self, timeout):
        import psutil

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                parent=psutil.Process(self.process.pid)
                if self._birth is not None and parent.create_time()!=self._birth:
                    self.close();raise ModelUnavailable('Processo Timestral mudou de identidade.')
                rss=sum(p.memory_info().rss for p in [parent,*parent.children(recursive=True)] if p.is_running())
                if psutil.virtual_memory().available<128*1024**2:
                    self.close();raise ModelUnavailable('Timestral aguarda memoria livre; processo isolado encerrado.')
                if rss > self.config.memory_mb * 1024**2:
                    self.close()
                    raise ModelUnavailable("Timestral excedeu limite de memória.")
            except psutil.NoSuchProcess:
                raise ModelUnavailable("Processo Timestral encerrou.") from None
            try:
                return self.responses.get(
                    timeout=min(0.1, max(0.001, deadline - time.monotonic()))
                )
            except queue.Empty:
                pass
        self.close()
        raise ModelUnavailable("Timeout Timestral; processo isolado encerrado.")

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        python = self.config.python or str(
            ROOT
            / ".venv-timestral"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        if not Path(python).is_file():
            raise ModelUnavailable("Ambiente Timestral não instalado.")
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        import psutil
        self._birth=psutil.Process(self.process.pid).create_time()
        threading.Thread(
            target=self._read, args=(self.process, self.responses), daemon=True
        ).start()
        self.process.stdin.write(json.dumps(self._options()) + "\n")
        self.process.stdin.flush()
        ready = self._wait(self.config.load_timeout_seconds)
        if not ready.get("ready"):
            self.close()
            raise ModelUnavailable(
                "Falha no carregamento Timestral: " + ready.get("error_type", "unknown")
            )

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
                result = self._wait(self.config.timeout_seconds)
                if not result.get("ok"):
                    raise ModelUnavailable(
                        "Inferência Timestral indisponível: "
                        + result.get("error_type", "unknown")
                    )
                return result
            except (OSError, ValueError, ModelUnavailable) as exc:
                self.close()
                if isinstance(exc, ModelUnavailable):
                    raise
                raise ModelUnavailable("Falha no processo local Timestral.") from None
