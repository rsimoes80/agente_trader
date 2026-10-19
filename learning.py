"""Small, regularized, walk-forward outcome learner for candidate filtering."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


FEATURES = (
    "trend", "pullback", "structure", "trigger", "region", "rsi_filter",
    "macd_filter", "adx_filter", "atr_filter", "wyckoff", "rsi_level",
    "adx_level", "atr_level", "pullback_quality", "bos", "liquidity_sweep",
    "relative_tick_volume", "range_expansion", "close_location", "body_atr", "trend_distance_atr",
    "talib_pattern",
)
MIN_ROWS = 100
MIN_HOLDOUT = 20
MIN_CLASS_ROWS = 10
MIN_BRIER_IMPROVEMENT = 0.05
ENTRY_PROBABILITY_FLOOR = 0.55


def features_from_signal(signal: dict[str, Any]) -> dict[str, float]:
    details = signal.get("analysis", {})
    conditions = details.get("indicator_conditions", details.get("confluences", {}))
    pullback = details.get("pullback", {})
    return {
        "trend": float(bool(conditions.get("tendencia", False))),
        "pullback": float(bool(conditions.get("pullback", False))),
        "structure": float(bool(conditions.get("estrutura_smc", False))),
        "trigger": float(bool(conditions.get("gatilho_candle", False))),
        "region": float(bool(conditions.get("regiao_confluente", False))),
        "rsi_filter": float(bool(conditions.get("rsi", False))),
        "macd_filter": float(bool(conditions.get("macd", False))),
        "adx_filter": float(bool(conditions.get("adx", False))),
        "atr_filter": float(bool(conditions.get("atr", False))),
        "wyckoff": float(bool(conditions.get("wyckoff", False))),
        "rsi_level": float(details.get("rsi", 50.0) or 50.0) / 100.0,
        "adx_level": min(float(details.get("adx", 0.0) or 0.0), 60.0) / 60.0,
        "atr_level": min(float(details.get("atr_pct", 0.0) or 0.0), 2.0) / 2.0,
        "pullback_quality": float(pullback.get("score", 0) or 0) / 4.0,
        "bos": float(bool(details.get("bos", False))),
        "liquidity_sweep": float(bool(details.get("liquidity_sweep", False))),
        "relative_tick_volume": min(float(details.get("volume_ratio", 0.0) or 0.0), 5.0) / 5.0,
        "range_expansion": min(float(details.get("range_expansion", 0.0) or 0.0), 5.0) / 5.0,
        "close_location": float(details.get("close_location", 0.5) or 0.0),
        "body_atr": min(float(details.get("body_atr", 0.0) or 0.0), 3.0) / 3.0,
        "trend_distance_atr": float(np.clip(float(details.get("trend_distance_atr", 0.0) or 0.0) / 3.0, -1.0, 1.0)),
        "talib_pattern": float(bool(conditions.get("padrao_candle_talib", False))),
    }


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -30, 30)))


def _fit(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    weights = np.zeros(z.shape[1], dtype=float)
    bias = 0.0
    for _ in range(900):
        probability = _sigmoid(z @ weights + bias)
        error = probability - y
        weights -= 0.08 * ((z.T @ error) / len(y) + 0.08 * weights)
        bias -= 0.08 * float(error.mean())
    return weights, bias, mean, scale


def train_model(rows: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    clean = [row for row in rows if isinstance(row.get("features"), dict) and row.get("outcome") in (0, 1)]
    clean.sort(key=lambda row: str(row.get("entry_time", "")))
    total = len(clean)
    status: dict[str, Any] = {"samples": total, "active": False, "reason": "Aguardando hist\u00f3rico de opera\u00e7\u00f5es encerradas."}
    if total < MIN_ROWS:
        status["required_samples"] = MIN_ROWS
        return None, status

    x = np.array([[float(row["features"].get(name, 0.0)) for name in FEATURES] for row in clean], dtype=float)
    y = np.array([int(row["outcome"]) for row in clean], dtype=float)
    split = max(int(total * 0.8), total - MIN_HOLDOUT)
    split = min(split, total - MIN_HOLDOUT)
    train_y, test_y = y[:split], y[split:]
    status["holdout_samples"] = int(len(test_y))
    if min(int(train_y.sum()), int(len(train_y) - train_y.sum()), int(test_y.sum()), int(len(test_y) - test_y.sum())) < MIN_CLASS_ROWS:
        status["reason"] = "A amostra ainda n\u00e3o tem vit\u00f3rias e perdas suficientes nos per\u00edodos de treino e valida\u00e7\u00e3o."
        return None, status

    weights, bias, mean, scale = _fit(x[:split], train_y)
    predicted = _sigmoid(((x[split:] - mean) / scale) @ weights + bias)
    base_rate = float(train_y.mean())
    model_brier = float(np.mean((predicted - test_y) ** 2))
    baseline_brier = float(np.mean((base_rate - test_y) ** 2))
    improvement = (baseline_brier - model_brier) / max(baseline_brier, 1e-9)
    status.update({
        "holdout_brier": round(model_brier, 4),
        "baseline_brier": round(baseline_brier, 4),
        "holdout_improvement_pct": round(improvement * 100, 1),
    })
    if improvement < MIN_BRIER_IMPROVEMENT:
        status["reason"] = "O modelo ainda n\u00e3o supera a previs\u00e3o-base no per\u00edodo n\u00e3o visto; os indicadores seguem sem pesos aprendidos."
        return None, status

    final_weights, final_bias, final_mean, final_scale = _fit(x, y)
    model = {
        "features": list(FEATURES),
        "weights": final_weights.tolist(),
        "bias": final_bias,
        "mean": final_mean.tolist(),
        "scale": final_scale.tolist(),
    }
    status.update({"active": True, "reason": "Pesos validados em dados cronologicamente posteriores ao treino."})
    return model, status


def predict_win_probability(model: dict[str, Any], features: dict[str, float]) -> float:
    values = np.array([float(features.get(name, 0.0)) for name in model["features"]])
    z = (values - np.array(model["mean"])) / np.array(model["scale"])
    probability = float(_sigmoid(z @ np.array(model["weights"]) + float(model["bias"])))
    return probability if math.isfinite(probability) else 0.5


def append_outcomes(path: Path, trades: list[dict[str, Any]], instrument: str, timeframe: str, source: str = "csv", evaluation_scope: str = "full") -> int:
    if path.exists():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except (OSError, json.JSONDecodeError):
            rows = []
    else:
        rows = []
    known = {row.get("id") for row in rows if isinstance(row, dict)}
    added = 0
    for trade in trades:
        features = trade.get("decision_features")
        if not isinstance(features, dict):
            continue
        # A repeated parameter sweep over the same instrument/time candle must not
        # inflate the learner's apparent sample size.
        signature = "|".join((source, evaluation_scope, instrument, timeframe, str(trade.get("entry_time"))))
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
        if digest in known:
            continue
        rows.append({
            "id": digest,
            "entry_time": trade.get("entry_time", ""),
            "instrument": instrument,
            "timeframe": timeframe,
            "source": source,
            "evaluation_scope": evaluation_scope,
            "features": features,
            "outcome": int(float(trade.get("pnl", 0.0)) > 0),
        })
        known.add(digest)
        added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
    return added
