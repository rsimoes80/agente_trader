"""Frozen research setup joining causal V4 context and Timestral features.

EMA/ATR thresholds are engineering hypotheses, not formulas attributed to books.
This separate strategy does not change the legacy V4 strategy or authorize orders.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from statistics import mean

from .domain import Candidate

STRATEGY_ID = "agent_pullback_timestral"
VERSION = "research-v3-counterfactual-context"
FEATURES = (
    "side",
    "body_atr",
    "distance_ema_atr",
    "stop_atr",
    "spread_stop",
    "h1_aligned",
    "h1_direction_known",
    "h4_aligned",
    "h4_direction_known",
    "d1_aligned",
    "evidence_conflicted",
    "volume_ratio",
    "range_atr",
    "session_london",
    "session_new_york",
    "regime_trend",
    "regime_range",
    "regime_transition",
    "regime_unknown",
    "forecast_3_atr",
    "forecast_6_atr",
    "forecast_12_atr",
    "uncertainty_3_atr",
    "uncertainty_6_atr",
    "uncertainty_12_atr",
)
SPEC = dict(
    strategy_id=STRATEGY_ID,
    version=VERSION,
    calendar="thinkmarkets-forex-v1; closed UTC buckets over tradable slots; documented weekly hours",
    symbol="EURUSD",
    timeframe="M5",
    hierarchy=dict(macro="H4", context="H1", structure="M15", execution="M5"),
    extra_context="D1 UTC closed buckets; 20-bar directional return feature",
    direction_policy="With H1 context trend; macro H4 and daily disagreement retained as explicit features for research",
    research_candidates="Fixed pullback pattern across observed regimes; ineligible regimes never authorize production entries",
    research_direction_fallback="Sign of past EMA21 slope only when H1 direction is unavailable; explicitly flagged",
    regimes=["TREND"],
    ema_period=21,
    atr_period=14,
    reward_multiple=2.5,
    minimum_stop_atr=0.5,
    stop_buffer_atr=0.2,
    max_holding_bars=12,
    slippage_pips=0.2,
    commission_per_million_side=35.0,
    source_review="docs/referencias_v3.md: Pring PDF 16-17,68-71; Brooks PDF 127,135,233",
    source_scope="Reviewed concepts only; numeric setup is a research hypothesis.",
    feature_schema=list(FEATURES),
    automatic_live_promotion=False,
)
SPEC_HASH = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


def propose_pullback(
    snapshot, history, *, daily_history=None, pip_size=0.0001, research=False
):
    """A closed trigger after a correction, eligible only in a confirmed trend."""
    if len(history) < 64:
        return None, "INSUFFICIENT_CONTEXT"
    if daily_history is None or len(daily_history) < 20:
        return None, "DAILY_CONTEXT_INSUFFICIENT"
    if snapshot.regime != "TREND" and not research:
        return None, "REGIME_" + snapshot.regime
    if not snapshot.session:
        return None, "OUTSIDE_SESSION"
    direction = snapshot.context_trend.get("direction")
    h1_known = direction in {"bullish", "bearish"}
    if not h1_known and not research:
        return None, "CONTEXT_TREND_UNRESOLVED"
    if snapshot.invalidating_evidence:
        return None, "INVALIDATING_EVIDENCE"
    previous, current = history[-2:]
    if (current.timestamp - previous.timestamp).total_seconds() != 300:
        return None, "NONCONTIGUOUS_TRIGGER"
    if current.spread_pips is None or current.spread_pips > 2:
        return None, "SPREAD_UNAVAILABLE_OR_HIGH"
    recent = history[-100:]
    alpha = 2 / 22
    ema = recent[0].close
    for bar in recent[1:-1]:
        ema += alpha * (bar.close - ema)
    prior_ema = ema
    ema += alpha * (current.close - ema)
    if not h1_known:
        direction = (
            "bullish"
            if ema > prior_ema
            else "bearish"
            if ema < prior_ema
            else "neutral"
        )
        if direction == "neutral":
            return None, "RESEARCH_DIRECTION_UNRESOLVED"
    ranges = [
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in zip(history[-15:-1], history[-14:])
    ]
    atr = mean(ranges)
    if atr <= 0:
        return None, "VOLATILITY_UNAVAILABLE"
    long = direction == "bullish"
    correction = (
        (previous.close < previous.open or previous.low <= prior_ema)
        if long
        else (previous.close > previous.open or previous.high >= prior_ema)
    )
    trigger = (
        (
            current.close > previous.high
            and current.close > ema
            and current.close > current.open
        )
        if long
        else (
            current.close < previous.low
            and current.close < ema
            and current.close < current.open
        )
    )
    if not correction or not trigger:
        return None, "WAITING_PULLBACK_TRIGGER"
    stop = (
        min(b.low for b in history[-3:]) - 0.2 * atr
        if long
        else max(b.high for b in history[-3:]) + 0.2 * atr
    )
    distance = abs(current.close - stop)
    if distance < 0.5 * atr or distance < 3 * current.spread_pips * pip_size:
        return None, "STOP_TOO_NARROW"
    sign = 1 if long else -1
    target = current.close + sign * 2.5 * distance
    candidate = Candidate(
        "long" if long else "short",
        current.close,
        stop,
        target,
        current.timestamp + timedelta(seconds=600),
        ("confirmed_trend_context", "prior_correction", "closed_trigger"),
    )
    volume_base = mean(b.volume for b in history[-21:-1])
    feature = dict(
        side=sign,
        body_atr=sign * (current.close - current.open) / atr,
        distance_ema_atr=sign * (current.close - ema) / atr,
        stop_atr=distance / atr,
        spread_stop=current.spread_pips * pip_size / distance,
        h1_aligned=float(snapshot.context_trend.get("direction") == direction),
        h1_direction_known=float(h1_known),
        h4_aligned=float(snapshot.macro_trend.get("direction") == direction),
        h4_direction_known=float(
            snapshot.macro_trend.get("direction") in {"bullish", "bearish"}
        ),
        d1_aligned=float(
            sign * (daily_history[-1].close - daily_history[-20].close) > 0
        ),
        evidence_conflicted=float(snapshot.evidence_status == "CONFLICTED"),
        volume_ratio=min(current.volume / volume_base, 5) if volume_base else 0,
        range_atr=(current.high - current.low) / atr,
        session_london=float("london" in snapshot.session),
        session_new_york=float("new_york" in snapshot.session),
        regime_trend=float(snapshot.regime == "TREND"),
        regime_range=float(snapshot.regime == "RANGE"),
        regime_transition=float(snapshot.regime == "TRANSITION"),
        regime_unknown=float(snapshot.regime == "UNKNOWN"),
    )
    return dict(
        candidate=candidate,
        features=feature,
        atr=atr,
        reference_close=current.close,
        signal_at=(current.timestamp + timedelta(seconds=300)).isoformat(),
        snapshot=snapshot.as_dict(),
        strategy_id=STRATEGY_ID,
        strategy_version=VERSION,
        spec_hash=SPEC_HASH,
        production_eligible=snapshot.regime == "TREND" and h1_known,
        candidate_scope="counterfactual_research"
        if research
        else "production_proposal",
    ), None


def attach_forecast(setup, output):
    """No future OHLC is accepted here; forecast must come from the past prefix."""
    import math

    quantiles = output["quantiles"]
    feature = dict(setup["features"])
    for horizon in (3, 6, 12):
        low, median, high = quantiles[horizon - 1]
        if (
            not all(math.isfinite(x) and x > 0 for x in (low, median, high))
            or not low <= median <= high
        ):
            raise ValueError("Quantis Timestral inválidos.")
        feature[f"forecast_{horizon}_atr"] = (
            setup["features"]["side"]
            * (median - setup["reference_close"])
            / setup["atr"]
        )
        feature[f"uncertainty_{horizon}_atr"] = (high - low) / setup["atr"]
    if set(feature) != set(FEATURES) or not all(
        math.isfinite(feature[k]) for k in FEATURES
    ):
        raise ValueError("Contrato de variáveis do agente incompleto.")
    return feature
