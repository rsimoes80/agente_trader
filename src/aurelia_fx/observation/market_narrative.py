"""Objective narrative retaining facts, conflicts, unknowns and operational boundaries."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MarketNarrative:
    context: tuple[str, ...]
    behavior: tuple[str, ...]
    trends: dict
    conflicts: tuple
    missing: tuple[str, ...]
    state: str
    price_action: str
    evidence_status: str
    confluence: str
    confirmation: str = "requires_expectation_contract"
    trigger: str = "requires_predefined_event"
    risk_authorization: str = "not_evaluated"

    def as_dict(self):
        return asdict(self)
