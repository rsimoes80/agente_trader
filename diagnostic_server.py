"""Linux diagnostics and read-only observer, served behind the existing Nginx."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from aurelia_fx.diagnostic_observer import DiagnosticObserver  # noqa: E402
from aurelia_fx.diagnostics_repository import DiagnosticsRepository  # noqa: E402
from aurelia_fx.forecasting.repository import ForecastRepository  # noqa: E402
from aurelia_fx.historical.repository import HistoricalRepository  # noqa: E402
from aurelia_fx.learning_audit import build_report  # noqa: E402
from aurelia_fx.operator_auth import authorized  # noqa: E402
from aurelia_fx.platform_control import ObservationController, preflight  # noqa: E402
from aurelia_fx.regime_research import compare_regime_parameters  # noqa: E402
from aurelia_fx.storage import open_memory  # noqa: E402

CSRF = secrets.token_urlsafe(32)
ALLOWED_ORIGINS = {
    "http://192.168.97.221:8097",
    "http://127.0.0.1:8770",
    "http://localhost:8770",
}
STATIC = {
    "/diagnostico": "diagnostics.html",
    "/diagnostico/": "diagnostics.html",
    "/diagnostics.css": "diagnostics.css",
    "/diagnostics.js": "diagnostics.js",
    "/timestral.css": "timestral.css",
    "/timestral-panel.js": "timestral-panel.js",
    "/history.css": "history.css",
    "/history-panel.js": "history-panel.js",
    "/platform.css": "platform.css",
    "/platform-panel.js": "platform-panel.js",
}


class Application:
    def __init__(self):
        self.memory = open_memory()
        self.repo = DiagnosticsRepository(self.memory)
        self.forecasts = ForecastRepository(self.memory)
        self.history = HistoricalRepository(self.memory)
        self.stop = threading.Event()
        self.research_lock = threading.Lock()
        try:
            code_version = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            code_version = "unknown"
        self.observer = DiagnosticObserver(
            self.memory,
            self.repo,
            os.environ.get(
                "AGENTE_DIAGNOSTICS_MT5_URL",
                "http://192.168.97.221:8097/api/mt5/chart?timeframe=M5&count=2000",
            ),
            self.stop,
            code_version,
            historical_repository=self.history,
        )
        token_path = ROOT / "data/platform-operator.token"
        self.operator_token = os.environ.get("AURELIA_OPERATOR_TOKEN") or (
            token_path.read_text(encoding="ascii").strip()
            if token_path.exists()
            else ""
        )
        self.controller = ObservationController(self.memory, self.preflight)
        self.controller.recover()
        self.observer.session_controller = self.controller

    def preflight(self):
        observer = self.observer.status()
        baseline = self.history.latest(
            clock_id=(observer.get("source_clock") or {}).get("clock_id")
        )
        return preflight(
            observer, baseline, disk_free=shutil.disk_usage(ROOT / "data").free
        )

    def learning_worker(self):
        while not self.stop.is_set():
            try:
                report = build_report(self.memory)
                self.memory.record_project_data(
                    "learning_dataset_audit", report["report_id"], report
                )
            except Exception as exc:
                print("Learning audit unavailable:", type(exc).__name__, flush=True)
            self.stop.wait(3600)

    def experiment(self, payload):
        if not self.research_lock.acquire(blocking=False):
            raise ValueError("Já existe uma comparação em execução.")
        try:
            manifest, bars = self.repo.research_candles(str(payload.get("run_id", "")))
            variations = payload.get("variations")
            if not isinstance(variations, list) or not 1 <= len(variations) <= 3:
                raise ValueError("Informe até três configurações candidatas.")
            # Validate small, bounded parameter inputs before recording the frozen plan.
            compare_regime_parameters(manifest, bars[:1], variations)
            job = {
                "job_id": str(uuid4()),
                "run_id": manifest["run_id"],
                "status": "queued",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "variations": variations,
                "dataset_sha256": manifest["dataset_sha256"],
                "partition": "development",
                "automatic_promotion": False,
                "holdout_accessed": False,
            }
            self.memory.record_project_data("offline_regime_job", job["job_id"], job)
        except Exception:
            self.research_lock.release()
            raise

        def work():
            try:
                result = compare_regime_parameters(manifest, bars, variations)
                self.memory.record_project_data(
                    "offline_regime_job",
                    job["job_id"],
                    {
                        **job,
                        "status": "completed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "result": result,
                    },
                )
            except Exception as exc:
                self.memory.record_project_data(
                    "offline_regime_job",
                    job["job_id"],
                    {**job, "status": "failed", "error_type": type(exc).__name__},
                )
            finally:
                self.research_lock.release()

        threading.Thread(
            target=work, name="regime-offline-research", daemon=True
        ).start()
        return job


class Handler(BaseHTTPRequestHandler):
    server_version = "AureliaDiagnostics/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        print(self.command, urlparse(self.path).path, flush=True)

    def send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        args = {key: value[0] for key, value in parse_qs(parsed.query).items()}
        app = self.server.app
        try:
            if path in STATIC:
                body = (ROOT / "static" / STATIC[path]).read_bytes()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/html; charset=utf-8"
                    if path.startswith("/diagnostico")
                    else "text/css; charset=utf-8"
                    if path.endswith(".css")
                    else "application/javascript; charset=utf-8",
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/api/diagnostics/bootstrap":
                self.send(
                    200,
                    {
                        "ok": True,
                        "csrf": CSRF,
                        "runs": app.repo.runs(),
                        "observer": app.observer.status(),
                        "orders_enabled": False,
                        "timezone": "UTC",
                    },
                )
                return
            if path == "/api/diagnostics/platform":
                reports = app.repo.recent_records("learning_dataset_audit", 1)
                self.send(
                    200,
                    dict(
                        ok=True,
                        session=app.controller.status(),
                        preflight=app.preflight(),
                        operator_configured=bool(app.operator_token),
                        learning=reports[0] if reports else None,
                    ),
                )
                return
            if path == "/api/diagnostics/audit":
                self.send(200, {"ok": True, **app.repo.audit(args)})
                return
            if path == "/api/diagnostics/timestral":
                self.send(
                    200,
                    {
                        "ok": True,
                        **app.forecasts.summary(
                            scope=args.get("scope", "live"),
                            source_id=args.get("source_id"),
                        ),
                    },
                )
                return
            if path == "/api/diagnostics/history":
                self.send(200, {"ok": True, **app.history.summary()})
                return
            if path == "/api/diagnostics/samples":
                self.send(
                    200, {"ok": True, **app.repo.samples(args, args.get("offset", 0))}
                )
                return
            if path == "/api/diagnostics/detail":
                self.send(
                    200, {"ok": True, **app.repo.detail(args.get("decision_id", ""))}
                )
                return
            if path == "/api/diagnostics/jobs":
                unique = {}
                for job in app.repo.recent_records("offline_regime_job", 50):
                    unique.setdefault(job["job_id"], job)
                self.send(200, {"ok": True, "jobs": list(unique.values())[:10]})
                return
            if path == "/health":
                self.send(
                    200,
                    {
                        "ok": True,
                        "observer": app.observer.status(),
                        "orders_enabled": False,
                    },
                )
                return
            self.send(404, {"ok": False, "error": "Rota não encontrada."})
        except (ValueError, KeyError, TypeError) as exc:
            self.send(400, {"ok": False, "error": str(exc)[:200]})
        except Exception:
            self.send(
                503,
                {
                    "ok": False,
                    "error": "Diagnóstico indisponível. Verifique o serviço e o PostgreSQL.",
                },
            )

    def do_POST(self):
        try:
            origin = self.headers.get("Origin")
            if (origin and origin not in ALLOWED_ORIGINS) or not hmac.compare_digest(
                self.headers.get("X-Diagnostics-CSRF", ""), CSRF
            ):
                self.send(
                    403,
                    {
                        "ok": False,
                        "error": "Recarregue o painel para renovar a sessão de revisão.",
                    },
                )
                return
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0 < length <= 16000
                or self.headers.get("Content-Type", "").split(";")[0]
                != "application/json"
            ):
                self.send(
                    400, {"ok": False, "error": "Corpo JSON inválido ou grande demais."}
                )
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Objeto JSON obrigatório.")
            path = urlparse(self.path).path
            if path == "/api/diagnostics/platform/command":
                if not authorized(
                    self.headers.get("X-Operator-Token", ""),
                    self.server.app.operator_token,
                ):
                    self.send(
                        403,
                        dict(
                            ok=False,
                            error="Credencial de operador necessária para controlar a sessão.",
                        ),
                    )
                    return
                response = self.server.app.controller.command(
                    payload,
                    self.headers.get("Idempotency-Key", ""),
                    origin=self.client_address[0],
                )
                self.send(200, dict(ok=True, **response))
                return
            if path == "/api/diagnostics/reviews":
                self.send(
                    201, {"ok": True, "review": self.server.app.repo.review(payload)}
                )
                return
            if path == "/api/diagnostics/experiments":
                self.send(202, {"ok": True, "job": self.server.app.experiment(payload)})
                return
            self.send(404, {"ok": False, "error": "Rota não encontrada."})
        except (ValueError, KeyError, TypeError) as exc:
            self.send(400, {"ok": False, "error": str(exc)[:200]})
        except Exception:
            self.send(
                503, {"ok": False, "error": "Não foi possível persistir a solicitação."}
            )


def main():
    app = Application()
    server = ThreadingHTTPServer(("127.0.0.1", 8770), Handler)
    server.daemon_threads = True
    server.app = app

    def stop(*_):
        app.stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    app.observer.start()
    threading.Thread(
        target=app.learning_worker, name="learning-eligibility-audit", daemon=True
    ).start()
    try:
        server.serve_forever()
    finally:
        app.stop.set()
        server.server_close()
        app.memory.close()


if __name__ == "__main__":
    main()
