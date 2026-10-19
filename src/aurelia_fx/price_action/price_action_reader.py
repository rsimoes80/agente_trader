"""Measurements and sequences only. No next-bar forecasts or trade actions."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from statistics import median

from ..trend import timeframe_seconds


@dataclass(frozen=True)
class PriceActionObservation:
    observation_id: str
    timestamp_utc: str
    symbol: str
    timeframe: str
    bar_count: int
    directional_pressure: str
    impulse_state: str
    correction_state: str
    expansion_state: str
    overlap_state: str
    breakout_status: str
    retest_status: str
    failure_status: str
    swing_progression: str
    momentum_behavior: str
    volatility_behavior: str
    candle_sequence_features: tuple[dict, ...]
    continuation_evidence: tuple[str, ...]
    exhaustion_evidence: tuple[str, ...]
    reversal_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    data_quality: dict

    def as_dict(self):
        return asdict(self)


class PriceActionReader:
    def __init__(
        self, *, expansion_multiple: float = 1.5, contraction_multiple: float = 0.67
    ):
        if not 0 < contraction_multiple < 1 < expansion_multiple:
            raise ValueError("Invalid descriptive range thresholds.")
        self.expansion_multiple, self.contraction_multiple = (
            expansion_multiple,
            contraction_multiple,
        )

    def read(
        self,
        candles,
        *,
        symbol: str,
        timeframe: str,
        now: datetime,
        observation_id: str,
    ):
        bars = tuple(candles)
        if (
            bars
            and bars[-1].timestamp + timedelta(seconds=timeframe_seconds(timeframe))
            > now
        ):
            raise ValueError(
                "Price action requires closed bars available at the observation time."
            )
        features = []
        for bar in bars[-5:]:
            extent = bar.high - bar.low
            features.append(
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "range": extent,
                    "body": abs(bar.close - bar.open),
                    "body_fraction": abs(bar.close - bar.open) / extent
                    if extent
                    else 0,
                    "upper_wick": bar.high - max(bar.open, bar.close),
                    "lower_wick": min(bar.open, bar.close) - bar.low,
                    "close_location": (bar.close - bar.low) / extent if extent else 0.5,
                    "direction": "bullish"
                    if bar.close > bar.open
                    else "bearish"
                    if bar.close < bar.open
                    else "neutral",
                }
            )
        pressure = "neutral"
        expansion = overlap = breakout = retest = failure = momentum = (
            "insufficient_data"
        )
        continuation, exhaustion, reversal, conflicts = [], [], [], []
        if len(bars) >= 3:
            last, previous, before = bars[-1], bars[-2], bars[-3]
            change = last.close - bars[max(0, len(bars) - 5)].close
            pressure = (
                "bullish" if change > 0 else "bearish" if change < 0 else "neutral"
            )
            baseline = median(b.high - b.low for b in bars[max(0, len(bars) - 21) : -1])
            extent = last.high - last.low
            ratio = extent / baseline if baseline else None
            expansion = (
                "expanding"
                if ratio and ratio > self.expansion_multiple
                else "contracting"
                if ratio is not None and ratio < self.contraction_multiple
                else "normal"
            )
            intersection = max(
                0, min(last.high, previous.high) - max(last.low, previous.low)
            )
            overlap = "overlapping" if intersection > 0 else "separated"
            features[-1].update(
                relative_range=ratio,
                overlap_range=intersection,
                gap_from_previous_close=last.open - previous.close,
                displacement=last.close - previous.close,
                progress_per_bar=change / min(4, len(bars) - 1),
            )
            breakout = (
                "bullish"
                if last.close > previous.high
                else "bearish"
                if last.close < previous.low
                else "none"
            )
            retest = (
                "bullish"
                if previous.close > before.high
                and last.low <= before.high <= last.high
                and last.close > before.high
                else (
                    "bearish"
                    if previous.close < before.low
                    and last.low <= before.low <= last.high
                    and last.close < before.low
                    else "none"
                )
            )
            if previous.close > before.high:
                if last.close <= before.high:
                    failure = "failed_bullish_breakout"
                    conflicts.append(failure)
                elif last.close <= previous.close:
                    failure = "no_bullish_follow_through"
                    conflicts.append(failure)
                else:
                    continuation.append("bullish_follow_through")
                    failure = "none"
            elif previous.close < before.low:
                if last.close >= before.low:
                    failure = "failed_bearish_breakout"
                    conflicts.append(failure)
                elif last.close >= previous.close:
                    failure = "no_bearish_follow_through"
                    conflicts.append(failure)
                else:
                    continuation.append("bearish_follow_through")
                    failure = "none"
            else:
                failure = "none"
            step, prior = (
                abs(last.close - previous.close),
                abs(previous.close - before.close),
            )
            momentum = (
                "decelerating"
                if step < prior
                else "accelerating"
                if step > prior
                else "unchanged"
            )
            if momentum == "decelerating":
                exhaustion.append(
                    "smaller_close_to_close_progress; not_a_reversal_forecast"
                )
            if last.high > previous.high and last.close < previous.high:
                reversal.append("higher_extreme_closed_back_below_previous_high")
            if last.low < previous.low and last.close > previous.low:
                reversal.append("lower_extreme_closed_back_above_previous_low")
        return PriceActionObservation(
            observation_id,
            now.isoformat(),
            symbol,
            timeframe,
            len(bars),
            pressure,
            "displacement_observed"
            if breakout in {"bullish", "bearish"}
            else "not_established",
            "retest_observed"
            if retest in {"bullish", "bearish"}
            else "not_established",
            expansion,
            overlap,
            breakout,
            retest,
            failure,
            "see_confirmed_structure",
            momentum,
            expansion,
            tuple(features),
            tuple(continuation),
            tuple(exhaustion),
            tuple(reversal),
            tuple(conflicts),
            {
                "valid": len(bars) >= 3,
                "missing": () if len(bars) >= 3 else ("at_least_three_closed_bars",),
            },
        )
