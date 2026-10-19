"""Immutable hypothesis expectations and expected-versus-observed evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Mapping
from uuid import uuid4


class ExpectationStatus(str, Enum):
    PROPOSED = "proposed"
    MONITORING = "monitoring"
    DEVELOPING_AS_EXPECTED = "developing_as_expected"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CONFIRMED = "confirmed"
    WEAKENING = "weakening"
    CONTRADICTED = "contradicted"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class CandidateHypothesis:
    hypothesis_id: str
    description: str
    prediction: str
    rejection_criteria: tuple[str, ...]
    source_experience_ids: tuple[str, ...] = ()
    status: str = "proposed"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.hypothesis_id or not self.prediction or not self.rejection_criteria:
            raise ValueError("Hipótese precisa de ID, previsão e critérios de rejeição.")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at precisa conter timezone.")


@dataclass(frozen=True, slots=True)
class ExpectationContract:
    expectation_id: str
    hypothesis_id: str
    symbol: str
    session: str
    direction: str
    expected_events: tuple[str, ...]
    invalidation_events: tuple[str, ...]
    expires_at: datetime
    strategy_id: str
    strategy_version: str
    tolerance: tuple[str, ...] = ()
    alert_events: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.direction not in {"long", "short", "neutral"}:
            raise ValueError("direction deve ser long, short ou neutral.")
        if not self.expected_events or not self.invalidation_events:
            raise ValueError("Contrato precisa definir eventos esperados e de invalidação.")
        if self.expires_at.tzinfo is None or self.created_at.tzinfo is None:
            raise ValueError("Datas do contrato precisam conter timezone.")
        if self.expires_at <= self.created_at:
            raise ValueError("Contrato deve expirar depois de criado.")


@dataclass(frozen=True, slots=True)
class Evaluation:
    evaluation_id: str
    expectation_id: str
    hypothesis_id: str
    status: ExpectationStatus
    favorable: tuple[str, ...]
    contrary: tuple[str, ...]
    missing: tuple[str, ...]
    observed_at: datetime
    execution_eligible: bool = False


class ExpectedVsObservedEngine:
    """Deterministic event-based evaluator. Confirmation alone never executes."""

    def evaluate(
        self,
        contract: ExpectationContract,
        observed_events: Mapping[str, bool],
        *,
        now: datetime | None = None,
        data_valid: bool = True,
    ) -> Evaluation:
        stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        favorable = tuple(event for event in contract.expected_events if observed_events.get(event) is True)
        contrary = tuple(event for event in contract.invalidation_events if observed_events.get(event) is True)
        missing = tuple(event for event in contract.expected_events if observed_events.get(event) is not True)
        if not data_valid:
            status = ExpectationStatus.INSUFFICIENT_DATA
        elif stamp >= contract.expires_at.astimezone(timezone.utc):
            status = ExpectationStatus.EXPIRED
        elif contrary:
            status = ExpectationStatus.INVALIDATED
        elif not missing:
            status = ExpectationStatus.CONFIRMED
        elif favorable:
            status = ExpectationStatus.PARTIALLY_CONFIRMED
        elif any(observed_events.get(event) is True for event in contract.alert_events):
            status = ExpectationStatus.WEAKENING
        else:
            status = ExpectationStatus.MONITORING
        return Evaluation(str(uuid4()), contract.expectation_id, contract.hypothesis_id,
                          status, favorable, contrary, missing, stamp, False)
