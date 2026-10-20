"""Closed UTC buckets complete over the existing NY-close Forex calendar.

Short Friday/Sunday buckets are retained only after their nominal close. Missing
tradable M5 bars still invalidate the bucket; no prices are filled or invented.
"""

from datetime import datetime, timezone

from .domain import Candle
from .replay_data import market_open
from .trend import ClosedBarAggregator


class CalendarBarAggregator(ClosedBarAggregator):
    def __init__(
        self, config, *, lookback=300, market_calendar=market_open, extra_periods=None
    ):
        super().__init__(config, lookback=lookback)
        self.expected_cache = {}
        self.market_calendar = market_calendar
        for name, seconds in (extra_periods or {}).items():
            if seconds < self.base or seconds % self.base:
                raise ValueError(
                    "Additional context periods must be multiples of the base timeframe."
                )
            if name not in self.periods:
                self.periods[name] = seconds
                self.history[name] = []
                self.buffers[name] = []

    def reset(self):
        super().reset()
        self.expected_cache.clear()

    def expected(self, name, bucket, seconds):
        cached = self.expected_cache.get(name)
        if cached is None or cached[0] != bucket:
            stamps = [
                t
                for t in range(bucket, bucket + seconds, self.base)
                if self.market_calendar(datetime.fromtimestamp(t, timezone.utc))
            ]
            self.expected_cache[name] = (bucket, stamps)
        return self.expected_cache[name][1]

    def emit(self, name, bucket, seconds, known_at):
        buffer = self.buffers[name]
        if known_at < bucket + seconds or not buffer:
            return False
        expected = self.expected(name, bucket, seconds)
        if not expected or [int(b.timestamp.timestamp()) for b in buffer] != expected:
            return False
        bar = Candle(
            datetime.fromtimestamp(bucket, timezone.utc),
            buffer[0].open,
            max(b.high for b in buffer),
            min(b.low for b in buffer),
            buffer[-1].close,
            sum(b.volume for b in buffer),
            buffer[-1].spread_pips
            if all(b.spread_pips is not None for b in buffer)
            else None,
        )
        self.history[name].append(bar)
        self.history[name] = self.history[name][-self.lookback :]
        buffer.clear()
        return True

    def add(self, candle):
        if self.last_base is not None and candle.timestamp <= self.last_base:
            raise ValueError(
                "Aggregation requires strictly chronological base candles."
            )
        if candle.timestamp.timestamp() % self.base:
            raise ValueError("Base candle is not aligned to its timeframe.")
        self.last_base = candle.timestamp
        known_at = int(candle.timestamp.timestamp()) + self.base
        for name, seconds in self.periods.items():
            bucket = int(candle.timestamp.timestamp()) // seconds * seconds
            buffer = self.buffers[name]
            if buffer:
                old_bucket = int(buffer[0].timestamp.timestamp()) // seconds * seconds
                if old_bucket != bucket:
                    self.emit(name, old_bucket, seconds, known_at)
                    buffer.clear()
            buffer.append(candle)
            self.emit(name, bucket, seconds, known_at)
        return {name: tuple(value) for name, value in self.history.items()}
