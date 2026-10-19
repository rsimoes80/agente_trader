"""Chronological, multi-window search for MT5 Forex strategy configurations.

Candidates are ranked on forward validation windows. The newest segment is
reserved as a final gate and is never used for parameter selection or fitting.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtest import run_backtest
from learning import append_outcomes, train_model


PROFILES: dict[str, dict[str, Any]] = {
    "base": {},
    "impulso": {
        "pullback_filter": False, "smc_filter": False, "rsi_filter": False,
        "macd_filter": True, "adx_filter": True, "atr_filter": True,
        "talib_patterns_filter": False, "minimum_confluence": 4, "minimum_risk_reward": 1.5,
    },
    "pullback_pa": {
        "trend_filter": True, "pullback_filter": True, "smc_filter": True,
        "rsi_filter": False, "macd_filter": False, "adx_filter": False,
        "atr_filter": True, "talib_patterns_filter": True,
        "minimum_confluence": 4, "minimum_risk_reward": 1.5,
    },
    "tendencia_relaxada": {
        "trend_filter": True, "pullback_filter": False, "smc_filter": False,
        "rsi_filter": False, "macd_filter": True, "adx_filter": False,
        "atr_filter": False, "talib_patterns_filter": False,
        "minimum_confluence": 2, "minimum_risk_reward": 1.2,
    },
    "padrao_reversao": {
        "trend_filter": False, "pullback_filter": True, "smc_filter": True,
        "rsi_filter": False, "macd_filter": False, "adx_filter": False,
        "atr_filter": False, "talib_patterns_filter": True,
        "minimum_confluence": 2, "minimum_risk_reward": 1.0,
    },
    "qualidade": {
        "trend_filter": True, "pullback_filter": True, "smc_filter": True,
        "rsi_filter": True, "macd_filter": False, "adx_filter": True,
        "atr_filter": False, "talib_patterns_filter": True,
        "minimum_confluence": 5, "minimum_risk_reward": 1.5,
    },
    "momentum": {
        "trend_filter": True, "pullback_filter": False, "smc_filter": True,
        "rsi_filter": False, "macd_filter": True, "adx_filter": False,
        "atr_filter": True, "talib_patterns_filter": False,
        "minimum_confluence": 4, "minimum_risk_reward": 1.5,
    },
    "minimo": {
        "trend_filter": False, "pullback_filter": False, "smc_filter": False,
        "rsi_filter": False, "macd_filter": False, "adx_filter": False,
        "atr_filter": False, "talib_patterns_filter": False,
        "minimum_confluence": 1, "minimum_risk_reward": 1.0,
    },
}

# Parameter neighbors extend the profile ablation to indicator periods and
# thresholds already supported by the analysis engine.
NEIGHBORS: dict[str, dict[str, Any]] = {
    "tendencia_21_50": {"ema_fast": 21, "ema_slow": 50, "adx_min": 20, "minimum_confluence": 4, "minimum_risk_reward": 1.5},
    "tendencia_34_100": {"ema_fast": 34, "ema_slow": 100, "adx_min": 18, "minimum_confluence": 4, "minimum_risk_reward": 1.5},
    "momentum_rsi9": {"ema_fast": 13, "ema_slow": 50, "rsi_period": 9, "adx_period": 14, "adx_min": 22, "minimum_confluence": 4, "minimum_risk_reward": 1.5, "pullback_filter": False, "smc_filter": False, "rsi_filter": True, "macd_filter": True, "adx_filter": True, "atr_filter": True, "talib_patterns_filter": False},
    "pullback_rsi21": {"ema_fast": 21, "ema_slow": 100, "rsi_period": 21, "adx_period": 14, "adx_min": 18, "minimum_confluence": 5, "minimum_risk_reward": 1.5, "trend_filter": True, "pullback_filter": True, "smc_filter": True, "rsi_filter": True, "macd_filter": False, "adx_filter": True, "atr_filter": True, "talib_patterns_filter": True},
    "volatilidade_atr20": {"atr_period": 20, "atr_min_pct": 0.04, "atr_max_pct": 1.0, "stop_atr_buffer": 0.3, "minimum_confluence": 5, "minimum_risk_reward": 1.5, "trend_filter": True, "pullback_filter": True, "smc_filter": True, "rsi_filter": False, "macd_filter": True, "adx_filter": True, "atr_filter": True, "talib_patterns_filter": False},
}

MIN_CANDLES = 10_000
MAX_CANDLES = 100_000
MIN_VALIDATION_TRADES = 30
MIN_HOLDOUT_TRADES = 30
TARGET_WIN_RATE = 70.0
FOLD_COUNT = 3
FOLD_WARMUP = 1_500
FOLD_WIDTH = 8_000


def _metrics_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "trades": metrics["trades"],
        "win_rate_pct": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "net_pnl": metrics["net_pnl"],
        "return_pct": metrics["return_pct"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
    }


def _candidate_configs(config: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name, overrides in (PROFILES | NEIGHBORS).items():
        candidate = {**config, **overrides}
        # Keep fast and slow EMA logically ordered even if a base config changed.
        candidate["ema_fast"] = min(int(candidate["ema_fast"]), int(candidate["ema_slow"]) - 1)
        signature = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        if digest not in seen:
            seen.add(digest)
            candidates.append({"name": name, "config": candidate, "config_hash": digest[:16]})
    return candidates


def _fold_ranges(candle_count: int, holdout_start: int) -> list[tuple[int, int]]:
    validation_start = int(candle_count * 0.40)
    validation_end = holdout_start
    available = validation_end - validation_start
    if available < FOLD_COUNT * (FOLD_WARMUP + 1_000):
        raise ValueError("Historico insuficiente para tres janelas de validacao e um holdout final.")
    width = min(FOLD_WIDTH, available // FOLD_COUNT - FOLD_WARMUP)
    if width < 1_000:
        raise ValueError("Cada janela de validacao precisa conter ao menos 1.000 candles de teste.")
    ranges: list[tuple[int, int]] = []
    for fold_index in range(FOLD_COUNT):
        end = validation_start + int((fold_index + 1) * available / FOLD_COUNT)
        start = max(validation_start, end - width - FOLD_WARMUP)
        ranges.append((start, end))
    return ranges


def _evaluate_fold(candles: list[dict[str, Any]], config: dict[str, Any], start: int, end: int, balance: float) -> dict[str, Any]:
    window = candles[start:end]
    warmup = min(FOLD_WARMUP, max(200, len(window) // 3))
    result = run_backtest(window, config, balance, evaluation_start=warmup)
    metrics = _metrics_summary(result["metrics"])
    metrics["tested_from"] = window[warmup]["timestamp"] if len(window) > warmup else None
    metrics["tested_to"] = window[-1]["timestamp"] if window else None
    return metrics


def _robust_score(folds: list[dict[str, Any]]) -> float:
    """Reward repeatability and penalize deep loss periods; don't rank on hit rate alone."""
    returns = [float(fold["return_pct"]) for fold in folds]
    drawdowns = [float(fold["max_drawdown_pct"]) for fold in folds]
    factors = [min(float(fold["profit_factor"] or 0.0), 3.0) for fold in folds]
    trade_counts = [int(fold["trades"]) for fold in folds]
    median_return = statistics.median(returns)
    worst_return = min(returns)
    median_factor = statistics.median(factors)
    worst_drawdown = max(drawdowns)
    thin_sample_penalty = max(0, 10 - min(trade_counts)) * 0.25
    return round(median_return + 0.35 * median_factor + 0.25 * worst_return - 0.6 * worst_drawdown - thin_sample_penalty, 4)


