"""Small versioned outcome filter; fitting is isolated from temporal evaluation."""

from __future__ import annotations

import hashlib
import json
import math

from .agent_strategy import FEATURES, SPEC_HASH

PROTOCOL = dict(
    version="agent-temporal-v1",
    fractions=[0.6, 0.2, 0.2],
    minimum_development=100,
    minimum_validation=30,
    minimum_final=30,
    minimum_class=10,
    minimum_calibration_class=5,
    probability_thresholds=[0.55, 0.60, 0.65],
    minimum_trades_validation=20,
    minimum_trades_final=20,
    minimum_profit_factor=1.1,
    maximum_drawdown_pct=5.0,
    required_brier_improvement=0.05,
    initial_equity=10000.0,
    risk_per_trade_pct=0.5,
    max_daily_loss_pct=2.0,
    max_trades_per_day=5,
    candidate_scope="retrospective_paper_only",
    live_promotion=False,
    timestral_baseline=dict(
        schedule="One candidate per closed M5 bar with UTC open minute zero",
        direction="Sign of 3-bar median forecast versus reference close",
        stop_atr=1.5,
        reward_multiple=2.5,
        max_holding_bars=12,
        context_regime_gate=False,
        scope="independent_research_benchmark_only",
    ),
)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def fit_model(samples):
    import numpy as np

    samples = sorted(samples, key=lambda s: s["entry_at"])
    if len(samples) < PROTOCOL["minimum_development"]:
        raise ValueError("INSUFFICIENT_DEVELOPMENT_SAMPLES_OR_CLASSES")
    split = int(0.8 * len(samples))
    boundary = samples[split]["entry_at"]
    fitting = [s for s in samples[:split] if s["exit_at"] < boundary]
    calibration = samples[split:]
    x = np.array([[s["features"][k] for k in FEATURES] for s in fitting], dtype=float)
    y = np.array([s["net_pnl"] > 0 for s in fitting], dtype=float)
    if (
        len(fitting) < 50
        or min(int(y.sum()), int(len(y) - y.sum())) < PROTOCOL["minimum_class"]
    ):
        raise ValueError("INSUFFICIENT_DEVELOPMENT_SAMPLES_OR_CLASSES")
    if not np.isfinite(x).all():
        raise ValueError("NONFINITE_TRAINING_FEATURES")
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1
    z = np.clip((x - mean) / scale, -8, 8)
    weights, bias = np.zeros(len(FEATURES)), 0.0
    for _ in range(900):
        probability = 1 / (1 + np.exp(-np.clip(z @ weights + bias, -30, 30)))
        residual = probability - y
        weights -= 0.08 * (z.T @ residual / len(y) + 0.08 * weights)
        bias -= 0.08 * residual.mean()
    cx = np.array(
        [[s["features"][k] for k in FEATURES] for s in calibration], dtype=float
    )
    if not np.isfinite(cx).all():
        raise ValueError("NONFINITE_CALIBRATION_FEATURES")
    cy = np.array([s["net_pnl"] > 0 for s in calibration], dtype=float)
    if (
        min(int(cy.sum()), len(cy) - int(cy.sum()))
        < PROTOCOL["minimum_calibration_class"]
    ):
        raise ValueError("INSUFFICIENT_CALIBRATION_CLASSES")
    logits = np.clip((cx - mean) / scale, -8, 8) @ weights + bias
    slope, intercept = 1.0, 0.0
    for _ in range(600):
        error = 1 / (1 + np.exp(-np.clip(slope * logits + intercept, -30, 30))) - cy
        slope -= 0.03 * ((error * logits).mean() + 0.1 * (slope - 1))
        intercept -= 0.03 * (error.mean() + 0.1 * intercept)
    result = dict(
        feature_schema=list(FEATURES),
        spec_hash=SPEC_HASH,
        weights=weights.tolist(),
        bias=float(bias),
        mean=mean.tolist(),
        scale=scale.tolist(),
        base_rate=float(y.mean()),
        training_samples=len(fitting),
        calibration=dict(
            method="platt_temporal_development",
            samples=len(calibration),
            slope=float(slope),
            intercept=float(intercept),
            purged=len(samples) - len(fitting) - len(calibration),
        ),
        training_sample_hash=fingerprint([s["sample_id"] for s in samples]),
        training_authorization="candidate_only",
        probability_status="calibrator_fitted_requires_out_of_sample_evaluation",
    )
    result["model_id"] = fingerprint(result)
    return result


def predict(model, features):
    if model["feature_schema"] != list(FEATURES) or model["spec_hash"] != SPEC_HASH:
        raise ValueError("INCOMPATIBLE_AGENT_MODEL")
    value = model["bias"]
    for key, weight, mean, scale in zip(
        FEATURES, model["weights"], model["mean"], model["scale"]
    ):
        if key not in features or not math.isfinite(features[key]):
            raise ValueError("INCOMPLETE_AGENT_FEATURES")
        value += weight * max(-8, min(8, (features[key] - mean) / scale))
    calibration = model["calibration"]
    value = calibration["slope"] * value + calibration["intercept"]
    return 1 / (1 + math.exp(-max(-30, min(30, value))))


def partition_samples(samples, first_boundary, second_boundary):
    result = dict(development=[], validation=[], final=[], purged=[])
    for sample in samples:
        entry, exit = sample["entry_at"], sample["exit_at"]
        phase = (
            "development"
            if entry < first_boundary
            else "validation"
            if entry < second_boundary
            else "final"
        )
        if (phase == "development" and exit >= first_boundary) or (
            phase == "validation" and exit >= second_boundary
        ):
            result["purged"].append(sample)
        else:
            result[phase].append(sample)
    return result


def probability_metrics(model, samples):
    if not samples:
        return dict(samples=0, brier=None, baseline_brier=None, brier_improvement=None)
    pairs = [(predict(model, s["features"]), int(s["net_pnl"] > 0)) for s in samples]
    brier = sum((p - y) ** 2 for p, y in pairs) / len(pairs)
    baseline = sum((model["base_rate"] - y) ** 2 for _, y in pairs) / len(pairs)
    # Report empirical bins; do not relabel raw probabilities as calibrated.
    bins = []
    for low in (0, 0.2, 0.4, 0.6, 0.8):
        group = [
            (p, y) for p, y in pairs if low <= p < low + 0.2 or low == 0.8 and p == 1
        ]
        if group:
            bins.append(
                dict(
                    lower=low,
                    count=len(group),
                    predicted=sum(p for p, _ in group) / len(group),
                    observed=sum(y for _, y in group) / len(group),
                )
            )
    return dict(
        samples=len(samples),
        brier=brier,
        baseline_brier=baseline,
        brier_improvement=(baseline - brier) / max(baseline, 1e-9),
        calibration_bins=bins,
        probability_status="temporal_calibration_out_of_sample_diagnostic",
    )
