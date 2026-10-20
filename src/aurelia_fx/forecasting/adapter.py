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
        self.responses = queue.Queue()
        self.lock = threading.Lock()

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream:
                    stream.close()

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
                rss = psutil.Process(self.process.pid).memory_info().rss
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
                [python, "-u", str(ROOT / "run_timestral.py"), "--engine"],
                cwd=ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        threading.Thread(
            target=self._read, args=(self.process, self.responses), daemon=True
        ).start()
        self.process.stdin.write(json.dumps(asdict(self.config)) + "\n")
        self.process.stdin.flush()
        ready = self._wait(self.config.load_timeout_seconds)
        if not ready.get("ready"):
            self.close()
            raise ModelUnavailable(
                "Falha no carregamento Timestral: " + ready.get("error_type", "unknown")
            )

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
