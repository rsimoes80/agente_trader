"""Collect a rolling MT5 month into PostgreSQL before operational analysis."""

import argparse
import json
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def main():
    from aurelia_fx.historical.collector import collect
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.storage import open_memory
    from mt5_provider import fetch_history

    parser = argparse.ArgumentParser(description="Histórico MT5 EURUSD para PostgreSQL")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--study", action="store_true")
    args = parser.parse_args()
    full_due = args.full
    study_day = None
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    memory = open_memory()
    repo = HistoricalRepository(memory)
    pid_path = ROOT / "data/history.pid"
    try:
        with memory.pool.connection() as lease:
            if not lease.execute(
                "SELECT pg_try_advisory_lock(70616023) AS acquired"
            ).fetchone()["acquired"]:
                print("Coletor histórico já ativo.")
                return 0
            pid_path.write_text(str(os.getpid()), encoding="ascii")
            try:
                while not stop.is_set():
                    lease.execute("SELECT 1")
                    try:
                        current_day = datetime.now(timezone.utc).date().isoformat()
                        baseline = collect(
                            repo,
                            fetch_history,
                            days=args.days,
                            full=full_due,
                            run_study=args.study and study_day != current_day,
                        )
                        state = dict(
                            status=baseline["status"],
                            baseline_id=baseline["baseline_id"],
                            updated_at=datetime.now(timezone.utc).isoformat(),
                            blocker=baseline["blocker"],
                        )
                        print(
                            json.dumps(
                                {
                                    **state,
                                    "bars": {
                                        tf: r["statistics"]["bars"]
                                        for tf, r in baseline["timeframes"].items()
                                    },
                                },
                                ensure_ascii=False,
                            ),
                            flush=True,
                        )
                        success = state["status"] == "ready"
                        if success:
                            full_due = False
                            study_day = current_day
                    except Exception as exc:
                        state = dict(
                            status="unavailable",
                            error_type=type(exc).__name__,
                            message=str(exc)[:180],
                            updated_at=datetime.now(timezone.utc).isoformat(),
                        )
                        print(json.dumps(state, ensure_ascii=False), flush=True)
                        success = False
                    memory.record_project_data(
                        "historical_collection_status", "EURUSD", state
                    )
                    if not args.watch:
                        return 0 if success else 2
                    stop.wait(900 if success else 60)
            finally:
                if not lease.closed:
                    lease.execute("SELECT pg_advisory_unlock(70616023)")
    finally:
        if pid_path.exists() and pid_path.read_text().strip() == str(os.getpid()):
            pid_path.unlink()
        memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
