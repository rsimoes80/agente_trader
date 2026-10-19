"""Explainable, configurable FX confluence analysis derived from the supplied guides."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import talib


def _rsi(close: pd.Series, period: int) -> pd.Series:
    values = talib.RSI(close.to_numpy(dtype=float), timeperiod=period)
    return pd.Series(values, index=close.index).fillna(50)


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    values = talib.ATR(
        frame.high.to_numpy(dtype=float),
        frame.low.to_numpy(dtype=float),
        frame.close.to_numpy(dtype=float),
        timeperiod=period,
    )
    return pd.Series(values, index=frame.index)


def _adx(frame: pd.DataFrame, period: int) -> pd.Series:
    values = talib.ADX(
        frame.high.to_numpy(dtype=float),
        frame.low.to_numpy(dtype=float),
        frame.close.to_numpy(dtype=float),
        timeperiod=period,
    )
    return pd.Series(values, index=frame.index).fillna(0)


def _confirmed_swings(values: pd.Series, window: int, high: bool) -> list[tuple[int, float]]:
    """Return pivots only after the right-hand confirmation bars have closed."""
    found: list[tuple[int, float]] = []
    data = values.to_numpy(dtype=float)
    if len(data) <= 2 * window:
        return found
    pivots = data[window : len(data) - window]
    mask = np.ones(len(pivots), dtype=bool)
    for offset in range(1, window + 1):
        left = data[window - offset : len(data) - window - offset]
        right = data[window + offset : len(data) - window + offset]
        mask &= (pivots > left) & (pivots > right) if high else (pivots < left) & (pivots < right)
    indexes = np.flatnonzero(mask) + window
    return [(int(idx), float(data[idx])) for idx in indexes]


def _candlestick_patterns(frame: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Detect TA-Lib patterns on closed bars; they are contextual evidence, not standalone signals."""
    o, h, l, c = (frame[key].to_numpy(dtype=float) for key in ("open", "high", "low", "close"))
    detectors = {
        "engolfo": talib.CDLENGULFING, "martelo": talib.CDLHAMMER,
        "martelo_invertido": talib.CDLINVERTEDHAMMER, "estrela_cadente": talib.CDLSHOOTINGSTAR,
        "estrela_manha": talib.CDLMORNINGSTAR, "estrela_noite": talib.CDLEVENINGSTAR,
        "piercing": talib.CDLPIERCING, "nuvem_negra": talib.CDLDARKCLOUDCOVER,
        "harami": talib.CDLHARAMI,
    }
    found: dict[str, dict[str, Any]] = {}
    for name, detector in detectors.items():
        value = int(detector(o, h, l, c)[-1])
        if value:
            found[name] = {"direcao": "long" if value > 0 else "short", "forca_talib": value}
    return found


