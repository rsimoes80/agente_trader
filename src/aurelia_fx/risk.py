"""Independent fail-closed risk gate for hypothetical research signals."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .domain import AccountSnapshot, Candidate, DataQuality, RiskAssessment, RiskLimits


def assess_candidate(
    candidate: Candidate,
    *,
    quality: DataQuality,
    session: str | None,
    allowed_sessions: frozenset[str],
    spread_pips: float | None,
    pip_size: float,
    max_slippage_price: float,
    value_per_price_unit: float,
    account: AccountSnapshot,
    limits: RiskLimits,
    now: datetime | None = None,
    commission_per_unit: float = 0.0,
    entry_is_executable: bool = False,
) -> RiskAssessment:
    reasons: list[str] = []
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if candidate.expires_at.astimezone(timezone.utc) <= stamp:
        reasons.append("HYPOTHESIS_EXPIRED")
    if not quality.valid:
        reasons.append("INVALID_MARKET_DATA")
    if session is None or session not in allowed_sessions:
        reasons.append("SESSION_NOT_AUTHORIZED")
    if spread_pips is None or not math.isfinite(spread_pips) or spread_pips < 0:
        reasons.append("SPREAD_UNAVAILABLE")
    elif spread_pips > limits.max_spread_pips:
        reasons.append("SPREAD_LIMIT")
    if not all(math.isfinite(value) and value > 0 for value in
               (account.equity, account.peak_equity, account.daily_start_equity)):
        reasons.append("ACCOUNT_EQUITY_INVALID")
    if isinstance(account.daily_trades, bool) or not isinstance(account.daily_trades, int) or account.daily_trades < 0:
        reasons.append("DAILY_TRADE_COUNT_INVALID")
    if account.daily_trades >= limits.max_trades_per_day:
        reasons.append("DAILY_TRADE_LIMIT")
    if account.daily_start_equity > 0:
        daily_loss_pct = max(0.0, (account.daily_start_equity - account.equity) / account.daily_start_equity * 100)
        if daily_loss_pct >= limits.max_daily_loss_pct:
            reasons.append("DAILY_LOSS_LIMIT")
    if account.peak_equity > 0:
        drawdown_pct = max(0.0, (account.peak_equity - account.equity) / account.peak_equity * 100)
        if drawdown_pct >= limits.max_drawdown_pct:
            reasons.append("DRAWDOWN_LIMIT")
    if not math.isfinite(pip_size) or pip_size <= 0:
        reasons.append("PIP_SIZE_INVALID")
    if not math.isfinite(max_slippage_price) or max_slippage_price < 0:
        reasons.append("SLIPPAGE_ASSUMPTION_INVALID")
    if not math.isfinite(value_per_price_unit) or value_per_price_unit <= 0:
        reasons.append("CONTRACT_VALUE_UNAVAILABLE")
    if not math.isfinite(commission_per_unit) or commission_per_unit < 0:
        reasons.append("COMMISSION_INVALID")
    distance = abs(candidate.entry - candidate.stop)
    reward = abs(candidate.target - candidate.entry)
    if not all(math.isfinite(value) for value in (candidate.entry, candidate.stop, candidate.target)) or distance <= 0 or reward <= 0:
        reasons.append("INVALID_STOP_OR_TARGET")
    if reasons:
        return RiskAssessment(False, tuple(dict.fromkeys(reasons)))

    cost_price = (0 if entry_is_executable else float(spread_pips) * pip_size) + max_slippage_price
    cost_price += commission_per_unit / value_per_price_unit
    net_risk_distance = distance + cost_price
    net_reward_distance = max(0.0, reward - cost_price)
    ratio = net_reward_distance / net_risk_distance if net_risk_distance > 0 else 0.0
    if ratio < limits.minimum_risk_reward:
        return RiskAssessment(False, ("NET_RISK_REWARD_TOO_LOW",), risk_reward=ratio)
    budget = account.equity * limits.risk_per_trade_pct / 100
    units = budget / (net_risk_distance * value_per_price_unit)
    return RiskAssessment(True, (), risk_budget=budget, hypothetical_units=units, risk_reward=ratio)