def _read_scope(path: Path, instrument: str, timeframe: str, source: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)
            and row.get("instrument") == instrument
            and row.get("timeframe") == timeframe
            and row.get("source") == source
            and row.get("evaluation_scope") == "treino"]


def optimize_history(
    candles: list[dict[str, Any]],
    config: dict[str, Any],
    data_dir: Path,
    starting_balance: float,
    source_info: dict[str, Any],
) -> dict[str, Any]:
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"A busca precisa de pelo menos {MIN_CANDLES:,} candles reais do MT5.")
    if len(candles) > MAX_CANDLES:
        raise ValueError(f"A busca aceita no maximo {MAX_CANDLES:,} candles.")

    holdout_start = int(len(candles) * 0.80)
    fold_ranges = _fold_ranges(len(candles), holdout_start)
    trials: list[dict[str, Any]] = []
    for candidate in _candidate_configs(config):
        folds = [
            _evaluate_fold(candles, candidate["config"], start, end, starting_balance)
            for start, end in fold_ranges
        ]
        validation_trades = sum(fold["trades"] for fold in folds)
        trials.append({
            "profile": candidate["name"],
            "config_hash": candidate["config_hash"],
            "config": {key: value for key, value in candidate["config"].items() if config.get(key) != value},
            "folds": folds,
            "validation_trades": validation_trades,
            "validation_win_rate_pct": round(
                sum(fold["win_rate_pct"] * fold["trades"] for fold in folds) / validation_trades, 1
            ) if validation_trades else 0.0,
            "validation_net_pnl": round(sum(fold["net_pnl"] for fold in folds), 2),
            "median_profit_factor": round(statistics.median([float(fold["profit_factor"] or 0.0) for fold in folds]), 2),
            "positive_folds": sum(fold["net_pnl"] > 0 for fold in folds),
            "robust_score": _robust_score(folds),
        })

    eligible = [row for row in trials if row["validation_trades"] >= MIN_VALIDATION_TRADES]
    pool = eligible or trials
    selected = max(pool, key=lambda row: (row["robust_score"], row["median_profit_factor"], row["validation_net_pnl"]))
    selected_candidate = next(item for item in _candidate_configs(config) if item["config_hash"] == selected["config_hash"])
    selected_config = selected_candidate["config"]

    # Fit only on the oldest 60%; neither the three forward-selection windows
    # nor the newest 20% are allowed to teach the candidate model.
    fit_end = int(len(candles) * 0.40)
    training = run_backtest(candles[:fit_end], selected_config, starting_balance)
    history_path = data_dir / "decision_history.json"
    source = "mt5_wf_" + selected["config_hash"]
    new_outcomes = append_outcomes(
        history_path, training["trades"], selected_config["instrument"],
        selected_config["timeframe"], source, "treino",
    )
    model_rows = _read_scope(history_path, selected_config["instrument"], selected_config["timeframe"], source)
    model, learning = train_model(model_rows)

    holdout = run_backtest(
        candles, selected_config, starting_balance, model, evaluation_start=holdout_start,
    )
    holdout_metrics = holdout["metrics"]
    # A strategy/model can be activated only after repeatable forward validation
    # and the untouched final window both meet the stated quality and risk gates.
    validation_quality = (
        selected["validation_trades"] >= MIN_VALIDATION_TRADES
        and selected["positive_folds"] >= 2
        and selected["median_profit_factor"] >= 1.0
        and selected["validation_net_pnl"] > 0
    )
    promoted = bool(
        model is not None
        and learning.get("active")
        and validation_quality
        and holdout_metrics["trades"] >= MIN_HOLDOUT_TRADES
        and holdout_metrics["win_rate_pct"] >= TARGET_WIN_RATE
        and holdout_metrics["profit_factor"] is not None
        and holdout_metrics["profit_factor"] >= 1.0
        and holdout_metrics["net_pnl"] > 0
        and holdout_metrics["max_drawdown_pct"] < selected_config["max_drawdown_pct"]
    )
    learning.update({
        "new_outcomes": new_outcomes,
        "source": source,
        "training_rows_exclude_validation_and_holdout": True,
        "historical_replay_used_prior_model": False,
    })
    holdout["learning"] = learning
    holdout["training_metrics"] = training["metrics"]
    holdout["validation_split_pct"] = 80
    holdout["validation_trades_are_training_data"] = False
    holdout["data_source"] = source_info
    holdout["source_candles"] = len(candles)
    holdout["optimization"] = {
        "selected_profile": selected["profile"],
        "selected_config": {key: value for key, value in selected_config.items() if config.get(key) != value},
        "promoted": promoted,
        "selection_method": "13 perfis e vizinhos de parametros comparados em 3 janelas cronologicas; ranking robusto por retorno, fator de lucro, drawdown e estabilidade.",
        "validation_quality_passed": validation_quality,
        "final_window_is_untouched": True,
        "promotion_rule": {
            "validation_windows": FOLD_COUNT,
            "minimum_validation_trades": MIN_VALIDATION_TRADES,
            "minimum_positive_validation_windows": 2,
            "minimum_holdout_trades": MIN_HOLDOUT_TRADES,
            "minimum_holdout_win_rate_pct": TARGET_WIN_RATE,
            "minimum_profit_factor": 1.0,
            "positive_net_pnl_required": True,
            "adaptive_model_must_be_validated": True,
        },
        "search_trials": sorted(trials, key=lambda row: row["robust_score"], reverse=True),
    }

    if promoted and model is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "promoted": True,
            "source": source,
            "instrument": selected_config["instrument"],
            "timeframe": selected_config["timeframe"],
            "config": selected_config,
            "model": model,
            "learning": learning,
            "holdout_metrics": holdout_metrics,
            "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        temp = data_dir / "decision_model.json.tmp"
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(data_dir / "decision_model.json")

    record = {
        "ran_at_utc": datetime.now(timezone.utc).isoformat(),
        "instrument": selected_config["instrument"],
        "timeframe": selected_config["timeframe"],
        "candles": len(candles),
        "candidate_count": len(trials),
        "validation_windows": selected["folds"],
        "selected_profile": selected["profile"],
        "training": _metrics_summary(training["metrics"]),
        "holdout": _metrics_summary(holdout_metrics),
        "learning": learning,
        "promoted": promoted,
        "trials": sorted(trials, key=lambda row: row["robust_score"], reverse=True),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    temp = data_dir / "strategy_search.json.tmp"
    temp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(data_dir / "strategy_search.json")
    return holdout
