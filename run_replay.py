"""Command line entry point for the isolated, read-only research replay."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# This repository entry point adds src before importing the local package.
from aurelia_fx.experience_memory import ExperienceMemory  # noqa: E402
from aurelia_fx.replay import ReplayConfig, run_replay  # noqa: E402
from aurelia_fx.replay_data import load_csv  # noqa: E402
from aurelia_fx.temporal_validation import run_temporal_validation  # noqa: E402
from aurelia_fx.trend import HierarchyConfig  # noqa: E402


def capture_mt5(timeframe: str, count: int, directory: Path) -> Path:
    # Lazy adapter import: offline replay runs on Linux with only stdlib + tzdata.
    from mt5_provider import fetch_history

    history = fetch_history("EURUSD", timeframe, count, include_current=False)
    directory.mkdir(parents=True, exist_ok=True)
    path = (
        directory
        / f"EURUSD-{timeframe}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.csv"
    )
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "spread_pips",
            ),
        )
        writer.writeheader()
        writer.writerows(history["candles"])
    metadata = {
        "symbol": history["symbol"],
        "timeframe": timeframe,
        "source": "mt5_local_closed_bars",
        "count": len(history["candles"]),
        "pip_size": history["pip_size"],
        "closed_bars_only": True,
    }
    path.with_suffix(".metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Aurelia FX: replay causal EURUSD, SQLite e relatorio HTML."
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "--csv",
        type=Path,
        help="UTF-8: timestamp,open,high,low,close,volume,spread_pips",
    )
    inputs.add_argument(
        "--capture-mt5",
        action="store_true",
        help="Captura candles fechados do terminal Windows local",
    )
    parser.add_argument(
        "--timeframe",
        type=str.upper,
        default="M5",
        help="Periodo UTC fixo M<n>, H<n> ou D<n>; captura MT5 depende do terminal",
    )
    parser.add_argument("--count", type=int, default=1500)
    parser.add_argument(
        "--source", default="user_csv_unverified", help="Proveniencia declarada do CSV"
    )
    parser.add_argument("--db", type=Path, default=ROOT / "data/agent_memory.sqlite3")
    parser.add_argument("--output", type=Path, default=ROOT / "data/replays")
    parser.add_argument(
        "--commission-per-million-side",
        type=float,
        default=35.0,
        help="USD por milhao de unidades e por lado; hipotese de pesquisa, nao tarifa da corretora",
    )
    parser.add_argument("--slippage-pips", type=float, default=0.2)
    parser.add_argument("--max-holding-bars", type=int, default=24)
    parser.add_argument(
        "--validate-temporal",
        action="store_true",
        help="60/20/20; reserva janela final por padrao",
    )
    parser.add_argument(
        "--include-holdout",
        action="store_true",
        help="Avalia tambem a janela final com config congelada",
    )
    parser.add_argument(
        "--macro-timeframe", help="Timeframe macro configuravel, por exemplo H1 ou H4"
    )
    parser.add_argument(
        "--context-timeframe", help="Timeframe de contexto configuravel"
    )
    parser.add_argument(
        "--structure-timeframe", help="Timeframe de estrutura configuravel"
    )
    args = parser.parse_args(argv)
    if args.include_holdout and not args.validate_temporal:
        parser.error("--include-holdout exige --validate-temporal")
    try:
        path = (
            capture_mt5(args.timeframe, args.count, ROOT / "data/replay_inputs")
            if args.capture_mt5
            else args.csv
        )
        source = "mt5_local_closed_bars" if args.capture_mt5 else args.source
        dataset = load_csv(path, source=source)
        try:
            code_version = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            if subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip():
                code_version += "+dirty"
        except (OSError, subprocess.CalledProcessError):
            code_version = "unknown"
        default_hierarchy = HierarchyConfig.for_execution(args.timeframe)
        hierarchy = HierarchyConfig(
            args.macro_timeframe or default_hierarchy.macro_timeframe,
            args.context_timeframe or default_hierarchy.context_timeframe,
            args.structure_timeframe or default_hierarchy.structure_timeframe,
            args.timeframe,
        )
        config = ReplayConfig(
            timeframe=args.timeframe,
            hierarchy=hierarchy,
            commission_per_million_side=args.commission_per_million_side,
            slippage_pips=args.slippage_pips,
            max_holding_bars=args.max_holding_bars,
        )
        if args.validate_temporal:
            report = run_temporal_validation(
                dataset,
                config=config,
                memory=ExperienceMemory(args.db),
                output_dir=args.output,
                code_version=code_version,
                include_holdout=args.include_holdout,
            )
            result = {
                key: report[key]
                for key in ("plan_id", "holdout_status", "report_directory")
            }
        else:
            report = run_replay(
                dataset,
                config=config,
                memory=ExperienceMemory(args.db),
                output_dir=args.output,
                code_version=code_version,
            )
            result = {
                key: report[key]
                for key in (
                    "run_id",
                    "bars",
                    "actions",
                    "reasons",
                    "execution",
                    "decision_digest",
                    "execution_digest",
                    "report_directory",
                )
            }
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"Replay interrompido: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
