"""Categorical evidence with explicit feature lineage, contradictions and expiry."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta

from ..trend import timeframe_seconds


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    category: str
    source_component: str
    source_rule_id: str
    direction: str
    observation: str
    status: str
    quality: str
    relevance: str
    conflicts_with: tuple[str, ...]
    expires_at: str
    data_reference: str
    dependency_group: str


@dataclass(frozen=True)
class EvidenceSet:
    evidence_set_id: str
    snapshot_id: str
    symbol: str
    timestamp_utc: str
    items: tuple[Evidence, ...]
    bullish_evidence: tuple[str, ...]
    bearish_evidence: tuple[str, ...]
    neutral_evidence: tuple[str, ...]
    warnings: tuple[str, ...]
    invalidations: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    conflicts: tuple[tuple[str, str], ...]
    dominant_evidence: str
    confluence_status: str
    confirmation_status: str
    trigger_status: str
    evidence_quality: str
    valid_until: str
    independent_feature_groups: tuple[str, ...]
    independence_limit: str = (
        "feature_lineage_deduplication; statistical_independence_not_established"
    )

    def as_dict(self):
        return asdict(self)


class EvidenceEngine:
    def aggregate(
        self,
        items,
        *,
        snapshot_id: str,
        symbol: str,
        now: datetime,
        valid_until: datetime,
        confirmation_status: str = "not_evaluated",
        trigger_status: str = "not_evaluated",
    ):
        # Deduplicate identical facts, but preserve distinct and opposing observations.
        unique = {e.evidence_id: e for e in items}
        active = [
            e for e in unique.values() if datetime.fromisoformat(e.expires_at) > now
        ]
        expired = [
            e.evidence_id
            for e in unique.values()
            if datetime.fromisoformat(e.expires_at) <= now
        ]
        bull = [
            e
            for e in active
            if e.direction == "bullish"
            and e.status not in {"insufficient", "invalidating"}
        ]
        bear = [
            e
            for e in active
            if e.direction == "bearish"
            and e.status not in {"insufficient", "invalidating"}
        ]
        conflicts = tuple((a.evidence_id, b.evidence_id) for a in bull for b in bear)
        invalidations = tuple(
            e.evidence_id for e in active if e.status == "invalidating"
        )
        missing = tuple(
            e.observation for e in active if e.status == "insufficient"
        ) + tuple("expired:" + identity for identity in expired)
        dominant = (
            "neutral" if bool(bull) == bool(bear) else "bullish" if bull else "bearish"
        )
        directional = (
            bull if dominant == "bullish" else bear if dominant == "bearish" else []
        )
        groups = tuple(sorted({e.dependency_group for e in directional}))
        if invalidations:
            quality = "INVALIDATED"
        elif conflicts:
            quality = "CONFLICTED"
        elif not directional:
            quality = "INSUFFICIENT"
        elif missing:
            quality = "DEVELOPING"
        elif len(groups) < 2:
            quality = "WEAK"
        elif confirmation_status == "confirmed":
            quality = "CONFIRMED"
        elif len(groups) >= 3:
            quality = "STRONG_BUT_UNCONFIRMED"
        else:
            quality = "SUPPORTIVE"
        confluence = (
            "COHERENT_DISTINCT_FEATURES"
            if len(groups) >= 2 and not conflicts
            else "CONFLICTED"
            if conflicts
            else "NOT_ESTABLISHED"
        )
        enriched = []
        for e in unique.values():
            opposite = tuple(
                b if a == e.evidence_id else a
                for a, b in conflicts
                if e.evidence_id in {a, b}
            )
            enriched.append(
                replace(
                    e,
                    conflicts_with=opposite,
                    status="conflicting"
                    if opposite and e.status == "supportive"
                    else e.status,
                )
            )
        return EvidenceSet(
            snapshot_id + ":evidence",
            snapshot_id,
            symbol,
            now.isoformat(),
            tuple(enriched),
            tuple(e.evidence_id for e in bull),
            tuple(e.evidence_id for e in bear),
            tuple(e.evidence_id for e in active if e.direction == "neutral"),
            tuple(e.evidence_id for e in active if e.status == "warning"),
            invalidations,
            missing,
            conflicts,
            dominant,
            confluence,
            confirmation_status,
            trigger_status,
            quality,
            valid_until.isoformat(),
            groups,
        )

    def observe(
        self,
        *,
        snapshot_id,
        symbol,
        timeframe,
        now,
        validity_seconds,
        hierarchy,
        price_action,
        levels,
        quality,
        spread_pips,
        max_spread_pips,
        sessions,
        freshness_seconds,
        max_age_seconds,
        required_roles=("context", "structure"),
        data_reference="",
    ):
        until = now + timedelta(seconds=validity_seconds)
        items = []

        def add(
            key,
            category,
            component,
            direction,
            observation,
            status,
            group,
            tf=timeframe,
        ):
            items.append(
                Evidence(
                    snapshot_id + ":" + key,
                    now.isoformat(),
                    symbol,
                    tf,
                    category,
                    component,
                    "engineering.v3." + key,
                    direction,
                    observation,
                    status,
                    "descriptive_unvalidated",
                    "contextual",
                    (),
                    until.isoformat(),
                    data_reference,
                    group,
                )
            )

        seen = set()
        for role, state in hierarchy["states"].items():
            if state["timeframe"] in seen:
                continue
            seen.add(state["timeframe"])
            roles = [
                r
                for r, s in hierarchy["states"].items()
                if s["timeframe"] == state["timeframe"]
            ]
            required = any(r in required_roles for r in roles)
            stale = bool(
                state["timestamp_utc"]
                and (
                    now - datetime.fromisoformat(state["timestamp_utc"])
                ).total_seconds()
                > 1.5 * timeframe_seconds(state["timeframe"])
            )
            if state["state"] == "UNKNOWN" or stale:
                add(
                    "trend_" + role,
                    "trend",
                    "TrendHierarchyEngine",
                    "neutral",
                    role + ":insufficient_confirmed_swings",
                    "insufficient" if required else "warning",
                    "structure",
                    state["timeframe"],
                )
            else:
                add(
                    "trend_" + role,
                    "trend",
                    "TrendHierarchyEngine",
                    state["direction"]
                    if state["direction"] != "undefined"
                    else "neutral",
                    role + ":" + state["state"],
                    "warning"
                    if state["state"]
                    in {"TRANSITION", "BULL_WEAKENING", "BEAR_WEAKENING"}
                    else "supportive",
                    "structure",
                    state["timeframe"],
                )
        pressure = price_action.directional_pressure
        add(
            "bar_sequence",
            "price_action",
            "PriceActionReader",
            pressure,
            "closed_bar_pressure:" + pressure,
            "supportive" if price_action.data_quality["valid"] else "insufficient",
            "bar_sequence",
        )
        if price_action.failure_status not in {"none", "insufficient_data"}:
            add(
                "follow_through",
                "price_action",
                "PriceActionReader",
                "neutral",
                price_action.failure_status,
                "warning",
                "bar_sequence",
            )
        if not levels:
            add(
                "levels",
                "support_resistance",
                "SupportResistanceEngine",
                "neutral",
                "no_confirmed_zones",
                "insufficient",
                "structure",
            )
        else:
            add(
                "levels",
                "support_resistance",
                "SupportResistanceEngine",
                "neutral",
                "confirmed_zones_with_provenance",
                "supportive",
                "structure",
            )
        if not quality.valid:
            add(
                "data_invalid",
                "risk_environment",
                "DataQuality",
                "neutral",
                "invalid_market_data",
                "invalidating",
                "data_quality",
            )
        if (
            freshness_seconds is None
            or freshness_seconds < 0
            or freshness_seconds > max_age_seconds
        ):
            add(
                "data_stale",
                "risk_environment",
                "DataQuality",
                "neutral",
                "stale_or_unknown_data",
                "invalidating",
                "data_quality",
            )
        if spread_pips is None:
            add(
                "spread_missing",
                "risk_environment",
                "MarketObserver",
                "neutral",
                "spread_unavailable",
                "invalidating",
                "spread",
            )
        elif spread_pips > max_spread_pips:
            add(
                "spread_limit",
                "risk_environment",
                "MarketObserver",
                "neutral",
                "spread_incompatible",
                "invalidating",
                "spread",
            )
        if not sessions:
            add(
                "session",
                "session",
                "SessionEngine",
                "neutral",
                "outside_authorized_session",
                "warning",
                "session",
            )
        # No volume evidence: provider-specific tick activity alone is not validated market volume.
        return self.aggregate(
            items, snapshot_id=snapshot_id, symbol=symbol, now=now, valid_until=until
        )
