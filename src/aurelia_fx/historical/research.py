"""Frozen, small hypothesis studies. Final holdout is never scored."""

import hashlib
import json
import statistics

from .core import utc


def study(rows, *, baseline_id):
    n = len(rows)
    bounds = (0, int(n * 0.6), int(n * 0.8), n)
    result = dict(
        version="historical-hypotheses-v2",
        baseline_id=baseline_id,
        split="chronological 60/20/20",
        holdout_accessed=False,
        automatic_promotion=False,
        hypotheses=["last_candle_direction_continues", "last_candle_direction_reverts"],
        rejection="Validation directional accuracy must exceed frozen development-majority baseline; minimum 30 samples.",
        causal_rule="Predictor uses candle body at close; labels use later bars of the same partition only.",
        sampling="Non-overlapping horizons, gaps rejected; different horizons remain correlated.",
        economic_validation=False,
        results=[],
        partitions={},
    )
    result["prior_access"] = (
        "Not auditable; rolling studies may overlap previously viewed data. Not independent confirmation."
    )
    for phase, (lo, hi) in zip(
        ("development", "validation", "holdout"), zip(bounds, bounds[1:])
    ):
        part = rows[lo:hi]
        result["partitions"][phase] = dict(
            bars=len(part),
            first=part[0]["timestamp"] if part else None,
            last=part[-1]["timestamp"] if part else None,
            sha256=hashlib.sha256(
                json.dumps(part, sort_keys=True).encode()
            ).hexdigest(),
        )
    for horizon in (3, 6, 12):
        majority = 1
        for phase, (lo, hi) in zip(
            ("development", "validation"), zip(bounds, bounds[1:])
        ):
            part = rows[lo:hi]
            samples = []
            for index in range(0, len(part) - horizon, horizon):
                window = part[index : index + horizon + 1]
                if any(
                    (utc(b["timestamp"]) - utc(a["timestamp"])).total_seconds() != 300
                    for a, b in zip(window, window[1:])
                ):
                    continue
                body = part[index]["close"] - part[index]["open"]
                move = part[index + horizon]["close"] - part[index]["close"]
                if body == 0:
                    continue
                samples.append(
                    (
                        1 if body > 0 else -1,
                        1 if move > 0 else -1 if move < 0 else 0,
                        move / 0.0001,
                    )
                )
            if phase == "development" and samples:
                majority = (
                    1
                    if sum(s[1] > 0 for s in samples) >= sum(s[1] < 0 for s in samples)
                    else -1
                )
            baseline = (
                sum(s[1] == majority for s in samples) / len(samples)
                if samples
                else None
            )
            for hypothesis, multiplier in [
                ("last_candle_direction_continues", 1),
                ("last_candle_direction_reverts", -1),
            ]:
                hits = sum(s[0] * multiplier == s[1] for s in samples)
                accuracy = hits / len(samples) if samples else None
                result["results"].append(
                    dict(
                        hypothesis=hypothesis,
                        horizon=horizon,
                        phase=phase,
                        samples=len(samples),
                        neutral_outcomes=sum(s[1] == 0 for s in samples),
                        directional_accuracy=accuracy,
                        baseline_directional_accuracy=baseline,
                        baseline_direction=majority,
                        gross_signed_move_pips=statistics.fmean(
                            s[0] * multiplier * s[2] for s in samples
                        )
                        if samples
                        else None,
                        classification="INSUFFICIENT_DATA"
                        if len(samples) < 30
                        else "RESEARCH_ONLY_CANDIDATE"
                        if accuracy > baseline
                        else "NOT_DEMONSTRATED",
                        trading_costs_included=False,
                        orders_enabled=False,
                    )
                )
    result["study_id"] = hashlib.sha256(
        json.dumps(result, sort_keys=True).encode()
    ).hexdigest()
    return result
