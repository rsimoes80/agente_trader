"""Read-only HTTP bridge from the local Windows MT5 terminal to the Linux UI."""

from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mt5_provider import fetch_history

HOST = os.environ.get("AURELIA_MT5_BRIDGE_HOST", "192.168.200.1")
PORT = int(os.environ.get("AURELIA_MT5_BRIDGE_PORT", "8769"))
TOKEN = os.environ.get("AURELIA_MT5_BRIDGE_TOKEN", "")


class Handler(BaseHTTPRequestHandler):
    server_version = "AureliaMT5Bridge/1.0"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # Do not log quote payloads or authorization headers.
        print(f"{self.address_string()} {self.command} {urlparse(self.path).path}")

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, {"ok": True, "service": "Aurelia FX MT5 read-only bridge"})
            return
        if path != "/api/mt5/chart":
            self._send(404, {"ok": False, "error": "Rota não encontrada."})
            return
        supplied = self.headers.get("X-Bridge-Token", "")
        if not TOKEN or not hmac.compare_digest(supplied, TOKEN):
            self._send(403, {"ok": False, "error": "Token da ponte inválido."})
            return
        query = parse_qs(urlparse(self.path).query)
        timeframe = query.get("timeframe", ["M5"])[0].upper()
        try:
            count = max(100, min(2_000, int(query.get("count", ["600"])[0])))
            result = fetch_history("EUR/USD", timeframe, count, include_current=True)
            self._send(200, {"ok": True, **result})
        except (RuntimeError, ValueError) as exc:
            self._send(503, {"ok": False, "error": str(exc)})


class BridgeServer(HTTPServer):
    allow_reuse_address = True


def main() -> None:
    if not TOKEN:
        raise RuntimeError(
            "Configure AURELIA_MT5_BRIDGE_TOKEN antes de iniciar a ponte."
        )
    # MT5's local IPC bridge is kept on the server's main thread and serialized.
    server = BridgeServer((HOST, PORT), Handler)
    pid_path = Path(__file__).resolve().parent / "data/mt5_bridge.pid"
    pid_path.write_text(str(os.getpid()), encoding="ascii")
    print(f"Ponte MT5 somente leitura em http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if pid_path.exists() and pid_path.read_text(encoding="ascii").strip() == str(
            os.getpid()
        ):
            pid_path.unlink()


if __name__ == "__main__":
    main()
