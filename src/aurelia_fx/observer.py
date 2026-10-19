"""Read-only market observer producing an explainable market snapshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from .domain import Candle, DataQuality
from .evidence import EvidenceEngine
from .levels import SupportResistanceEngine
from .observation import MarketNarrative
from .price_action import PriceActionReader
from .sessions import SessionContext, SessionEngine
from .structure import StructureSnapshot, analyze_structure
from .trend import HierarchyConfig, TrendHierarchyEngine


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
    schema_version: int = 3
    trend_hierarchy: dict[str, Any] = field(default_factory=dict)
    macro_trend: dict[str, Any] = field(default_factory=dict)
    context_trend: dict[str, Any] = field(default_factory=dict)
    structure_trend: dict[str, Any] = field(default_factory=dict)
    execution_trend: dict[str, Any] = field(default_factory=dict)
    trend_alignment: dict[str, Any] = field(default_factory=dict)
    trend_state: str = "UNKNOWN"
    reversal_status: str = "none"
    price_action: dict[str, Any] = field(default_factory=dict)
    impulse_state: str = "not_established"
    correction_state: str = "not_established"
    follow_through_status: str = "insufficient_data"
    support_levels: tuple[dict, ...] = ()
    resistance_levels: tuple[dict, ...] = ()
    nearby_structural_levels: tuple[dict, ...] = ()
    momentum_context: dict[str, Any] = field(default_factory=dict)
    evidence_set_id: str = ""
    evidence_status: str = "INSUFFICIENT"
    evidence_set: dict[str, Any] = field(default_factory=dict)
    bullish_evidence: tuple[str, ...] = ()
    bearish_evidence: tuple[str, ...] = ()
    invalidating_evidence: tuple[str, ...] = ()
    market_narrative: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def learning_context(self, evaluation=None):
        return {
            "trend_state_at_decision": self.trend_state,
            "trend_alignment": self.trend_alignment,
            "trade_direction_class": self.trend_alignment["trade_direction_class"],
            "price_action_state": {
                key: self.price_action[key]
                for key in (
                    "directional_pressure",
                    "impulse_state",
                    "correction_state",
                    "expansion_state",
                    "overlap_state",
                    "breakout_status",
                    "retest_status",
                    "failure_status",
                    "momentum_behavior",
                )
            },
            "support_resistance_context": tuple(
                {
                    key: zone[key]
                    for key in (
                        "level_id",
                        "timeframe",
                        "lower_bound",
                        "upper_bound",
                        "distance",
                        "role",
                        "breakout_status",
                        "retest_status",
                    )
                }
                for zone in self.nearby_structural_levels
            ),
            "evidence_set_id": self.evidence_set_id,
            "evidence_available": tuple(
                item["evidence_id"] for item in self.evidence_set["items"]
            ),
            "evidence_missing": self.missing_evidence,
            "conflicting_evidence": self.conflicting_evidence,
            "evidence_state": self.evidence_status,
            "confirmation_state": evaluation.confirmation_state
            if evaluation
            else "not_evaluated",
            "trigger_state": evaluation.trigger_state
            if evaluation
            else "not_evaluated",
            "partial_reversal_state": self.reversal_status,
            "observed_follow_through": self.follow_through_status,
        }


class MarketObserver:
    """Summarizes market context only; it has no broker or execution dependency."""

    def __init__(
        self,
        sessions: SessionEngine,
        *,
        swing_window: int = 2,
        max_spread_pips: float = 2.0,
        hierarchy_config: HierarchyConfig | None = None,
        level_tolerance: float = 0.0002,
        level_ttl_bars: int = 300,
        required_trend_roles: tuple[str, ...] = ("context", "structure"),
    ):
        self.sessions = sessions
        self.swing_window = swing_window
        self.max_spread_pips = max_spread_pips
        self.trends = (
            TrendHierarchyEngine(hierarchy_config, swing_window=swing_window)
            if hierarchy_config
            else None
        )
        self.price_reader = PriceActionReader()
        self.level_reader = SupportResistanceEngine(
            tolerance=level_tolerance,
            ttl_bars=level_ttl_bars,
            swing_window=swing_window,
        )
        self.evidence_reader = EvidenceEngine()
        self.required_trend_roles = required_trend_roles

    def reset(self):
        if self.trends:
            self.trends.reset()

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
        histories_by_timeframe: dict | None = None,
        data_reference: str = "",
    ) -> MarketSnapshot:
        now = (observed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        latest = quality.latest_timestamp
        freshness = (now - latest).total_seconds() if latest else None
        session: SessionContext = self.sessions.identify(now)
        structure: StructureSnapshot = (
            analyze_structure(candles, self.swing_window)
            if candles
            else analyze_structure((), self.swing_window)
        )
        favorable: list[str] = []
        conflicting: list[str] = []
        missing: list[str] = []
        if structure.direction in {"bullish", "bearish"}:
            favorable.append(
                f"Estrutura confirmada {structure.direction} por swings fechados."
            )
        elif structure.direction == "mixed":
            conflicting.append("Swings recentes não confirmam uma direção única.")
        else:
            missing.append("Histórico insuficiente para classificar a estrutura.")
        if structure.break_of_structure:
            favorable.append(
                f"Fechamento atual além de swing confirmado ({structure.break_of_structure})."
            )
        if structure.liquidity_sweep:
            favorable.append(
                f"Pavio ultrapassou swing e fechou de volta ({structure.liquidity_sweep}); proxy, requer contexto."
            )
        if spread_pips is None:
            missing.append("Spread atual indisponível.")
        elif spread_pips > self.max_spread_pips:
            conflicting.append(
                "Spread acima da referência configurada para observação."
            )
        if not session.active_sessions:
            missing.append(
                "Nenhuma sessão autorizada/configurada está ativa neste instante."
            )
        if not quality.valid:
            conflicting.extend(quality.errors)
        if quality.warnings:
            conflicting.extend(quality.warnings)
        if len(candles) < 30:
            missing.append("Menos de 30 candles disponíveis para contexto inicial.")
        clarity = (
            "insufficient_data"
            if not quality.valid or len(candles) < 30
            else "mixed"
            if conflicting
            else "clear"
            if structure.direction in {"bullish", "bearish"}
            else "developing"
        )
        status = (
            "halted"
            if not quality.valid
            else "waiting_for_context"
            if clarity in {"insufficient_data", "unclear", "mixed"}
            else "context_detected"
        )
        levels = tuple(swing.price for swing in structure.swings[-8:])
        last = candles[-1] if candles else None
        range_position = None
        volatility = "unknown"
        if len(candles) >= 20:
            recent = candles[-20:]
            low = min(item.low for item in recent)
            high = max(item.high for item in recent)
            range_position = (
                (last.close - low) / (high - low) if last and high > low else None
            )
            ranges = sorted(item.high - item.low for item in recent)
            median_range = ranges[len(ranges) // 2]
            current_range = last.high - last.low if last else 0.0
            volatility = (
                "elevated"
                if current_range > median_range * 2
                else "compressed"
                if current_range < median_range * 0.5
                else "normal"
            )
        volume_context = {
            "source": "provider-specific",
            "recent_tick_volume": [item.volume for item in candles[-5:]],
        }
        narrative = {
            "context": [f"Estrutura observada: {structure.direction}."],
            "behavior": [
                f"Último fechamento: {last.close:.5f} UTC {last.timestamp.isoformat()}."
            ]
            if last
            else [],
            "conflicts": conflicting,
            "state": status,
        }
        identity = snapshot_id or str(uuid4())
        if self.trends is None:
            self.trends = TrendHierarchyEngine(
                HierarchyConfig.for_execution(timeframe), swing_window=self.swing_window
            )
        histories = histories_by_timeframe or {timeframe: tuple(candles)}
        hierarchy = self.trends.evaluate(histories, as_of=now)
        pa = self.price_reader.read(
            candles,
            symbol=symbol,
            timeframe=timeframe,
            now=now,
            observation_id=identity + ":price_action",
        )
        follow_through = (
            pa.failure_status
            if pa.failure_status not in {"none", "insufficient_data"}
            else pa.continuation_evidence[-1]
            if pa.continuation_evidence
            else "insufficient_data"
            if pa.failure_status == "insufficient_data"
            else "not_observed"
        )
        zones = self.level_reader.evaluate(histories, symbol=symbol, now=now)
        nearby = self.level_reader.context(zones, last.close, limit=12) if last else ()
        evidence = self.evidence_reader.observe(
            snapshot_id=identity,
            symbol=symbol,
            timeframe=timeframe,
            now=now,
            validity_seconds=validity_seconds,
            hierarchy=hierarchy,
            price_action=pa,
            levels=nearby,
            quality=quality,
            spread_pips=spread_pips,
            max_spread_pips=self.max_spread_pips,
            sessions=session.active_sessions,
            freshness_seconds=freshness,
            max_age_seconds=validity_seconds * 1.5,
            required_roles=self.required_trend_roles,
            data_reference=data_reference,
        )
        narrative = MarketNarrative(
            tuple(narrative["context"]),
            tuple(narrative["behavior"]),
            {r: s["state"] for r, s in hierarchy["states"].items()},
            tuple(conflicting) + evidence.conflicts,
            tuple(missing) + evidence.missing_evidence,
            status,
            pa.failure_status,
            evidence.evidence_quality,
            evidence.confluence_status,
        ).as_dict()
        if evidence.invalidations:
            clarity, status = "unclear", "halted"
        elif evidence.evidence_quality in {"INSUFFICIENT", "CONFLICTED", "DEVELOPING"}:
            clarity, status = (
                "mixed" if evidence.conflicts else "developing",
                "waiting_for_context",
            )
        narrative["state"] = status
        states = hierarchy["states"]
        return MarketSnapshot(
            identity,
            now.isoformat(),
            symbol,
            timeframe,
            session.active_sessions,
            freshness,
            {
                "valid": quality.valid,
                "errors": list(quality.errors),
                "warnings": list(quality.warnings),
            },
            spread_pips,
            volatility,
            "trend"
            if structure.direction in {"bullish", "bearish"}
            else structure.direction,
            {
                "direction": structure.direction,
                "swings": [asdict(item) for item in structure.swings],
                "bos": structure.break_of_structure,
                "sweep": structure.liquidity_sweep,
                "last_close": last.close if last else None,
            },
            hierarchy["alignment"]["dominant_direction"],
            asdict(structure.swings[-1]) if structure.swings else None,
            "impulse" if structure.break_of_structure else "correction_or_undetermined",
            range_position,
            {"last_confirmed_swings": list(levels), "sweep": structure.liquidity_sweep},
            (),
            levels,
            volume_context,
            tuple(favorable),
            tuple(conflicting) + tuple(str(pair) for pair in evidence.conflicts),
            tuple(missing) + evidence.missing_evidence,
            narrative,
            clarity,
            status,
            (now + timedelta(seconds=validity_seconds)).isoformat(),
            trend_hierarchy=hierarchy,
            macro_trend=states["macro"],
            context_trend=states["context"],
            structure_trend=states["structure"],
            execution_trend=states["execution"],
            trend_alignment=hierarchy["alignment"],
            trend_state=states["execution"]["state"],
            reversal_status=states["execution"]["reversal_status"],
            price_action=pa.as_dict(),
            impulse_state=pa.impulse_state,
            correction_state=pa.correction_state,
            follow_through_status=follow_through,
            support_levels=tuple(z for z in nearby if z["role"] == "support"),
            resistance_levels=tuple(z for z in nearby if z["role"] == "resistance"),
            nearby_structural_levels=nearby,
            momentum_context={
                "behavior": pa.momentum_behavior,
                "basis": "closed_bar_displacement",
                "prediction": False,
            },
            evidence_set_id=evidence.evidence_set_id,
            evidence_status=evidence.evidence_quality,
            evidence_set=evidence.as_dict(),
            bullish_evidence=evidence.bullish_evidence,
            bearish_evidence=evidence.bearish_evidence,
            invalidating_evidence=evidence.invalidations,
            market_narrative=narrative,
        )
