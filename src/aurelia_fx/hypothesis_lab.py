"""Offline-only hypothesis proposal and experiment readiness checks."""

from __future__ import annotations

from collections import defaultdict
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
    feature_dependence_reviewed: bool = False
    timeframe_lineage_recorded: bool = False


def check_experiment(
    hypothesis: CandidateHypothesis, plan: ExperimentPlan
) -> tuple[str, ...]:
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
    if not plan.feature_dependence_reviewed:
        blockers.append("EVIDENCE_DEPENDENCE_REVIEW_MISSING")
    if not plan.timeframe_lineage_recorded:
        blockers.append("TIMEFRAME_LINEAGE_MISSING")
    return tuple(blockers)


V3_RESEARCH_QUESTIONS = (
    "trend_alignment_incremental_value",
    "countertrend_confirmation_requirements",
    "redundant_evidence_ablation",
    "independent_feature_information",
    "partial_reversal_information",
    "no_follow_through_invalidation",
    "structural_zone_distance",
    "price_action_by_regime",
    "session_and_volatility_effects",
)


def v3_cohort_report(records, *, minimum_samples: int = 30) -> dict:
    """Descriptive outcome cohorts using frozen entry context, not promotion or optimization."""
    if minimum_samples < 1:
        raise ValueError("Minimum sample size must be positive.")
    unique = {
        r["decision_id"]: r
        for r in records
        if r.get("financial_result", {}).get("result_in_r") is not None
    }
    groups = defaultdict(list)
    for record in unique.values():
        for key in (
            "trade_direction_class",
            "evidence_state",
            "partial_reversal_state",
            "observed_follow_through",
        ):
            groups[(key, str(record.get(key, "unknown")))].append(
                record["financial_result"]["result_in_r"]
            )
    return {
        "status": "needs_review",
        "unique_outcomes": len(unique),
        "questions": list(V3_RESEARCH_QUESTIONS),
        "cohorts": [
            {
                "feature": key,
                "value": value,
                "sample_count": len(values),
                "minimum_sample_floor_met": len(values) >= minimum_samples,
                "mean_r": sum(values) / len(values)
                if len(values) >= minimum_samples
                else None,
            }
            for (key, value), values in sorted(groups.items())
        ],
        "interpretation": "descriptive_only; correlated_features; no_causal_or_statistical_claim; no_promotion",
    }
