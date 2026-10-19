"""Side-effect-free domain types for research, replay and paper workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any
from uuid import uuid4


class AgentState(str, Enum):
    BOOTING = "BOOTING"
    CONNECTING = "CONNECTING"
    SYNCING_DATA = "SYNCING_DATA"
    OBSERVING = "OBSERVING"
    BUILDING_CONTEXT = "BUILDING_CONTEXT"
    RETRIEVING_EXPERIENCE = "RETRIEVING_EXPERIENCE"
    FORMING_HYPOTHESIS = "FORMING_HYPOTHESIS"
    BUILDING_EXPECTATION = "BUILDING_EXPECTATION"
    WAITING_FOR_ZONE = "WAITING_FOR_ZONE"
    WAITING_FOR_TRIGGER = "WAITING_FOR_TRIGGER"
    COMPARING_EXPECTED_OBSERVED = "COMPARING_EXPECTED_OBSERVED"
    HYPOTHESIS_CONFIRMED = "HYPOTHESIS_CONFIRMED"
    HYPOTHESIS_WEAKENING = "HYPOTHESIS_WEAKENING"
    HYPOTHESIS_INVALIDATED = "HYPOTHESIS_INVALIDATED"
    VALIDATING_RISK = "VALIDATING_RISK"
    READY_TO_EXECUTE = "READY_TO_EXECUTE"
    ORDER_PENDING = "ORDER_PENDING"
    POSITION_OPEN = "POSITION_OPEN"
    MANAGING_POSITION = "MANAGING_POSITION"
    REVIEWING_EXPERIENCE = "REVIEWING_EXPERIENCE"
    COOLDOWN = "COOLDOWN"
    SESSION_HALTED = "SESSION_HALTED"
    DATA_ERROR = "DATA_ERROR"
    RISK_LOCK = "RISK_LOCK"
    SHUTDOWN = "SHUTDOWN"


class DecisionAction(str, Enum):
    NO_TRADE = "NO_TRADE"
    HYPOTHETICAL_SIGNAL = "HYPOTHETICAL_SIGNAL"


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    spread_pips: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.timestamp, datetime):
            raise ValueError("Candle.timestamp precisa ser datetime.")
        if self.timestamp.tzinfo is None:
            raise ValueError("Candle.timestamp precisa conter timezone.")
        object.__setattr__(self, "timestamp", self.timestamp.astimezone(timezone.utc))
        prices = (self.open, self.high, self.low, self.close, self.volume)
        if not all(math.isfinite(value) for value in prices):
            raise ValueError("OHLCV precisa conter somente números finitos.")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC inválido: low/high não abrangem open e close.")
        if self.low > self.high:
            raise ValueError("OHLC inválido: low maior que high.")
        if self.volume < 0:
            raise ValueError("Volume não pode ser negativo.")
        if self.spread_pips is not None and (not math.isfinite(self.spread_pips) or self.spread_pips < 0):
            raise ValueError("Spread precisa ser finito e não negativo.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(), "open": self.open, "high": self.high,
            "low": self.low, "close": self.close, "volume": self.volume,
            "spread_pips": self.spread_pips,
        }


@dataclass(frozen=True, slots=True)
class DataQuality:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    latest_timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class Candidate:
    side: str
    entry: float
    stop: float
    target: float
    expires_at: datetime
    evidence: tuple[str, ...]
    contradictions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) and value > 0 for value in (self.entry, self.stop, self.target)):
            raise ValueError("Candidate prices must be finite and positive.")
        if self.expires_at.tzinfo is None:
            raise ValueError("Candidate.expires_at precisa conter timezone.")
        if self.side not in {"long", "short"}:
            raise ValueError("Candidate.side precisa ser long ou short.")
        if self.side == "long" and not (self.stop < self.entry < self.target):
            raise ValueError("Candidato long precisa ter stop < entrada < alvo.")
        if self.side == "short" and not (self.target < self.entry < self.stop):
            raise ValueError("Candidato short precisa ter alvo < entrada < stop.")


@dataclass(frozen=True, slots=True)
class RiskLimits:
    risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_drawdown_pct: float
    max_spread_pips: float
    minimum_risk_reward: float
    max_trades_per_day: int

    def __post_init__(self) -> None:
        values = (self.risk_per_trade_pct, self.max_daily_loss_pct, self.max_drawdown_pct,
                  self.max_spread_pips, self.minimum_risk_reward)
        if not all(math.isfinite(value) and value >= 0 for value in values):
            raise ValueError("RiskLimits precisa conter valores finitos e não negativos.")
        if not 0 < self.risk_per_trade_pct <= 2:
            raise ValueError("Risco por operação deve ficar entre 0 e 2 por cento nesta fundação.")
        if self.max_trades_per_day < 1:
            raise ValueError("max_trades_per_day precisa ser positivo.")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    equity: float
    peak_equity: float
    daily_start_equity: float
    daily_trades: int = 0


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    approved: bool
    reasons: tuple[str, ...]
    risk_budget: float | None = None
    hypothetical_units: float | None = None
    risk_reward: float | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    run_id: str
    symbol: str
    timeframe: str
    data_source: str
    data_timestamp: datetime
    action: DecisionAction
    reason_code: str
    state: AgentState
    evidence: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    missing_data: tuple[str, ...] = ()
    candidate: Candidate | None = None
    risk: RiskAssessment | None = None
    strategy_id: str = "pullback_trend"
    strategy_version: str = "0.1"
    config_hash: str = ""
    decision_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "decision_id": self.decision_id, "run_id": self.run_id,
            "created_at_utc": self.created_at.astimezone(timezone.utc).isoformat(),
            "symbol": self.symbol, "timeframe": self.timeframe, "data_source": self.data_source,
            "data_timestamp_utc": self.data_timestamp.astimezone(timezone.utc).isoformat(),
            "action": self.action.value, "reason_code": self.reason_code, "state": self.state.value,
            "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
            "config_hash": self.config_hash, "evidence": list(self.evidence),
            "contradictions": list(self.contradictions), "missing_data": list(self.missing_data),
            "candidate": None if self.candidate is None else {
                "side": self.candidate.side, "entry": self.candidate.entry, "stop": self.candidate.stop,
                "target": self.candidate.target, "expires_at_utc": self.candidate.expires_at.isoformat(),
                "evidence": list(self.candidate.evidence), "contradictions": list(self.candidate.contradictions),
            },
            "risk": None if self.risk is None else {
                "approved": self.risk.approved, "reasons": list(self.risk.reasons),
                "risk_budget": self.risk.risk_budget, "hypothetical_units": self.risk.hypothetical_units,
                "risk_reward": self.risk.risk_reward,
            },
        }
