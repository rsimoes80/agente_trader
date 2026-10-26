"""Deterministic next-open execution on bid bars, isolated from broker APIs."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from .domain import AccountSnapshot, Candidate, Candle, DataQuality, RiskLimits
from .risk import assess_candidate


def classify_outcome(net_pnl: float | None, *, compliant: bool | None) -> str:
    if net_pnl is None or compliant is None:
        return "insufficient_evidence"
    outcome = "profit" if net_pnl > 0 else "loss" if net_pnl < 0 else "breakeven"
    return ("good_process_" if compliant else "poor_process_") + outcome


@dataclass(frozen=True)
class ExecutionConfig:
    pip_size: float = 0.0001
    slippage_pips: float = (
        0.2  # Per market fill; target limits have no adverse slippage.
    )
    commission_per_million_side: float = (
        35.0  # Explicit USD research assumption, not broker pricing.
    )
    max_holding_bars: int = 24
    value_per_price_unit: float = 1.0
    initial_equity: float = 10_000.0
    bar_seconds: int = 300
    fixed_units: float | None = None

    def __post_init__(self):
        if self.fixed_units is not None and (
            not math.isfinite(self.fixed_units) or self.fixed_units <= 0
        ):
            raise ValueError("Fixed lot units must be finite and positive.")
        for value in (self.pip_size, self.value_per_price_unit, self.initial_equity):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Execution parameters must be finite and positive.")
        for value in (self.slippage_pips, self.commission_per_million_side):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Execution costs must be finite and nonnegative.")
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 1
            for v in (self.max_holding_bars, self.bar_seconds)
        ):
            raise ValueError(
                "Holding period and bar duration must be positive integers."
            )


@dataclass(frozen=True)
class EntryRequest:
    decision_id: str
    snapshot_id: str
    hypothesis_id: str
    candidate: Candidate
    submitted_at: datetime
    session: str
    regime: str
    intelligence_context: dict = field(default_factory=dict)


@dataclass
class Position:
    request: EntryRequest
    entry_bid: float
    entry_price: float
    entry_spread: float
    entry_slippage: float
    entry_at: datetime
    units: float
    initial_risk: float
    bars_held: int = 0
    mae_price: float = 0.0
    mfe_price: float = 0.0


class ExecutionSimulator:
    """One exposure at a time. Missing exposure data freezes the simulated account."""

    def __init__(self, config: ExecutionConfig, limits: RiskLimits, *, instrument_context=None):
        self.config, self.limits = config, limits
        self.instrument_context = dict(instrument_context) if instrument_context else None
        self.request: EntryRequest | None = None
        self.position: Position | None = None
        self.balance = self.peak_equity = config.initial_equity
        self.daily_start = config.initial_equity
        self.day = None
        self.daily_entries = 0
        self.account_locked = False
        self.events: list[dict] = []
        self.equity_curve: list[dict] = []

    @property
    def busy(self):
        return self.request is not None or self.position is not None

    def account(self, at: datetime) -> AccountSnapshot:
        day = at.date().isoformat()
        if self.day != day:
            self.day, self.daily_start, self.daily_entries = day, self.balance, 0
        return AccountSnapshot(
            self.balance, self.peak_equity, self.daily_start, self.daily_entries
        )

    def submit(self, request: EntryRequest) -> None:
        if self.instrument_context and any(
            request.intelligence_context.get(key) != self.instrument_context[key]
            for key in ('symbol', 'profile_id')
        ):
            raise ValueError('SIMULATION_INSTRUMENT_MISMATCH')
        if self.busy or self.account_locked:
            raise ValueError("Simulator cannot queue another exposure.")
        self.request = request

    def _event(self, request, status, now, **payload):
        event = {
            "event_id": f"{request.decision_id}:execution:{status}",
            "decision_id": request.decision_id,
            "snapshot_id": request.snapshot_id,
            "hypothesis_id": request.hypothesis_id,
            "status": status,
            "observed_at": now.isoformat(),
            "session": request.session,
            "market_regime": request.regime,
            "side": request.candidate.side,
            **payload,
        }
        event["intelligence_context"] = request.intelligence_context
        if self.instrument_context:
            event['instrument'] = dict(self.instrument_context)
        self.events.append(event)
        return event

    def advance(
        self,
        candle: Candle,
        *,
        data_valid: bool,
        active_sessions: tuple[str, ...],
        force_close_reason: str | None = None,
    ) -> list[dict]:
        start = len(self.events)
        now = candle.timestamp + timedelta(seconds=self.config.bar_seconds)
        self.account(candle.timestamp)
        spread = candle.spread_pips
        valid_spread = spread is not None and math.isfinite(spread) and spread >= 0
        if self.position and (not data_valid or not valid_spread):
            self._event(
                self.position.request,
                "censored",
                now,
                reason="MARKET_DATA_UNRESOLVED",
                financial_result={"net_pnl": None, "result_in_r": None},
                process_classification="technical_failure",
                account_locked=True,
            )
            self.position = None
            self.account_locked = True
        if self.request:
            request, self.request = self.request, None
            reason = None
            if self.account_locked or not data_valid:
                reason = "ENTRY_DATA_INVALID"
            elif not valid_spread:
                reason = "ENTRY_SPREAD_UNAVAILABLE"
            elif candle.timestamp != request.submitted_at:
                reason = "ENTRY_NOT_NEXT_CONTIGUOUS_OPEN"
            elif request.session not in active_sessions:
                reason = "ENTRY_SESSION_NOT_AUTHORIZED"
            elif candle.timestamp >= request.candidate.expires_at:
                reason = "ENTRY_EXPIRED"
            if reason:
                self._event(request, "rejected", now, reason=reason)
            else:
                long = request.candidate.side == "long"
                spread_price = spread * self.config.pip_size
                slippage = self.config.slippage_pips * self.config.pip_size
                fill = (
                    candle.open + spread_price + slippage
                    if long
                    else candle.open - slippage
                )
                original = request.candidate
                try:
                    rebased = Candidate(
                        original.side,
                        fill,
                        original.stop,
                        original.target,
                        original.expires_at,
                        original.evidence,
                        original.contradictions,
                    )
                except ValueError:
                    self._event(
                        request,
                        "rejected",
                        now,
                        reason="ENTRY_GAP_OUTSIDE_FROZEN_STOP_TARGET",
                    )
                else:
                    risk = assess_candidate(
                        rebased,
                        quality=DataQuality(True),
                        session=request.session,
                        allowed_sessions=frozenset(active_sessions),
                        spread_pips=spread,
                        pip_size=self.config.pip_size,
                        max_slippage_price=slippage,
                        value_per_price_unit=self.config.value_per_price_unit,
                        commission_per_unit=2
                        * self.config.commission_per_million_side
                        / 1_000_000,
                        entry_is_executable=True,
                        account=self.account(candle.timestamp),
                        limits=self.limits,
                        now=candle.timestamp,
                        fixed_units=self.config.fixed_units,
                    )
                    if not risk.approved:
                        self._event(
                            request,
                            "rejected",
                            now,
                            reason="ENTRY_RISK_VETO",
                            risk=asdict(risk),
                        )
                    else:
                        self.position = Position(
                            request,
                            candle.open,
                            fill,
                            spread_price,
                            slippage,
                            candle.timestamp,
                            risk.hypothetical_units,
                            risk.risk_budget,
                        )
                        self.daily_entries += 1
                        self._event(
                            request,
                            "filled",
                            now,
                            entry_at=candle.timestamp.isoformat(),
                            entry_price=fill,
                            units=risk.hypothetical_units,
                            initial_risk=risk.risk_budget,
                            risk=asdict(risk),
                        )
        if self.position:
            p = self.position
            p.bars_held += 1
            long = p.request.candidate.side == "long"
            shift = 0.0 if long else spread * self.config.pip_size
            opening, high, low, close = (
                getattr(candle, name) + shift
                for name in ("open", "high", "low", "close")
            )
            stop, target = p.request.candidate.stop, p.request.candidate.target
            stop_gap = opening <= stop if long else opening >= stop
            target_gap = opening >= target if long else opening <= target
            stop_hit = low <= stop if long else high >= stop
            target_hit = high >= target if long else low <= target
            reason, reference, exit_slip = (
                None,
                None,
                self.config.slippage_pips * self.config.pip_size,
            )
            if stop_gap:
                reason, reference = "STOP_GAP", opening
            elif target_gap:
                reason, reference, exit_slip = "TARGET_GAP_LIMIT", target, 0.0
            elif stop_hit:
                reason, reference = (
                    "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP",
                    stop,
                )
            elif target_hit:
                reason, reference, exit_slip = "TARGET", target, 0.0
            elif p.bars_held >= self.config.max_holding_bars:
                reason, reference = "TIME_EXPIRY", close
            elif force_close_reason:
                reason, reference = force_close_reason, close
            if reason:
                self._excursion(p, (opening, reference))
                self._close(
                    p, reference, spread * self.config.pip_size, exit_slip, now, reason
                )
            else:
                self._excursion(p, (low, high))
        equity = self.balance
        if self.position and valid_spread:
            p = self.position
            long = p.request.candidate.side == "long"
            liquidation = (
                candle.close if long else candle.close + spread * self.config.pip_size
            )
            equity += (
                (1 if long else -1)
                * (liquidation - p.entry_price)
                * p.units
                * self.config.value_per_price_unit
            )
            equity -= 2 * p.units * self.config.commission_per_million_side / 1_000_000
        self.peak_equity = max(self.peak_equity, equity)
        self.equity_curve.append(
            {
                "timestamp": now.isoformat(),
                "balance": self.balance,
                "equity": None if self.account_locked else equity,
                "account_locked": self.account_locked,
            }
        )
        return self.events[start:]

    def _excursion(self, p, prices):
        sign = 1 if p.request.candidate.side == "long" else -1
        changes = [sign * (price - p.entry_price) for price in prices]
        p.mae_price = max(p.mae_price, -min(changes), 0.0)
        p.mfe_price = max(p.mfe_price, max(changes), 0.0)

    def _close(self, p, reference, exit_spread, slippage, now, reason):
        long = p.request.candidate.side == "long"
        sign = 1 if long else -1
        exit_fill = reference - sign * slippage
        bid_reference = reference if long else reference - exit_spread
        gross = (
            sign
            * (bid_reference - p.entry_bid)
            * p.units
            * self.config.value_per_price_unit
        )
        spread_cost = (
            (p.entry_spread if long else exit_spread)
            * p.units
            * self.config.value_per_price_unit
        )
        slippage_cost = (
            (p.entry_slippage + slippage) * p.units * self.config.value_per_price_unit
        )
        commission = 2 * p.units * self.config.commission_per_million_side / 1_000_000
        net = gross - spread_cost - slippage_cost - commission
        financial = {
            "gross_pnl": gross,
            "net_pnl": net,
            "spread_cost": spread_cost,
            "slippage_cost": slippage_cost,
            "commission": commission,
            "result_in_r": net / p.initial_risk,
            "initial_risk": p.initial_risk,
            "mae_price": p.mae_price,
            "mfe_price": p.mfe_price,
            "mae_r": p.mae_price
            * p.units
            * self.config.value_per_price_unit
            / p.initial_risk,
            "mfe_r": p.mfe_price
            * p.units
            * self.config.value_per_price_unit
            / p.initial_risk,
        }
        self.account(now)
        self.balance += net
        classification = classify_outcome(net, compliant=True)
        self._event(
            p.request,
            "closed",
            now,
            reason=reason,
            entry_at=p.entry_at.isoformat(),
            entry_price=p.entry_price,
            exit_price=exit_fill,
            stop=p.request.candidate.stop,
            target=p.request.candidate.target,
            units=p.units,
            bars_held=p.bars_held,
            duration_seconds=(now - p.entry_at).total_seconds(),
            financial_result=financial,
            process_classification=classification,
            rule_compliance=True,
            ambiguity="stop_first" if reason == "STOP_FIRST_AMBIGUOUS" else None,
            excursions="lower_bounds; exit bars use open and exit only",
        )
        self.position = None

    def finish(self, now: datetime) -> list[dict]:
        if self.request:
            request, self.request = self.request, None
            return [
                self._event(request, "rejected", now, reason="END_OF_DATA_NO_NEXT_OPEN")
            ]
        return []

    def summary(self) -> dict:
        closed = [event for event in self.events if event["status"] == "closed"]
        returns = [e["financial_result"]["result_in_r"] for e in closed]
        peak, drawdown = self.config.initial_equity, 0.0
        for item in self.equity_curve:
            if item["equity"] is not None:
                peak = max(peak, item["equity"])
                drawdown = max(drawdown, (peak - item["equity"]) / peak * 100)
        return {
            "model_version": "bid_next_open_v1",
            "initial_balance": self.config.initial_equity,
            "known_realized_balance": self.balance,
            "net_pnl": None
            if self.account_locked
            else self.balance - self.config.initial_equity,
            "gross_pnl_closed": sum(e["financial_result"]["gross_pnl"] for e in closed),
            "spread_cost_closed": sum(
                e["financial_result"]["spread_cost"] for e in closed
            ),
            "slippage_cost_closed": sum(
                e["financial_result"]["slippage_cost"] for e in closed
            ),
            "commission_closed": sum(
                e["financial_result"]["commission"] for e in closed
            ),
            "closed_trades": len(closed),
            "wins": sum(e["financial_result"]["net_pnl"] > 0 for e in closed),
            "losses": sum(e["financial_result"]["net_pnl"] < 0 for e in closed),
            "mean_r": sum(returns) / len(returns) if returns else None,
            "max_close_equity_drawdown_pct": drawdown,
            "censored_trades": sum(e["status"] == "censored" for e in self.events),
            "rejected_entries": sum(e["status"] == "rejected" for e in self.events),
            "account_locked": self.account_locked,
            "process_classes": {
                key: sum(e.get("process_classification") == key for e in self.events)
                for key in sorted(
                    {
                        e["process_classification"]
                        for e in self.events
                        if "process_classification" in e
                    }
                )
            },
        }
