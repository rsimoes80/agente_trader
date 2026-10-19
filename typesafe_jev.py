"""Fail-closed Jev review for a locally confirmed Forex setup."""

from __future__ import annotations

import json
import math
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from analysis import analyze


ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
MIN_APPROVE_PROBABILITY = 0.82
MIN_CONFIDENCE = 0.75


def _market_state(candles: list[dict[str, Any]], config: dict[str, Any], signal: dict[str, Any]) -> dict[str, Any]:
    context = signal.get("analysis", {})
    close = float(candles[-1]["close"])
    pip = float(config["pip_size"])
    recent = candles[-20:]
    ranges = [float(c["high"]) - float(c["low"]) for c in recent]
    current_range = ranges[-1] if ranges else 0.0
    mean_range = sum(ranges[:-1]) / max(len(ranges) - 1, 1)
    volumes = [float(c.get("volume", 0) or 0) for c in recent]
    mean_volume = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    volume_ratio = volumes[-1] / mean_volume if mean_volume > 0 else None
    normalized_bars = []
    scale = max(float(context.get("atr", 0) or 0), pip)
    for candle in candles[-8:]:
        normalized_bars.append({
            key: round((float(candle[key]) - close) / scale, 3)
            for key in ("open", "high", "low", "close")
        })
    return {
        "instrument": config["instrument"],
        "timeframe": config["timeframe"],
        "candle_close_time_utc": str(candles[-1]["timestamp"]),
        "candidate_direction": signal["side"],
        "candidate_entry": signal["entry"],
        "candidate_stop": signal["stop"],
        "candidate_target": signal["target"],
        "planned_risk_reward": signal["risk_reward"],
        "technical_filter_score": signal["score"],
        "technical_filter_count": signal["score_total"],
        "confirmed_conditions": context.get("confluences", {}),
        "talib_candlestick_patterns": {
            "recognized_patterns": context.get("padroes_candle", {}),
            "candidate_direction": signal["side"],
            "filter_enabled": config.get("talib_patterns_filter", False),
            "interpretation": "TA-Lib pattern outputs are candidate evidence only; reliability depends on preceding trend, location, volatility, structure, and the closed-candle context.",
        },
        "pullback_quality": context.get("pullback", {}),
        "structure": {"bos": context.get("bos"), "liquidity_sweep": context.get("liquidity_sweep")},
        "indicators": {
            "rsi": context.get("rsi"),
            "adx": context.get("adx"),
            "atr": context.get("atr"),
            "atr_percent_of_price": context.get("atr_pct"),
            "ema_fast": context.get("ema_fast"),
            "ema_slow": context.get("ema_slow"),
            "macd_direction_confirmed": context.get("confluences", {}).get("macd"),
        },
        "market_conditions": {
            "last_candle_range_vs_previous_19_average": round(current_range / mean_range, 3) if mean_range else None,
            "provider_tick_volume_vs_previous_19_average": round(volume_ratio, 3) if volume_ratio is not None else None,
            "volume_is_provider_specific_not_consolidated_fx_volume": True,
            "last_8_candles_in_atr_units_from_latest_close": normalized_bars,
        },
    }


def review_entry(candles: list[dict[str, Any]], config: dict[str, Any], api_key: str) -> dict[str, Any]:
    """Ask Jev to approve or defer one already-gated candidate; never place orders."""
    if not candles:
        raise ValueError("Ainda não há candle fechado para revisar com o Jev.")
    signal = analyze(candles[-1500:], config)
    if signal.get("signal") not in {"BUY", "SELL"}:
        return {
            "action": "wait",
            "reason": "A estratégia técnica local ainda não confirmou uma entrada; nenhuma chamada ao Jev foi feita.",
            "local_signal": signal.get("signal", "WAIT"),
            "local_analysis": signal,
            "model": None,
        }

    body = {
        "state": _market_state(candles[-1500:], config, signal),
        "model": MODEL,
        "questions": {
            "entry_review": {
                "type": "choice",
                "instructions": (
                    "Review this closed-candle Forex candidate as an independent market-context veto. "
                    "Assess the supplied TA-Lib candlestick pattern(s): their direction must agree with the candidate, "
                    "and their location after the preceding price movement must make sense. A pattern alone is never "
                    "sufficient. If no direction-aligned recognized pattern is supplied, or its context is weak, "
                    "choose defer. Choose approve only when the pattern context, trend, volatility, pullback, structure, trigger, and planned risk/reward "
                    "are mutually coherent and the evidence is sufficient. Choose defer for unstable, contradictory, "
                    "incomplete, stretched, or ambiguous conditions. Do not predict guaranteed profit. Do not change "
                    "the candidate direction, prices, position size, or hard risk limits."
                ),
                "criteria": {
                    "approve": "The stated evidence is coherent and the candidate is not contradicted by the supplied market context.",
                    "defer": "Evidence is weak, mixed, unstable, incomplete, or the candidate is too ambiguous to justify an entry.",
                },
            }
        },
    }
    request = Request(
        ENDPOINT,
        data=json.dumps(body, separators=(",", ":"), allow_nan=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15, context=ssl.create_default_context()) as response:
            result = json.loads(response.read(1_000_000).decode("utf-8"))
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise ValueError("A chave TypeSafe foi recusada. Confira a chave salva no painel.") from None
        if exc.code in {429, 529}:
            raise ValueError("O serviço Jev está temporariamente ocupado. A decisão foi bloqueada; tente mais tarde.") from None
        raise ValueError(f"O serviço Jev respondeu com HTTP {exc.code}. A decisão foi bloqueada.") from None
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise ValueError("Não foi possível obter uma resposta válida do Jev. A decisão foi bloqueada.") from None

    answer = result.get("answers", {}).get("entry_review", {})
    probabilities = answer.get("probabilities", {})
    choice = answer.get("choice")
    approve_probability = probabilities.get("approve", 0.0)
    confidence = answer.get("confidence", 0.0)
    if (
        answer.get("type") != "choice"
        or choice not in {"approve", "defer"}
        or not isinstance(approve_probability, (int, float))
        or not math.isfinite(approve_probability)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
    ):
        raise ValueError("Resposta do Jev fora do formato esperado. A decisão foi bloqueada.")

    allowed = (
        choice == "approve"
        and approve_probability >= MIN_APPROVE_PROBABILITY
        and confidence >= MIN_CONFIDENCE
    )
    usage = result.get("usage", {})
    return {
        "action": "approve" if allowed else "wait",
        "reason": "Revisão independente aprovada; limites técnicos e de risco continuam obrigatórios." if allowed else "Jev pediu espera ou não atingiu os limiares definidos; entrada bloqueada.",
        "local_signal": signal["signal"],
        "side": signal["side"],
        "local_score": signal["score"],
        "local_score_total": signal["score_total"],
        "entry": signal["entry"],
        "stop": signal["stop"],
        "target": signal["target"],
        "jev_choice": choice,
        "approve_probability": round(float(approve_probability), 4),
        "confidence": round(float(confidence), 4),
        "model": result.get("model", MODEL),
        "usage": usage,
        "live_order_sent": False,
    }
