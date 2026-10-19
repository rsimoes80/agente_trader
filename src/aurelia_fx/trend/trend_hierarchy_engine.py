"""Closed-bar aggregation and an explicit trend state machine per timeframe."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

from ..domain import Candle
from ..structure import analyze_structure


def timeframe_seconds(value: str) -> int:
    match = re.fullmatch(r"([MHD])(\d+)", value)
    if not match or int(match[2]) < 1:
        raise ValueError("Timeframe must be M<n>, H<n> or D<n>.")
    return {"M": 60, "H": 3600, "D": 86400}[match[1]] * int(match[2])


def timeframe_name(seconds: int) -> str:
    for prefix, scale in (("D", 86400), ("H", 3600), ("M", 60)):
        if seconds % scale == 0:
            return f"{prefix}{seconds // scale}"
    raise ValueError("Whole-minute timeframes required.")


@dataclass(frozen=True)
class HierarchyConfig:
    macro_timeframe: str
    context_timeframe: str
    structure_timeframe: str
    execution_timeframe: str
    confirmation_bars: int = 2

    def __post_init__(self):
        periods = [timeframe_seconds(t) for t in self.roles.values()]
        if periods != sorted(periods, reverse=True) or any(
            p % periods[-1] for p in periods
        ):
            raise ValueError(
                "Hierarchy must descend in integer multiples of the execution timeframe."
            )
        if (
            isinstance(self.confirmation_bars, bool)
            or not isinstance(self.confirmation_bars, int)
            or self.confirmation_bars < 2
        ):
            raise ValueError(
                "At least two distinct closed bars are required for confirmation."
            )

    @property
    def roles(self):
        return {
            role: getattr(self, role + "_timeframe")
            for role in ("macro", "context", "structure", "execution")
        }

    @classmethod
    def for_execution(cls, execution: str):
        base = timeframe_seconds(execution)
        return cls(*(timeframe_name(base * n) for n in (12, 6, 3, 1)))


class ClosedBarAggregator:
    """UTC-anchored complete buckets only; no forward-fill or partial HTF bars."""

    def __init__(self, config: HierarchyConfig, *, lookback: int = 300):
        self.base = timeframe_seconds(config.execution_timeframe)
        self.periods = {t: timeframe_seconds(t) for t in config.roles.values()}
        self.lookback = lookback
        self.history = {t: [] for t in self.periods}
        self.buffers = {t: [] for t in self.periods}
        self.last_base = None

    def reset(self):
        self.last_base = None
        for table in (self.history, self.buffers):
            for key in table:
                table[key].clear()

    def add(self, candle: Candle):
        if self.last_base is not None and candle.timestamp <= self.last_base:
            raise ValueError(
                "Aggregation requires strictly chronological base candles."
            )
        if candle.timestamp.timestamp() % self.base:
            raise ValueError("Base candle is not aligned to its timeframe.")
        self.last_base = candle.timestamp
        for name, seconds in self.periods.items():
            bucket = int(candle.timestamp.timestamp()) // seconds * seconds
            buffer = self.buffers[name]
            if (
                buffer
                and int(buffer[0].timestamp.timestamp()) // seconds * seconds != bucket
            ):
                buffer.clear()
            buffer.append(candle)
            expected = seconds // self.base
            if (
                len(buffer) == expected
                and int(buffer[0].timestamp.timestamp()) == bucket
                and all(
                    (b.timestamp - a.timestamp).total_seconds() == self.base
                    for a, b in zip(buffer, buffer[1:])
                )
            ):
                spread = (
                    buffer[-1].spread_pips
                    if all(b.spread_pips is not None for b in buffer)
                    else None
                )
                bar = Candle(
                    datetime.fromtimestamp(bucket, timezone.utc),
                    buffer[0].open,
                    max(b.high for b in buffer),
                    min(b.low for b in buffer),
                    buffer[-1].close,
                    sum(b.volume for b in buffer),
                    spread,
                )
                self.history[name].append(bar)
                self.history[name] = self.history[name][-self.lookback :]
                buffer.clear()
        return {key: tuple(value) for key, value in self.history.items()}


@dataclass(frozen=True)
class TrendState:
    timeframe: str
    timestamp_utc: str | None
    direction: str
    state: str
    structure: str
    last_confirmed_high: dict | None
    last_confirmed_low: dict | None
    dominant_swing: dict | None
    impulse_direction: str
    correction_direction: str
    structure_break_status: str
    reversal_status: str
    maturity_status: str
    evidence_status: str
    parent_timeframe: str | None
    relationship_with_parent: str
    data_quality: dict


class TrendHierarchyEngine:
    def __init__(self, config: HierarchyConfig, *, swing_window: int = 2):
        self.config, self.swing_window = config, swing_window
        self.previous: dict[str, TrendState] = {}
        self.counts: dict[str, tuple[str, int]] = {}
        self.anchors: dict[str, str] = {}

    def reset(self):
        self.previous.clear()
        self.counts.clear()
        self.anchors.clear()

    def classify(self, timeframe: str, candles: tuple[Candle, ...]) -> TrendState:
        previous = self.previous.get(timeframe)
        stamp = (
            (
                candles[-1].timestamp + timedelta(seconds=timeframe_seconds(timeframe))
            ).isoformat()
            if candles
            else None
        )
        if previous and previous.timestamp_utc == stamp:
            return previous
        structure = analyze_structure(
            candles, self.swing_window, bar_seconds=timeframe_seconds(timeframe)
        )
        highs = [s for s in structure.swings if s.kind == "high"]
        lows = [s for s in structure.swings if s.kind == "low"]
        high = asdict(highs[-1]) if highs else None
        low = asdict(lows[-1]) if lows else None
        candidate = structure.direction
        old_state = previous.state if previous else "UNKNOWN"
        anchor = self.anchors.get(timeframe)
        broken = None
        if previous and candles:
            if (
                anchor == "bullish"
                and previous.last_confirmed_low
                and candles[-1].close < previous.last_confirmed_low["price"]
            ):
                broken = "bearish"
            elif (
                anchor == "bearish"
                and previous.last_confirmed_high
                and candles[-1].close > previous.last_confirmed_high["price"]
            ):
                broken = "bullish"
        reversal = "none"
        if broken and candidate == anchor:
            candidate = (
                "mixed"  # Old pivots cannot reaffirm a trend below its protected swing.
            )
        state = old_state
        direction = "undefined"
        if broken and old_state in {
            "BULL_CONFIRMED",
            "BEAR_CONFIRMED",
            "BULL_WEAKENING",
            "BEAR_WEAKENING",
        }:
            state, reversal = "TRANSITION", "partial_reversal"
            self.counts.pop(timeframe, None)
        elif candidate in {"bullish", "bearish"}:
            bull = candidate == "bullish"
            potential, confirmed = (
                ("POTENTIAL_BULL", "BULL_CONFIRMED")
                if bull
                else ("POTENTIAL_BEAR", "BEAR_CONFIRMED")
            )
            prior_direction, count = self.counts.get(timeframe, (candidate, 0))
            count = count + 1 if prior_direction == candidate else 1
            self.counts[timeframe] = candidate, count
            opposite = "BEAR_CONFIRMED" if bull else "BULL_CONFIRMED"
            if old_state == opposite:
                state, reversal = (
                    ("BEAR_WEAKENING" if bull else "BULL_WEAKENING"),
                    "early_warning",
                )
            elif (
                old_state in {"BULL_WEAKENING", "BEAR_WEAKENING"}
                and candidate != anchor
            ):
                state, reversal = "TRANSITION", "partial_reversal"
            elif old_state == "TRANSITION" or (
                anchor and candidate != anchor and old_state != potential
            ):
                state, reversal = potential, "partial_reversal"
                self.counts[timeframe] = candidate, 1
            elif count >= self.config.confirmation_bars:
                state = confirmed
                if anchor and candidate != anchor:
                    reversal = "confirmed_reversal"
                elif previous and previous.reversal_status in {
                    "partial_reversal",
                    "early_warning",
                }:
                    reversal = "failed_reversal"
                self.anchors[timeframe] = candidate
            else:
                state = potential
                reversal = (
                    "partial_reversal" if anchor and candidate != anchor else "none"
                )
        elif candidate == "mixed":
            self.counts.pop(timeframe, None)
            if old_state in {"BULL_CONFIRMED", "BEAR_CONFIRMED"}:
                state, reversal = (
                    ("BULL_WEAKENING" if anchor == "bullish" else "BEAR_WEAKENING"),
                    "early_warning",
                )
            elif old_state in {"BULL_WEAKENING", "BEAR_WEAKENING"}:
                state, reversal = "TRANSITION", "partial_reversal"
            elif old_state == "TRANSITION":
                state, reversal = "TRANSITION", "partial_reversal"
            else:
                state = "RANGE"
        else:
            state = "UNKNOWN"
            self.counts.pop(timeframe, None)
        if state in {"POTENTIAL_BULL", "BULL_CONFIRMED", "BULL_WEAKENING"}:
            direction = "bullish"
        elif state in {"POTENTIAL_BEAR", "BEAR_CONFIRMED", "BEAR_WEAKENING"}:
            direction = "bearish"
        elif state in {"RANGE", "TRANSITION"}:
            direction = "neutral"
        result = TrendState(
            timeframe,
            stamp,
            direction,
            state,
            candidate,
            high,
            low,
            asdict(structure.swings[-1]) if structure.swings else None,
            structure.break_of_structure or "undefined",
            "undefined",
            broken or structure.break_of_structure or "none",
            reversal,
            "not_established",
            "confirmed_structure" if state.endswith("CONFIRMED") else "developing",
            None,
            "INSUFFICIENT_DATA",
            {
                "valid": bool(candles),
                "bars": len(candles),
                "reason": None
                if candidate != "insufficient_data"
                else "insufficient_confirmed_swings",
            },
        )
        self.previous[timeframe] = result
        return result

    def evaluate(
        self, histories: dict[str, tuple[Candle, ...]], *, as_of: datetime | None = None
    ) -> dict:
        execution = histories.get(self.config.execution_timeframe, ())
        cutoff = as_of or (
            execution[-1].timestamp
            + timedelta(seconds=timeframe_seconds(self.config.execution_timeframe))
            if execution
            else None
        )
        if cutoff is not None:
            for tf, values in histories.items():
                if (
                    values
                    and values[-1].timestamp + timedelta(seconds=timeframe_seconds(tf))
                    > cutoff
                ):
                    raise ValueError(
                        "A higher timeframe includes an unfinished or future candle."
                    )
        raw = {
            t: self.classify(t, histories.get(t, ()))
            for t in dict.fromkeys(self.config.roles.values())
        }
        states = {}
        parent = None
        for role, tf in self.config.roles.items():
            child = raw[tf]
            relationship = "INSUFFICIENT_DATA"
            if parent and child.state != "UNKNOWN" and parent.state != "UNKNOWN":
                if "TRANSITION" in {child.state, parent.state}:
                    relationship = "TRANSITIONING"
                elif child.state == "RANGE" and parent.direction in {
                    "bullish",
                    "bearish",
                }:
                    relationship = "RANGE_INSIDE_TREND"
                elif child.direction == parent.direction:
                    relationship = "ALIGNED"
                elif {child.direction, parent.direction} == {"bullish", "bearish"}:
                    bars = histories.get(tf, ())
                    protected = (
                        parent.last_confirmed_low
                        if parent.direction == "bullish"
                        else parent.last_confirmed_high
                    )
                    inside = bool(
                        bars
                        and protected
                        and (
                            bars[-1].close >= protected["price"]
                            if parent.direction == "bullish"
                            else bars[-1].close <= protected["price"]
                        )
                    )
                    relationship = "CORRECTING_PARENT" if inside else "COUNTER_TREND"
                else:
                    relationship = "CONFLICTING"
            child = replace(
                child,
                parent_timeframe=parent.timeframe if parent else None,
                relationship_with_parent=relationship,
                correction_direction=child.direction
                if relationship == "CORRECTING_PARENT"
                else "undefined",
            )
            states[role] = asdict(child)
            parent = child
        dominant = next(
            (
                states[r]["direction"]
                for r in ("context", "macro", "structure")
                if states[r]["state"] in {"BULL_CONFIRMED", "BEAR_CONFIRMED"}
            ),
            "undefined",
        )
        transition = any(
            s["state"] in {"TRANSITION", "BULL_WEAKENING", "BEAR_WEAKENING"}
            for s in states.values()
        )
        execution = states["execution"]["direction"]
        direction_class = (
            "TRANSITION"
            if transition
            else "UNDEFINED"
            if dominant == "undefined" or execution == "undefined"
            else "RANGE"
            if states["execution"]["state"] == "RANGE"
            else "WITH_TREND"
            if execution == dominant
            else "COUNTER_TREND"
        )
        alignment = {r + "_direction": s["direction"] for r, s in states.items()}
        alignment.update(
            alignment_status="TRANSITIONING"
            if transition
            else "ALIGNED"
            if all(s["direction"] == dominant for s in states.values())
            and dominant != "undefined"
            else "MIXED",
            dominant_direction=dominant,
            countertrend_risk="present"
            if direction_class == "COUNTER_TREND"
            else "not_observed",
            transition_risk="present" if transition else "not_observed",
            trade_direction_class=direction_class,
        )
        return {"states": states, "alignment": alignment}
