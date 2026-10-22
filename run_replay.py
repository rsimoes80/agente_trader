"""Command line entry point for the isolated, read-only research replay."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

# This repository entry point adds src before importing the local package.
from aurelia_fx.regime import RegimeConfig  # noqa: E402
from aurelia_fx.replay import ReplayConfig, run_replay  # noqa: E402
from aurelia_fx.replay_data import load_csv  # noqa: E402
from aurelia_fx.storage import open_memory  # noqa: E402
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
        writer.writerows(
            {key: row[key] for key in writer.fieldnames} for row in history["candles"]
        )
    metadata = {
        "symbol": history["symbol"],
        "timeframe": timeframe,
        "source": "mt5_local_closed_bars_utc_v1",
        "csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "source_clock": history.get("source_clock", {}),
        "timestamp_semantics": history.get("timestamp_semantics"),
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
        description="Agente Trader - IA: replay causal EURUSD, PostgreSQL e relatorio HTML."
    )
    parser.add_argument(
        "--timestral",
        action="store_true",
        help="Evidência Timestral isolada; somente PostgreSQL",
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument(
        "--postgres-history",
        action="store_true",
        help="Mês histórico congelado no PostgreSQL, sem CSV",
    )
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
        "--regime-config",
        type=Path,
        help="JSON versionado com parametros explicitos do classificador de regime",
    )
    parser.add_argument(
        "--source", default="user_csv_unverified", help="Proveniencia declarada do CSV"
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="SQLite offline explicito; padrao: PostgreSQL configurado",
    )
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
    memory = None
    forecast_adapter = None
    try:
        if args.postgres_history:
            from aurelia_fx.historical.repository import HistoricalRepository

            if args.db is not None:
                raise ValueError("O arquivo histórico exige o PostgreSQL oficial.")
            memory = open_memory()
            dataset = HistoricalRepository(memory).replay_dataset(
                timeframe=args.timeframe
            )
        else:
            path = (
                capture_mt5(args.timeframe, args.count, ROOT / "data/replay_inputs")
                if args.capture_mt5
                else args.csv
            )
            source = "mt5_local_closed_bars_utc_v1" if args.capture_mt5 else args.source
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
            regime_config=RegimeConfig(
                **json.loads(args.regime_config.read_text(encoding="utf-8"))
            )
            if args.regime_config
            else RegimeConfig(),
            timeframe=args.timeframe,
            hierarchy=hierarchy,
            commission_per_million_side=args.commission_per_million_side,
            slippage_pips=args.slippage_pips,
            max_holding_bars=args.max_holding_bars,
        )
        memory = memory or open_memory(args.db)
        forecast_service = None
        if args.timestral:
            from dataclasses import replace

            from aurelia_fx.forecasting.adapter import TimestralAdapter
            from aurelia_fx.forecasting.config import load_config
            from aurelia_fx.forecasting.repository import ForecastRepository
            from aurelia_fx.forecasting.service import ForecastService

            if args.db is not None or args.timeframe != "M5" or args.include_holdout:
                raise ValueError(
                    "Timestral exige PostgreSQL/M5 e preserva o holdout final."
                )
            forecast_config = replace(load_config(), enabled=True)
            forecast_repo = ForecastRepository(memory)
            if not forecast_repo.installed():
                raise ValueError("Aplique a migration Timestral antes do replay.")
            forecast_adapter = TimestralAdapter(forecast_config)
            forecast_service = ForecastService(
                forecast_config, forecast_repo, forecast_adapter
            )
        if args.validate_temporal:
            report = run_temporal_validation(
                dataset,
                config=config,
                memory=memory,
                output_dir=args.output,
                code_version=code_version,
                include_holdout=args.include_holdout,
                **(
                    {"forecast_service": forecast_service}
                    if forecast_service is not None
                    else {}
                ),
            )
            result = {
                key: report[key]
                for key in ("plan_id", "holdout_status", "report_directory")
            }
        else:
            report = run_replay(
                dataset,
                config=config,
                memory=memory,
                output_dir=args.output,
                code_version=code_version,
                **(
                    {"forecast_service": forecast_service}
                    if forecast_service is not None
                    else {}
                ),
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
    finally:
        if forecast_adapter is not None:
            forecast_adapter.close()
        if memory is not None and hasattr(memory, "close"):
            memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
