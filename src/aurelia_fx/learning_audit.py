"""Local dataset eligibility audit. Observations are not losing trades."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .historical.core import utc

MIN_ROWS = 100  # Existing legacy learner floor; not a new promotion criterion.
REQUIRED_CONTEXT = {
    "regime",
    "regime_model_version",
    "evidence_state",
    "trade_direction_class",
}


def assess(rows, *, observations):
    rejected = Counter()
    known = set()
    cohorts = defaultdict(list)
    for row in rows:
        payload = (
            json.loads(row["payload_json"])
            if isinstance(row["payload_json"], str)
            else row["payload_json"]
        )
        if payload.get("status") != "closed":
            rejected["OUTCOME_NOT_CLOSED"] += 1
            continue
        signature = (
            row["symbol"],
            row["strategy_id"],
            row["strategy_version"],
            row["config_hash"],
            payload.get("entry_at"),
            payload.get("side"),
        )
        if signature in known:
            rejected["DUPLICATE_REPLAY_SAMPLE"] += 1
            continue
        finance = payload.get("financial_result") or {}
        fields = (
            "net_pnl",
            "result_in_r",
            "initial_risk",
            "spread_cost",
            "slippage_cost",
            "commission",
        )
        if any(
            not isinstance(finance.get(k), (int, float))
            or isinstance(finance[k], bool)
            or not math.isfinite(finance[k])
            for k in fields
        ):
            rejected["OUTCOME_OR_COSTS_MISSING"] += 1
            continue
        if finance["initial_risk"] <= 0 or any(finance[k] < 0 for k in fields[3:]):
            rejected["INVALID_RISK_OR_COSTS"] += 1
            continue
        try:
            if utc(payload["observed_at"]) <= utc(payload["entry_at"]):
                raise ValueError("Outcome before entry")
        except (ValueError, KeyError, TypeError):
            rejected["OUTCOME_TIME_INVALID"] += 1
            continue
        context = row.get("frozen_context") or {}
        if not REQUIRED_CONTEXT <= set(context) or any(
            not isinstance(context[k], str) or not context[k] for k in REQUIRED_CONTEXT
        ):
            rejected["FROZEN_V4_CONTEXT_MISSING"] += 1
            continue
        known.add(signature)
        key = (
            row["symbol"],
            row["strategy_id"],
            row["strategy_version"],
            row["config_hash"],
            context["regime_model_version"],
        )
        cohorts[key].append(
            dict(
                event_id=payload["event_id"],
                entry_at=payload["entry_at"],
                outcome=int(finance["net_pnl"] > 0),
                result_in_r=finance["result_in_r"],
            )
        )
    groups = []
    for key, samples in cohorts.items():
        samples.sort(key=lambda s: s["entry_at"])
        groups.append(
            dict(
                symbol=key[0],
                strategy_id=key[1],
                strategy_version=key[2],
                config_hash=key[3],
                regime_model_version=key[4],
                scope="simulated_only",
                samples=len(samples),
                wins=sum(s["outcome"] for s in samples),
                losses=sum(not s["outcome"] for s in samples),
                minimum_rows=MIN_ROWS,
                sample_floor_met=len(samples) >= MIN_ROWS,
                dataset_sha256=hashlib.sha256(
                    json.dumps(samples, sort_keys=True).encode()
                ).hexdigest(),
            )
        )
    report = dict(
        version="learning-eligibility-v1",
        source="simulated_execution_events",
        closed_events_inspected=len(rows),
        eligible_samples=sum(g["samples"] for g in groups),
        no_trade_observations=observations,
        excluded=dict(rejected),
        cohorts=groups,
        training_started=False,
        correlated_cohorts_not_independent=True,
        automatic_promotion=False,
        external_llm_required=False,
        blockers=["APPROVED_V4_TO_LEARNER_FEATURE_SCHEMA_REQUIRED"],
        interpretation="Dataset eligibility only; no classifier, profitability or promotion claim.",
    )
    if not groups or not any(g["sample_floor_met"] for g in groups):
        report["blockers"].append("INSUFFICIENT_CLOSED_TRADE_SAMPLES")
    report["report_id"] = hashlib.sha256(
        json.dumps(report, sort_keys=True).encode()
    ).hexdigest()
    report["created_at"] = datetime.now(timezone.utc).isoformat()
    return report


def build_report(memory):
    with memory.pool.connection() as c:
        rows = c.execute("""SELECT e.payload_json,d.symbol,d.strategy_id,d.strategy_version,
            d.payload_json::jsonb ->> 'config_hash' AS config_hash,
            d.payload_json::jsonb -> 'intelligence_context' AS frozen_context
            FROM simulated_execution_events e JOIN decisions d USING(decision_id)
            WHERE e.status='closed' ORDER BY e.observed_at_utc DESC LIMIT 5001""").fetchall()
        observations = c.execute(
            "SELECT COUNT(*) AS n FROM decisions WHERE action='NO_TRADE'"
        ).fetchone()["n"]
    report = assess(rows[:5000], observations=observations)
    report["scan_truncated"] = len(rows) > 5000
    return report
