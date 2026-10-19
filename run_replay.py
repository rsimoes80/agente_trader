"""Command line entry point for the isolated, read-only research replay."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.replay import ReplayConfig, run_replay
from aurelia_fx.replay_data import TIMEFRAMES, load_csv


def capture_mt5(timeframe: str, count: int, directory: Path) -> Path:
    # Lazy adapter import: offline replay runs on Linux with only stdlib + tzdata.
    from mt5_provider import fetch_history
    history = fetch_history("EURUSD", timeframe, count, include_current=False)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"EURUSD-{timeframe}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.csv"
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("timestamp", "open", "high", "low", "close", "volume", "spread_pips"))
        writer.writeheader()
        writer.writerows(history["candles"])
    metadata = {"symbol": history["symbol"], "timeframe": timeframe, "source": "mt5_local_closed_bars",
                "count": len(history["candles"]), "pip_size": history["pip_size"], "closed_bars_only": True}
    path.with_suffix(".metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Aurelia FX: replay causal EURUSD, SQLite e relatorio HTML.")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--csv", type=Path, help="UTF-8: timestamp,open,high,low,close,volume,spread_pips")
    inputs.add_argument("--capture-mt5", action="store_true", help="Captura candles fechados do terminal Windows local")
    parser.add_argument("--timeframe", choices=tuple(TIMEFRAMES), default="M5")
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument("--source", default="user_csv_unverified", help="Proveniencia declarada do CSV")
    parser.add_argument("--db", type=Path, default=ROOT / "data/agent_memory.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "data/replays")
    args = parser.parse_args(argv)
    try:
        path = capture_mt5(args.timeframe, args.count, ROOT / "data/replay_inputs") if args.capture_mt5 else args.csv
        source = "mt5_local_closed_bars" if args.capture_mt5 else args.source
        dataset = load_csv(path, source=source)
        try:
            code_version = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                text=True, stderr=subprocess.DEVNULL).strip()
            if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
                code_version += "+dirty"
        except (OSError, subprocess.CalledProcessError):
            code_version = "unknown"
        config = ReplayConfig(timeframe=args.timeframe)
        report = run_replay(dataset, config=config, memory=ExperienceMemory(args.db),
                            output_dir=args.output, code_version=code_version)
        print(json.dumps({key: report[key] for key in
            ("run_id", "bars", "actions", "reasons", "decision_digest", "report_directory")}, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"Replay interrompido: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
