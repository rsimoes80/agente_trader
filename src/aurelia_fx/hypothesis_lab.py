"""Offline-only hypothesis proposal and experiment readiness checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .expectations import CandidateHypothesis


class ResearchStatus(str, Enum):
    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    REJECTED_BEFORE_TEST = "rejected_before_test"
    APPROVED_FOR_RESEARCH = "approved_for_research"


@dataclass(frozen=True, slots=True)
class ExperimentPlan:
    dataset_reference: str
    baseline: str
    measurable_metric: str
    rejection_threshold: str
    holdout_reference: str
    transaction_costs_included: bool
    lookahead_checked: bool
    attempt_number: int


def check_experiment(hypothesis: CandidateHypothesis, plan: ExperimentPlan) -> tuple[str, ...]:
    """Return blockers; caller must keep proposals in research until reviewed."""
    blockers: list[str] = []
    if not hypothesis.prediction.strip() or not hypothesis.rejection_criteria:
        blockers.append("FALSIFIABILITY_MISSING")
    if not plan.dataset_reference:
        blockers.append("DATASET_MISSING")
    if not plan.baseline:
        blockers.append("BASELINE_MISSING")
    if not plan.measurable_metric or not plan.rejection_threshold:
        blockers.append("MEASURABLE_CRITERIA_MISSING")
    if not plan.holdout_reference:
        blockers.append("UNTOUCHED_HOLDOUT_MISSING")
    if not plan.transaction_costs_included:
        blockers.append("TRANSACTION_COSTS_MISSING")
    if not plan.lookahead_checked:
        blockers.append("LOOKAHEAD_CHECK_MISSING")
    if plan.attempt_number < 1:
        blockers.append("ATTEMPT_COUNT_INVALID")
    return tuple(blockers)
