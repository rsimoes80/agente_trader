"""Read-only market observer producing an explainable market snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .domain import Candle, DataQuality
from .sessions import SessionContext, SessionEngine
from .structure import StructureSnapshot, analyze_structure


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    session: tuple[str, ...]
    data_freshness_seconds: float | None
    data_quality: dict[str, Any]
    spread_pips: float | None
    volatility_regime: str
    market_regime: str
    market_structure: dict[str, Any]
    dominant_direction: str
    dominant_swing: dict[str, Any] | None
    current_leg_type: str
    range_position: float | None
    liquidity_map: dict[str, Any]
    zones_of_interest: tuple[str, ...]
    relevant_levels: tuple[float, ...]
    volume_context: dict[str, Any]
    favorable_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    current_narrative: dict[str, Any]
    clarity_status: str
    observation_status: str
    expires_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MarketObserver:
    """Summarizes market context only; it has no broker or execution dependency."""

    def __init__(self, sessions: SessionEngine, *, swing_window: int = 2, max_spread_pips: float = 2.0):
        self.sessions = sessions
        self.swing_window = swing_window
        self.max_spread_pips = max_spread_pips

    def observe(
        self,
        *,
        symbol: str,
        timeframe: str,
        candles: tuple[Candle, ...] | list[Candle],
        quality: DataQuality,
        spread_pips: float | None,
        observed_at: datetime | None = None,
        snapshot_id: str | None = None,
        validity_seconds: float = 300,
    ) -> MarketSnapshot:
        now = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        latest = quality.latest_timestamp
        freshness = (now - latest).total_seconds() if latest else None
        session: SessionContext = self.sessions.identify(now)
        structure: StructureSnapshot = analyze_structure(candles, self.swing_window) if candles else analyze_structure((), self.swing_window)
        favorable: list[str] = []
        conflicting: list[str] = []
        missing: list[str] = []
        if structure.direction in {"bullish", "bearish"}:
            favorable.append(f"Estrutura confirmada {structure.direction} por swings fechados.")
        elif structure.direction == "mixed":
            conflicting.append("Swings recentes não confirmam uma direção única.")
        else:
            missing.append("Histórico insuficiente para classificar a estrutura.")
        if structure.break_of_structure:
            favorable.append(f"Fechamento atual além de swing confirmado ({structure.break_of_structure}).")
        if structure.liquidity_sweep:
            favorable.append(f"Pavio ultrapassou swing e fechou de volta ({structure.liquidity_sweep}); proxy, requer contexto.")
        if spread_pips is None:
            missing.append("Spread atual indisponível.")
        elif spread_pips > self.max_spread_pips:
            conflicting.append("Spread acima da referência configurada para observação.")
        if not session.active_sessions:
            missing.append("Nenhuma sessão autorizada/configurada está ativa neste instante.")
        if not quality.valid:
            conflicting.extend(quality.errors)
        if quality.warnings:
            conflicting.extend(quality.warnings)
        if len(candles) < 30:
            missing.append("Menos de 30 candles disponíveis para contexto inicial.")
        clarity = "insufficient_data" if not quality.valid or len(candles) < 30 else "mixed" if conflicting else "clear" if structure.direction in {"bullish", "bearish"} else "developing"
        status = "halted" if not quality.valid else "waiting_for_context" if clarity in {"insufficient_data", "unclear", "mixed"} else "context_detected"
        levels = tuple(swing.price for swing in structure.swings[-8:])
        last = candles[-1] if candles else None
        range_position = None
        volatility = "unknown"
        if len(candles) >= 20:
            recent = candles[-20:]
            low = min(item.low for item in recent)
            high = max(item.high for item in recent)
            range_position = (last.close - low) / (high - low) if last and high > low else None
            ranges = sorted(item.high - item.low for item in recent)
            median_range = ranges[len(ranges) // 2]
            current_range = last.high - last.low if last else 0.0
            volatility = "elevated" if current_range > median_range * 2 else "compressed" if current_range < median_range * 0.5 else "normal"
        volume_context = {"source": "provider-specific", "recent_tick_volume": [item.volume for item in candles[-5:]]}
        narrative = {
            "context": [f"Estrutura observada: {structure.direction}."],
            "behavior": [f"Último fechamento: {last.close:.5f} UTC {last.timestamp.isoformat()}."] if last else [],
            "conflicts": conflicting,
            "state": status,
        }
        return MarketSnapshot(
            snapshot_id or str(uuid4()), now.isoformat(), symbol, timeframe, session.active_sessions, freshness,
            {"valid": quality.valid, "errors": list(quality.errors), "warnings": list(quality.warnings)},
            spread_pips, volatility, "trend" if structure.direction in {"bullish", "bearish"} else structure.direction,
            {"direction": structure.direction, "swings": [asdict(item) for item in structure.swings], "bos": structure.break_of_structure, "sweep": structure.liquidity_sweep},
            structure.direction, asdict(structure.swings[-1]) if structure.swings else None,
            "impulse" if structure.break_of_structure else "correction_or_undetermined", range_position,
            {"last_confirmed_swings": list(levels), "sweep": structure.liquidity_sweep}, (), levels,
            volume_context, tuple(favorable), tuple(conflicting), tuple(missing), narrative,
            clarity, status, (now + timedelta(seconds=validity_seconds)).isoformat(),
        )
