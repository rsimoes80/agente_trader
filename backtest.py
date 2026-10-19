"""Conservative candle-by-candle simulator with deterministic risk gates."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

import pandas as pd

from analysis import analyze
from learning import ENTRY_PROBABILITY_FLOOR, features_from_signal, predict_win_probability


def run_backtest(candles: list[dict[str, Any]], config: dict[str, Any], starting_balance: float = 10_000.0, learned_model: dict[str, Any] | None = None, evaluation_start: int = 80) -> dict[str, Any]:
    if len(candles) > 100_000:
        raise ValueError("Limite do backtest: 100.000 candles por execução.")
    if len(candles) < 100:
        raise ValueError("Importe ao menos 100 candles para reduzir resultados sem histórico suficiente.")
    trades: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    balance = starting_balance
    peak_balance = starting_balance
    position: dict[str, Any] | None = None
    daily_start: dict[date, float] = {}
    daily_trades: defaultdict[date, int] = defaultdict(int)
    locked_days: set[date] = set()
    trading_halted = False
    pending: dict[str, Any] | None = None
    risk_amounts: list[float] = []
    adaptive_candidates = 0
    adaptive_blocked = 0

    def close_position(index: int, price: float, reason: str, timestamp: Any) -> None:
        nonlocal position, balance
        if position is None:
            return
        signed = 1 if position["side"] == "long" else -1
        pnl = signed * (price - position["entry"]) * position["units"]
        balance += pnl
        trades.append(
            {
                "entry_time": position["entry_time"],
                "exit_time": timestamp,
                "side": position["side"],
                "entry": position["entry"],
                "exit": price,
                "stop": position["stop"],
                "target": position["target"],
                "units": position["units"],
                "pnl": pnl,
                "pnl_pct_balance": pnl / max(position["balance_at_entry"], 1) * 100,
                "reason": reason,
                "score": position["score"],
                "decision_features": position.get("decision_features", {}),
            }
        )
        position = None

    for index, candle in enumerate(candles):
        stamp = pd.Timestamp(candle["timestamp"])
        day = stamp.date()
        daily_start.setdefault(day, balance)
        open_price = float(candle["open"])
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        actual_spread = float(candle.get("spread_pips", config["max_spread_pips"]))
        half_cost = (actual_spread + config["max_slippage_pips"]) * config["pip_size"] / 2

        if position is not None:
            stop = position["stop"]
            target = position["target"]
            is_long = position["side"] == "long"
            stop_touched = low <= stop if is_long else high >= stop
            target_touched = high >= target if is_long else low <= target
            if stop_touched:
                fill = min(open_price, stop) - half_cost if is_long else max(open_price, stop) + half_cost
                close_position(index, fill, "stop_loss", stamp.isoformat())
            elif target_touched:
                fill = max(open_price, target) - half_cost if is_long else min(open_price, target) + half_cost
                close_position(index, fill, "take_profit", stamp.isoformat())
            elif index - position["entry_index"] >= config["maximum_bars_in_trade"]:
                close_position(index, close - half_cost if is_long else close + half_cost, "time_exit", stamp.isoformat())

        # Intraday and account drawdown limits block further entries. If a
        # position is still open, flatten it at this candle close.
        unrealized = 0.0
        if position is not None:
            signed = 1 if position["side"] == "long" else -1
            unrealized = signed * (close - position["entry"]) * position["units"]
        day_equity = balance + unrealized
        day_loss_pct = max(0.0, (daily_start[day] - day_equity) / max(daily_start[day], 1) * 100)
        peak_balance = max(peak_balance, day_equity)
        drawdown_pct = (peak_balance - day_equity) / max(peak_balance, 1) * 100
        if day_loss_pct >= config["max_daily_loss_pct"]:
            locked_days.add(day)
            pending = None
            if position is not None:
                close_position(index, close - half_cost if position["side"] == "long" else close + half_cost, "daily_loss_limit", stamp.isoformat())
        if drawdown_pct >= config["max_drawdown_pct"]:
            trading_halted = True
            pending = None
            if position is not None:
                close_position(index, close - half_cost if position["side"] == "long" else close + half_cost, "max_drawdown_limit", stamp.isoformat())

        if position is None and pending is not None:
            risk_allowed = day not in locked_days and not trading_halted
            spread_ok = actual_spread <= config["max_spread_pips"]
            if spread_ok and risk_allowed and daily_trades[day] < config["max_trades_per_day"]:
                side = pending["side"]
                entry = open_price + half_cost if side == "long" else open_price - half_cost
                stop = pending["stop"]
                distance = abs(entry - stop)
                risk_budget = balance * config["risk_per_trade_pct"] / 100 * pending.get("risk_scale", 1.0)
                units = risk_budget / distance if distance > 0 else 0.0
                valid_stop_side = (side == "long" and stop < entry) or (side == "short" and stop > entry)
                if valid_stop_side and units > 0 and units * entry <= balance * 30:
                    target = entry + distance * config["minimum_risk_reward"] if side == "long" else entry - distance * config["minimum_risk_reward"]
                    position = {
                        "side": side,
                        "entry": entry,
                        "stop": stop,
                        "target": target,
                        "units": units,
                        "entry_time": stamp.isoformat(),
                        "entry_index": index,
                        "balance_at_entry": balance,
                        "score": pending["score"],
                        "decision_features": pending["decision_features"],
                        "learned_probability": pending.get("learned_probability"),
                    }
                    risk_amounts.append(risk_budget)
                    daily_trades[day] += 1
                    # The entry bar is simulated from its open. If both exits
                    # are touched in this candle, the stop is assumed first.
                    is_long = side == "long"
                    stop_touched = low <= stop if is_long else high >= stop
                    target_touched = high >= target if is_long else low <= target
                    if stop_touched:
                        close_position(index, stop - half_cost if is_long else stop + half_cost, "stop_loss", stamp.isoformat())
                    elif target_touched:
                        close_position(index, target - half_cost if is_long else target + half_cost, "take_profit", stamp.isoformat())
            pending = None

        if position is None and pending is None and index >= max(80, evaluation_start) and day not in locked_days and not trading_halted:
            warmup_bars = min(1_500, max(
                200, config["ema_slow"] * 5, config["atr_period"] * 5,
                config["adx_period"] * 5, config["rsi_period"] * 5,
                config["swing_window"] * 4 + 20,
            ))
            lookback_start = max(0, index - warmup_bars)
            signal = analyze(candles[lookback_start : index + 1], config)
            if signal["signal"] in ("BUY", "SELL"):
                decision_features = features_from_signal(signal)
                learned_probability = None
                if learned_model is not None:
                    adaptive_candidates += 1
                    learned_probability = predict_win_probability(learned_model, decision_features)
                if learned_probability is not None and learned_probability < ENTRY_PROBABILITY_FLOOR:
                    adaptive_blocked += 1
                else:
                    pending = {
                        "side": signal["side"],
                        "stop": signal["stop"],
                        "score": signal["score"],
                        "risk_scale": signal.get("risk_scale", 1.0),
                        "decision_features": decision_features,
                        "learned_probability": learned_probability,
                    }

        unrealized = 0.0
        if position is not None:
            sign = 1 if position["side"] == "long" else -1
            unrealized = sign * (close - position["entry"]) * position["units"]
        curve.append(
            {
                "timestamp": stamp.isoformat(),
                "balance": round(balance, 2),
                "equity": round(balance + unrealized, 2),
            }
        )

    if position is not None:
        last = candles[-1]
        close_position(len(candles) - 1, float(last["close"]), "end_of_data", str(last["timestamp"]))
        curve[-1]["balance"] = round(balance, 2)
        curve[-1]["equity"] = round(balance, 2)

    wins = [trade for trade in trades if trade["pnl"] > 0]
    losses = [trade for trade in trades if trade["pnl"] < 0]
    gross_profit = sum(trade["pnl"] for trade in wins)
    gross_loss = abs(sum(trade["pnl"] for trade in losses))
    equity_values = [point["equity"] for point in curve]
    peak = starting_balance
    max_dd = 0.0
    for value in equity_values:
        peak = max(peak, value)
        max_dd = max(max_dd, (peak - value) / max(peak, 1) * 100)
    return {
        "metrics": {
            "starting_balance": round(starting_balance, 2),
            "ending_balance": round(balance, 2),
            "net_pnl": round(balance - starting_balance, 2),
            "return_pct": round((balance / starting_balance - 1) * 100, 2),
            "trades": len(trades),
            "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else None,
            "max_drawdown_pct": round(max_dd, 2),
            "average_risk_budget": round(sum(risk_amounts) / len(risk_amounts), 2) if risk_amounts else 0,
            "adaptive_filter_active": learned_model is not None,
            "adaptive_candidates": adaptive_candidates,
            "adaptive_blocked": adaptive_blocked,
        },
        "trades": trades[-2_000:],
        "equity": curve[-2_000:],
        "execution_assumptions": [
            "Signals are evaluated only on closed bars and filled at the next bar open.",
            "If stop and target are both touched inside one candle, stop is assumed first.",
            "Spread and slippage are approximated in pips; financing, swap, commissions, gaps beyond OHLC, and quote-currency conversion are not modeled.",
            "Sizing assumes account currency equals the instrument quote currency and uses contract units as the quantity unit.",
        ],
    }
