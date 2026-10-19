"""Explainable V3 gates. Technical perception cannot authorize execution."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IntelligencePolicy:
    allowed_direction_classes: tuple[str, ...] = ("WITH_TREND",)
    required_trend_roles: tuple[str, ...] = ("context", "structure")
    allowed_evidence_states: tuple[str, ...] = (
        "SUPPORTIVE",
        "STRONG_BUT_UNCONFIRMED",
        "CONFIRMED",
    )
    veto_target_obstruction: bool = True
    countertrend_research_approved: bool = False

    def __post_init__(self):
        roles = {"macro", "context", "structure", "execution"}
        if not self.required_trend_roles or not set(self.required_trend_roles) <= roles:
            raise ValueError("Configure required trend roles explicitly.")
        if not set(self.allowed_direction_classes) <= {
            "WITH_TREND",
            "COUNTER_TREND",
            "RANGE",
            "TRANSITION",
            "UNDEFINED",
        }:
            raise ValueError("Unknown strategy direction class.")


class DecisionEngine:
    def __init__(self, policy: IntelligencePolicy):
        self.policy = policy

    def context_gate(self, snapshot, *, side=None, target=None):
        if snapshot.invalidating_evidence:
            return "EVIDENCE_INVALIDATED"
        states = snapshot.trend_hierarchy["states"]
        if any(
            states[role]["state"] == "UNKNOWN"
            for role in self.policy.required_trend_roles
        ):
            return "TREND_CONTEXT_INSUFFICIENT"
        if any(
            states[role]["state"] in {"TRANSITION", "BULL_WEAKENING", "BEAR_WEAKENING"}
            for role in self.policy.required_trend_roles
        ):
            return "TREND_TRANSITION_WAIT"
        if (
            snapshot.trend_alignment["transition_risk"] == "present"
            and "TRANSITION" not in self.policy.allowed_direction_classes
        ):
            return "TREND_TRANSITION_WAIT"
        if any(
            states[role]["state"].startswith("POTENTIAL")
            for role in self.policy.required_trend_roles
        ):
            return "TREND_CONFIRMATION_PENDING"
        if snapshot.evidence_status not in self.policy.allowed_evidence_states:
            return "EVIDENCE_" + snapshot.evidence_status
        if side is not None:
            dominant = snapshot.trend_alignment["dominant_direction"]
            desired = "bullish" if side == "long" else "bearish"
            direction_class = (
                "UNDEFINED"
                if dominant == "undefined"
                else "WITH_TREND"
                if desired == dominant
                else "COUNTER_TREND"
            )
            if direction_class not in self.policy.allowed_direction_classes:
                return "DIRECTION_CLASS_NOT_ALLOWED"
            if (
                direction_class == "COUNTER_TREND"
                and not self.policy.countertrend_research_approved
            ):
                return "COUNTERTREND_REQUIRES_VALIDATED_CRITERIA"
            if self.policy.veto_target_obstruction and target is not None:
                last = snapshot.market_structure["last_close"]
                for zone in snapshot.nearby_structural_levels:
                    if (
                        side == "long"
                        and zone["role"] == "resistance"
                        and last < zone["lower_bound"] < target
                        or side == "short"
                        and zone["role"] == "support"
                        and target < zone["upper_bound"] < last
                    ):
                        return "TARGET_OBSTRUCTED_BY_STRUCTURAL_ZONE"
        return None

    @staticmethod
    def trigger_gate(evaluation):
        if evaluation.status.value != "confirmed":
            return "EXPECTATION_NOT_CONFIRMED"
        if evaluation.trigger_state != "triggered":
            return "WAITING_FOR_TRIGGER"
        return None
