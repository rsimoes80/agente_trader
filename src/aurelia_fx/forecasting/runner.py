"""Independent Windows/WSL collector using the existing normalized read-only feed."""

from __future__ import annotations

import argparse
import json
import signal
import threading
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

from ..source_clock import validate_source_clock
from ..storage import open_memory
from .adapter import TimestralAdapter
from .config import ROOT, load_config
from .core import utc
from .repository import ForecastRepository
from .service import ForecastService


def main():
    parser = argparse.ArgumentParser(
        description="Timestral local, evidência somente leitura"
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument(
        "--url",
        default="http://192.168.97.221:8097/api/mt5/chart?timeframe=M5&count=2000",
    )
    args = parser.parse_args()
    config = load_config()
    if not config.enabled and not args.migrate:
        print(json.dumps({"status": "disabled"}))
        return 0
    memory = open_memory()
    repository = ForecastRepository(memory)
    adapter = TimestralAdapter(config)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    lease = None
    pid_path = ROOT / "data/timestral.pid"
    try:
        if args.migrate:
            repository.migrate()
            print("Migration Timestral aplicada.")
            return 0
        if not repository.installed():
            raise RuntimeError("Execute run_timestral.py --migrate antes do coletor.")
        # Session lease ensures only one live collector issues forecasts, even after retries.
        lease = memory.pool.getconn()
        if not lease.execute(
            "SELECT pg_try_advisory_lock(70616022) AS acquired"
        ).fetchone()["acquired"]:
            print(json.dumps({"status": "passive"}))
            return 0
        import os

        pid_path.write_text(str(os.getpid()), encoding="ascii")
        service = ForecastService(config, repository, adapter)
        while not stop.is_set():
            try:
                lease.execute("SELECT 1")
                with urlopen(args.url, timeout=15) as response:
                    raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise ValueError("Resposta da fonte excede limite.")
                data = json.loads(raw)
                now = datetime.now(timezone.utc)
                clock = validate_source_clock(data, now=now)
                if data.get("timeframe") != "M5" or data.get("symbol") not in {
                    "EURUSD",
                    "EUR/USD",
                }:
                    raise ValueError("Fonte deve ser EURUSD M5.")
                rows = data["candles"]
                closed = [
                    r
                    for r in rows
                    if utc(r["timestamp"]) + timedelta(seconds=300) <= now
                ]
                if (
                    not closed
                    or (
                        now - utc(closed[-1]["timestamp"]) - timedelta(seconds=300)
                    ).total_seconds()
                    > 300
                ):
                    raise ValueError(
                        "Dados insuficientes: último candle fechado atrasado."
                    )
                with memory.pool.connection() as c:
                    row = c.execute(
                        """SELECT payload_json::jsonb #>> '{technical_snapshot,regime}' AS regime
                        FROM project_records WHERE record_type IN ('agent_demo_event','agent_paper_event')
                        AND payload_json::jsonb->>'status'='decision'
                        AND payload_json::jsonb->>'clock_id'=%s
                        AND (payload_json::jsonb #>> '{decision,candle}')::timestamptz<=%s
                        AND (payload_json::jsonb #>> '{decision,candle}')::timestamptz>=%s
                        ORDER BY recorded_at DESC LIMIT 1""",
                        (clock["clock_id"],now,now-timedelta(minutes=10)),
                    ).fetchone()
                result = service.observe(
                    closed,
                    as_of=now,
                    scope="live",
                    source_id=clock["clock_id"],
                    regime=row["regime"] if row else "UNKNOWN",
                )
                state = {k: v for k, v in result.items() if k != "predictions"}
                state.update(
                    model=config.model,
                    updated_at=now.isoformat(),
                    orders_enabled=False,
                    last_reference=closed[-1]["timestamp"],
                    mode="observe_only",
                )
            except Exception as exc:
                state = dict(
                    status="unavailable",
                    error_type=type(exc).__name__,
                    message="Fonte ou modelo indisponível; nova tentativa automática.",
                    model=config.model,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    orders_enabled=False,
                )
                if lease.closed or lease.broken:
                    raise RuntimeError(
                        "Conexão do lease perdida; supervisor deve reiniciar coletor."
                    ) from None
            memory.record_project_data("timestral_status", "live", state)
            print(json.dumps(state, ensure_ascii=False), flush=True)
            if args.once:
                return 0 if state["status"] == "observing" else 2
            stop.wait(20)
        return 0
    finally:
        adapter.close()
        if lease is not None:
            if not lease.closed:
                lease.execute("SELECT pg_advisory_unlock(70616022)")
            memory.pool.putconn(lease)
        if pid_path.exists():
            import os

            if pid_path.read_text().strip() == str(os.getpid()):
                pid_path.unlink()
        memory.close()
