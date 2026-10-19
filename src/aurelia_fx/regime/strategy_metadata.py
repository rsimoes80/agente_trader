"""Strategy eligibility precedes setup search; it never authorizes an order."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    version: str
    allowed_regimes: tuple[str, ...] = ("TREND",)
    prohibited_regimes: tuple[str, ...] = ("RANGE", "UNKNOWN", "TRANSITION")
    allowed_transitions: tuple[str, ...] = ()
    direction_requirements: tuple[str, ...] = ("WITH_TREND",)
    confirmation_requirements: tuple[str, ...] = ("zone_retested",)
    location_requirements: tuple[str, ...] = ("no_target_obstruction",)
    data_requirements: tuple[str, ...] = ("closed_bars", "valid_data", "fresh_context")

    def __post_init__(self):
        valid = {"TREND", "RANGE", "TRANSITION", "UNKNOWN"}
        if (
            not self.allowed_regimes
            or not set(self.allowed_regimes) <= valid
            or not set(self.prohibited_regimes) <= valid
            or set(self.allowed_regimes) & set(self.prohibited_regimes)
            or "UNKNOWN" in self.allowed_regimes
        ):
            raise ValueError("Invalid strategy regime metadata")

    def evaluate(self, snapshot):
        regime = snapshot.regime
        reason = (
            "REGIME_UNKNOWN"
            if regime == "UNKNOWN"
            else "REGIME_MISMATCH"
            if regime in self.prohibited_regimes or regime not in self.allowed_regimes
            else "TRANSITION_UNCLEAR"
            if regime == "TRANSITION"
            and snapshot.regime_subtype not in self.allowed_transitions
            else "BREAKOUT_ATTEMPT_UNCONFIRMED"
            if snapshot.breakout_status in {"ATTEMPT", "DEVELOPING"}
            else None
        )
        if reason is None and regime == "RANGE":
            features = getattr(snapshot, "regime_state", {}).get("features", {})
            if snapshot.regime_subtype != "ESTABLISHED":
                reason = "RANGE_NOT_ESTABLISHED"
            elif features.get("range_width_acceptable") is False:
                reason = "RANGE_TOO_NARROW"
            elif (
                getattr(snapshot, "regime_stability", "descriptive_stable")
                != "descriptive_stable"
            ):
                reason = "RANGE_TOO_UNSTABLE"
            elif "range_boundary" in self.location_requirements and getattr(
                snapshot, "market_location", {}
            ).get("relative_location") not in {"UPPER_AREA", "LOWER_AREA"}:
                reason = "RANGE_LOCATION_UNFAVORABLE"
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "regime": regime,
            "status": "REJECTED" if reason else "ELIGIBLE_FOR_RESEARCH",
            "reason": reason,
            "regime_match": reason is None,
            "operational_authorization": False,
        }


REGIME_NO_TRADE_REASONS = (
    "RANGE_NOT_ESTABLISHED",
    "RANGE_TOO_NARROW",
    "RANGE_TOO_UNSTABLE",
    "RANGE_LOCATION_UNFAVORABLE",
    "BREAKOUT_ATTEMPT_UNCONFIRMED",
    "FAILED_BREAKOUT_UNRESOLVED",
    "TRANSITION_UNCLEAR",
    "REGIME_MISMATCH",
    "REGIME_UNKNOWN",
    "INSUFFICIENT_EVIDENCE",
    "RISK_REJECTED",
)
