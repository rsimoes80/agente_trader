"""Causal swing and price-structure observations from closed candles."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from .domain import Candle


@dataclass(frozen=True, slots=True)
class Swing:
    kind: Literal["high", "low"]
    index: int
    price: float
    timestamp: str
    confirmed_at: str


@dataclass(frozen=True, slots=True)
class StructureSnapshot:
    direction: str
    swings: tuple[Swing, ...]
    break_of_structure: str | None
    liquidity_sweep: str | None
    last_close: float


def analyze_structure(
    candles: tuple[Candle, ...] | list[Candle],
    window: int = 2,
    *,
    bar_seconds: int | None = None,
) -> StructureSnapshot:
    if window < 1:
        raise ValueError("window precisa ser positivo.")
    highs: list[Swing] = []
    lows: list[Swing] = []
    duration = (
        bar_seconds
        if bar_seconds is not None
        else min(
            (
                (b.timestamp - a.timestamp).total_seconds()
                for a, b in zip(candles, candles[1:])
                if b.timestamp > a.timestamp
            ),
            default=0,
        )
    )
    for index in range(window, len(candles) - window):
        current = candles[index]
        left = candles[index - window : index]
        right = candles[index + 1 : index + window + 1]
        if all(current.high > candle.high for candle in (*left, *right)):
            highs.append(
                Swing(
                    "high",
                    index,
                    current.high,
                    current.timestamp.isoformat(),
                    (
                        candles[index + window].timestamp + timedelta(seconds=duration)
                    ).isoformat(),
                )
            )
        if all(current.low < candle.low for candle in (*left, *right)):
            lows.append(
                Swing(
                    "low",
                    index,
                    current.low,
                    current.timestamp.isoformat(),
                    (
                        candles[index + window].timestamp + timedelta(seconds=duration)
                    ).isoformat(),
                )
            )

    direction = "insufficient_data"
    if len(highs) >= 2 and len(lows) >= 2:
        higher_high = highs[-1].price > highs[-2].price
        higher_low = lows[-1].price > lows[-2].price
        lower_high = highs[-1].price < highs[-2].price
        lower_low = lows[-1].price < lows[-2].price
        if higher_high and higher_low:
            direction = "bullish"
        elif lower_high and lower_low:
            direction = "bearish"
        else:
            direction = "mixed"

    last = candles[-1] if candles else None
    bos: str | None = None
    sweep: str | None = None
    if last is not None:
        previous_high = next(
            (s for s in reversed(highs) if s.index < len(candles) - 1), None
        )
        previous_low = next(
            (s for s in reversed(lows) if s.index < len(candles) - 1), None
        )
        if previous_high and last.close > previous_high.price:
            bos = "bullish"
        elif previous_low and last.close < previous_low.price:
            bos = "bearish"
        if (
            previous_low
            and last.low < previous_low.price
            and last.close > previous_low.price
        ):
            sweep = "bullish"
        elif (
            previous_high
            and last.high > previous_high.price
            and last.close < previous_high.price
        ):
            sweep = "bearish"
    ordered_swings = sorted((*highs, *lows), key=lambda swing: swing.index)
    return StructureSnapshot(
        direction, tuple(ordered_swings), bos, sweep, last.close if last else 0.0
    )
