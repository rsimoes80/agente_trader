"""Experimental breakout/retest baseline. No learned or book-derived entry rules."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from .domain import Candidate, Candle
from .expectations import (
    CandidateHypothesis,
    Evaluation,
    ExpectationContract,
    ExpectedVsObservedEngine,
)
from .structure import analyze_structure

STRATEGY_ID = "research_breakout_retest"
STRATEGY_VERSION = "2.0-v3"


@dataclass(frozen=True)
class PendingHypothesis:
    hypothesis: CandidateHypothesis
    contract: ExpectationContract
    level: float
    stop: float
    zone_tolerance: float
    retest_at: datetime | None = None
    retest_trigger: float | None = None


def propose(
    candles: list[Candle],
    *,
    now: datetime,
    hypothesis_id: str,
    expectation_id: str,
    session: str,
    symbol: str,
    swing_window: int,
    tolerance: float,
    lifetime_seconds: int,
    source_experiences: tuple[str, ...],
) -> PendingHypothesis | None:
    # All reference swings were already confirmed BEFORE the breakout candle.
    if len(candles) < 3:
        return None
    structure = analyze_structure(candles[:-1], swing_window)
    if structure.direction not in {"bullish", "bearish"}:
        return None
    long = structure.direction == "bullish"
    highs = [s for s in structure.swings if s.kind == "high"]
    lows = [s for s in structure.swings if s.kind == "low"]
    if not highs or not lows:
        return None
    level = highs[-1].price if long else lows[-1].price
    stop = lows[-1].price if long else highs[-1].price
    previous, current = candles[-2:]
    broke = (
        previous.close <= level < current.close
        if long
        else previous.close >= level > current.close
    )
    if not broke or (current.low <= stop if long else current.high >= stop):
        return None
    side = "long" if long else "short"
    hypothesis = CandidateHypothesis(
        hypothesis_id,
        f"{side} breakout followed by retest of {level:.5f}",
        "A later bar retests the frozen zone; a subsequent close crosses the retest extreme.",
        ("touch structural stop", "expire", "session changes", "invalid data"),
        source_experience_ids=source_experiences,
        created_at=now,
    )
    contract = ExpectationContract(
        expectation_id,
        hypothesis_id,
        symbol,
        session,
        side,
        ("zone_retested",),
        ("stop_touched",),
        now + timedelta(seconds=lifetime_seconds),
        STRATEGY_ID,
        STRATEGY_VERSION,
        tolerance=(f"zone +/- {tolerance:.8f}",),
        created_at=now,
        trigger_event="trigger_closed",
        expected_context=(("trend_direction", "bullish" if long else "bearish"),),
    )
    return PendingHypothesis(hypothesis, contract, level, stop, tolerance)


def compare(
    pending: PendingHypothesis,
    candle: Candle,
    *,
    now: datetime,
    evaluation_id: str,
    data_valid: bool,
    evidence_set: dict | None = None,
    observed_context: dict | None = None,
) -> tuple[PendingHypothesis, Evaluation]:
    long = pending.contract.direction == "long"
    invalidated = candle.low <= pending.stop if long else candle.high >= pending.stop
    retested = (
        candle.low <= pending.level + pending.zone_tolerance
        and candle.high >= pending.level - pending.zone_tolerance
    )
    trigger = False
    if pending.retest_at is not None and now > pending.retest_at:
        trigger = (
            candle.close > pending.retest_trigger
            if long
            else candle.close < pending.retest_trigger
        )
    elif retested and data_valid:
        pending = replace(
            pending, retest_at=now, retest_trigger=candle.high if long else candle.low
        )
    result = ExpectedVsObservedEngine().evaluate(
        pending.contract,
        {
            "zone_retested": pending.retest_at is not None,
            "trigger_closed": trigger,
            "stop_touched": invalidated,
        },
        now=now,
        data_valid=data_valid,
        evidence_set=evidence_set,
        observed_context=observed_context,
    )
    return pending, replace(result, evaluation_id=evaluation_id)


def candidate(
    pending: PendingHypothesis, candle: Candle, *, reward_multiple: float
) -> Candidate:
    distance = abs(candle.close - pending.stop)
    sign = 1 if pending.contract.direction == "long" else -1
    return Candidate(
        pending.contract.direction,
        candle.close,
        pending.stop,
        candle.close + sign * distance * reward_multiple,
        pending.contract.expires_at,
        (
            "prior_confirmed_structure",
            "breakout_close",
            "later_retest",
            "later_trigger_close",
        ),
    )