def _pullback_quality(frame: pd.DataFrame, swings_high: list[tuple[int, float]], swings_low: list[tuple[int, float]], side: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Score the guide's four pullback checks without forcing a subjective label."""
    if len(swings_high) < 2 or len(swings_low) < 2:
        return {"score": 0, "checks": {"depth": False, "pace": False, "volume": not cfg["volume_filter"], "structure": False}, "depth_pct": None}
    high = swings_high[-1][1]
    low = swings_low[-1][1]
    width = high - low
    if width <= 0:
        return {"score": 0, "checks": {"depth": False, "pace": False, "volume": not cfg["volume_filter"], "structure": False}, "depth_pct": None}
    close = float(frame.close.iloc[-1])
    depth = ((high - close) / width if side == "long" else (close - low) / width) * 100
    depth_ok = cfg["pullback_min_pct"] <= depth <= cfg["pullback_max_pct"]

    lookback = min(5, max(2, len(frame) // 10))
    recent = frame.tail(lookback)
    prior = frame.iloc[max(0, len(frame) - 2 * lookback) : len(frame) - lookback]
    recent_range = float((recent.high - recent.low).mean()) if not recent.empty else 0.0
    prior_range = float((prior.high - prior.low).mean()) if not prior.empty else recent_range
    pace_ok = recent_range <= prior_range

    if cfg["volume_filter"]:
        recent_volume = float(frame.volume.tail(lookback).mean())
        prior_volume = float(frame.volume.iloc[max(0, len(frame) - 2 * lookback) : len(frame) - lookback].mean())
        volume_ok = prior_volume > 0 and recent_volume < prior_volume
    else:
        volume_ok = True

    older_same_side = swings_low[-2][1] if side == "long" else swings_high[-2][1]
    structure_ok = low > older_same_side if side == "long" else high < older_same_side
    checks = {"depth": depth_ok, "pace": pace_ok, "volume": volume_ok, "structure": structure_ok}
    return {"score": sum(checks.values()), "checks": checks, "depth_pct": round(depth, 1)}


def analyze(candles: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """Return a signal plus transparent indicator and confluence diagnostics."""
    required = max(config["ema_slow"], config["atr_period"], config["adx_period"], config["rsi_period"]) + 2 * config["swing_window"] + 5
    if len(candles) < required:
        return {"signal": "WAIT", "score": 0, "required_bars": required, "message": f"Aquecendo indicadores com dados ao vivo: {len(candles)}/{required} candles fechados."}

    frame = pd.DataFrame(candles).copy()
    close_values = frame.close.to_numpy(dtype=float)
    frame["ema_fast"] = talib.EMA(close_values, timeperiod=config["ema_fast"])
    frame["ema_slow"] = talib.EMA(close_values, timeperiod=config["ema_slow"])
    frame["rsi"] = _rsi(frame.close, config["rsi_period"])
    macd, macd_signal, _ = talib.MACD(close_values, fastperiod=12, slowperiod=26, signalperiod=9)
    frame["atr"] = _atr(frame, config["atr_period"])
    frame["adx"] = _adx(frame, config["adx_period"])
    frame["volume"] = pd.to_numeric(frame.get("volume", pd.Series(0, index=frame.index)), errors="coerce").fillna(0)
    patterns = _candlestick_patterns(frame)

    i = len(frame) - 1
    row = frame.iloc[i]
    last_close = float(row.close)
    atr = float(row.atr) if pd.notna(row.atr) else 0.0
    atr_pct = (atr / last_close * 100) if last_close else 0.0
    swing_highs = _confirmed_swings(frame.high, config["swing_window"], high=True)
    swing_lows = _confirmed_swings(frame.low, config["swing_window"], high=False)

    results: dict[str, dict[str, Any]] = {}
    viable: list[tuple[int, str, dict[str, Any]]] = []
    for side in ("long", "short"):
        is_long = side == "long"
        aligned_patterns = {name: detail for name, detail in patterns.items() if detail["direcao"] == side}
        trend_condition = (last_close > row.ema_slow and row.ema_fast > row.ema_slow) if is_long else (last_close < row.ema_slow and row.ema_fast < row.ema_slow)
        trend_ok = trend_condition
        if not config["trend_filter"]:
            trend_ok = True
        rsi_condition = (config["rsi_long_min"] <= row.rsi <= config["rsi_long_max"]) if is_long else (config["rsi_short_min"] <= row.rsi <= config["rsi_short_max"])
        rsi_ok = rsi_condition
        if not config["rsi_filter"]:
            rsi_ok = True
        macd_condition = (macd[-1] > macd_signal[-1]) if is_long else (macd[-1] < macd_signal[-1])
        macd_ok = macd_condition
        if not config["macd_filter"]:
            macd_ok = True
        adx_condition = float(row.adx) >= config["adx_min"]
        adx_ok = adx_condition
        if not config["adx_filter"]:
            adx_ok = True
        atr_condition = config["atr_min_pct"] <= atr_pct <= config["atr_max_pct"]
        atr_ok = atr_condition
        if not config["atr_filter"]:
            atr_ok = True

        pullback = _pullback_quality(frame.iloc[: i + 1], swing_highs, swing_lows, side, config)
        pullback_condition = pullback["score"] >= 3
        if not config["pullback_filter"]:
            pullback = {"score": 4, "checks": {"depth": True, "pace": True, "volume": True, "structure": True}, "depth_pct": None}
        pullback_ok = pullback["score"] >= 3

        high_levels = [level for idx, level in swing_highs if idx < i]
        low_levels = [level for idx, level in swing_lows if idx < i]
        bos = bool(high_levels and last_close > high_levels[-1]) if is_long else bool(low_levels and last_close < low_levels[-1])
        previous = frame.iloc[-2]
        sweep = (float(row.low) < float(previous.low) and last_close > float(previous.low)) if is_long else (float(row.high) > float(previous.high) and last_close < float(previous.high))
        structure_condition = bos or sweep
        if not config["smc_filter"]:
            structure_confirmation = True
        else:
            structure_confirmation = bos or sweep

        candle_confirmation = (last_close > float(previous.high) and row.close > row.open) if is_long else (last_close < float(previous.low) and row.close < row.open)
        near_ema = abs(last_close - float(row.ema_fast)) <= max(atr * 0.5, last_close * 0.0001)
        fib_region = bool(pullback["depth_pct"] is not None and config["fib_zone_min_pct"] <= pullback["depth_pct"] <= config["fib_zone_max_pct"])
        region_ok = near_ema or fib_region
        range_window = frame.iloc[max(0, i - 20) : i]
        if range_window.empty:
            wyckoff_ok = False
        else:
            range_low = float(range_window.low.min())
            range_high = float(range_window.high.max())
            wyckoff_ok = (float(row.low) < range_low and last_close > range_low) if is_long else (float(row.high) > range_high and last_close < range_high)
        if config["volume_filter"]:
            prior_volume = float(frame.volume.iloc[max(0, i - 20) : i].mean())
            wyckoff_ok = wyckoff_ok and float(row.volume) > prior_volume if prior_volume > 0 else False
        wyckoff_condition = wyckoff_ok
        if not config["wyckoff_filter"]:
            wyckoff_ok = True
        prior_window = frame.iloc[max(0, i - 20) : i]
        prior_volume_mean = float(prior_window.volume.mean()) if not prior_window.empty else 0.0
        prior_range_mean = float((prior_window.high - prior_window.low).mean()) if not prior_window.empty else 0.0
        volume_ratio = float(row.volume) / prior_volume_mean if prior_volume_mean > 0 else 0.0
        range_expansion = (float(row.high) - float(row.low)) / prior_range_mean if prior_range_mean > 0 else 0.0
        candle_range = max(float(row.high) - float(row.low), 1e-12)
        close_location = (last_close - float(row.low)) / candle_range
        body_atr = abs(float(row.close) - float(row.open)) / max(atr, 1e-12)
        trend_distance_atr = (float(row.ema_fast) - float(row.ema_slow)) / max(atr, 1e-12)
        confluences = {
            "tendencia": bool(trend_ok),
            "pullback": bool(pullback_ok),
            "estrutura_smc": bool(structure_confirmation),
            "gatilho_candle": bool(candle_confirmation or sweep),
            "regiao_confluente": bool(region_ok),
            "rsi": bool(rsi_ok),
            "macd": bool(macd_ok),
            "adx": bool(adx_ok),
            "atr": bool(atr_ok),
            "wyckoff": bool(wyckoff_ok),
            "padrao_candle_talib": bool(aligned_patterns),
        }
        indicator_conditions = {
            "tendencia": bool(trend_condition),
            "pullback": bool(pullback_condition),
            "estrutura_smc": bool(structure_condition),
            "gatilho_candle": bool(candle_confirmation or sweep),
            "regiao_confluente": bool(region_ok),
            "rsi": bool(rsi_condition),
            "macd": bool(macd_condition),
            "adx": bool(adx_condition),
            "atr": bool(atr_condition),
            "wyckoff": bool(wyckoff_condition),
            "padrao_candle_talib": bool(aligned_patterns),
        }
        for setting, key in (
            ("trend_filter", "tendencia"),
            ("pullback_filter", "pullback"),
            ("smc_filter", "estrutura_smc"),
            ("rsi_filter", "rsi"),
            ("macd_filter", "macd"),
            ("adx_filter", "adx"),
            ("atr_filter", "atr"),
            ("wyckoff_filter", "wyckoff"),
            ("talib_patterns_filter", "padrao_candle_talib"),
        ):
            if not config[setting]:
                confluences.pop(key)
        score = sum(confluences.values())
        results[side] = {
            "score": score,
            "confluences": confluences,
            "indicator_conditions": indicator_conditions,
            "pullback": pullback,
            "bos": bos,
            "liquidity_sweep": sweep,
            "atr": round(atr, 6),
            "atr_pct": round(atr_pct, 4),
            "volume_ratio": round(volume_ratio, 4),
            "range_expansion": round(range_expansion, 4),
            "close_location": round(close_location, 4),
            "body_atr": round(body_atr, 4),
            "trend_distance_atr": round(trend_distance_atr, 4),
            "rsi": round(float(row.rsi), 2),
            "adx": round(float(row.adx), 2),
            "ema_fast": round(float(row.ema_fast), 6),
            "ema_slow": round(float(row.ema_slow), 6),
            "trigger_candle": candle_confirmation,
            "padroes_candle": aligned_patterns,
            "near_ema": near_ema,
            "fib_region": fib_region,
        }
        minimum_score = min(config["minimum_confluence"], len(confluences))
        pullback_gate = pullback_ok if config["pullback_filter"] else True
        atr_gate = atr_ok if config["atr_filter"] else True
        adx_gate = adx_ok if config["adx_filter"] else True
        wyckoff_gate = wyckoff_ok if config["wyckoff_filter"] else True
        if score >= minimum_score and candle_confirmation and pullback_gate and atr_gate and adx_gate and wyckoff_gate:
            viable.append((score, side, results[side]))

    if not viable:
        side = "long" if results["long"]["score"] >= results["short"]["score"] else "short"
        chosen = results[side]
        return {
            "signal": "WAIT",
            "score": chosen["score"],
            "score_total": len(chosen["confluences"]),
            "side": side,
            "analysis": chosen,
            "message": "Sem entrada: os filtros configurados ainda não confirmaram o setup.",
        }

    score, side, chosen = max(viable, key=lambda item: item[0])
    entry = last_close
    swing_stop = (swing_lows[-1][1] if swing_lows else float(row.low)) if side == "long" else (swing_highs[-1][1] if swing_highs else float(row.high))
    stop = swing_stop - atr * config["stop_atr_buffer"] if side == "long" else swing_stop + atr * config["stop_atr_buffer"]
    risk_distance = abs(entry - stop)
    target = entry + risk_distance * config["minimum_risk_reward"] if side == "long" else entry - risk_distance * config["minimum_risk_reward"]
    if (side == "long" and stop >= entry) or (side == "short" and stop <= entry) or risk_distance <= 0:
        return {"signal": "WAIT", "score": score, "score_total": len(chosen["confluences"]), "side": side, "analysis": chosen, "message": "Setup bloqueado: stop estrutural inválido para a direção da entrada."}
    return {
        "signal": "BUY" if side == "long" else "SELL",
        "side": side,
        "score": score,
        "score_total": len(chosen["confluences"]),
        "confidence_pct": round(score / len(chosen["confluences"]) * 100),
        "entry": round(entry, 6),
        "stop": round(stop, 6),
        "target": round(target, 6),
        "risk_reward": config["minimum_risk_reward"],
        "risk_scale": 0.5 if chosen["pullback"]["score"] == 3 else 1.0,
        "analysis": chosen,
        "message": "Setup confirmado pelos filtros configurados; aguardar preenchimento e validar risco do instrumento.",
    }
