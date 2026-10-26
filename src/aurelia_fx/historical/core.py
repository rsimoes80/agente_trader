"""Causal historical statistics, with explicit market-calendar assumptions."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone

from ..domain import Candle
from ..replay_data import market_open
from ..sessions import SessionEngine, SessionWindow

SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}
TIMEFRAMES = tuple(SECONDS)
VERSION = "historical-baseline-v1"
SESSIONS = SessionEngine(
    (
        SessionWindow("london", "Europe/London", time(8), time(17)),
        SessionWindow("new_york", "America/New_York", time(8), time(17)),
    )
)


def utc(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("Histórico exige timestamps com timezone.")
    return stamp.astimezone(timezone.utc)


def closed_rows(rows, timeframe, *, start, as_of):
    seconds = SECONDS[timeframe]
    start, as_of = utc(start), utc(as_of)
    previous = None
    result = []
    for row in rows:
        stamp = utc(row["timestamp"])
        if previous is not None and stamp <= previous:
            raise ValueError("Histórico duplicado ou fora de ordem.")
        previous = stamp
        if stamp < start or stamp + timedelta(seconds=seconds) > as_of:
            continue
        candle = Candle(
            stamp,
            *(float(row[k]) for k in ("open", "high", "low", "close")),
            float(row.get("volume", 0)),
            row.get("spread_pips"),
        )
        if min(candle.open, candle.high, candle.low, candle.close) <= 0:
            raise ValueError("Preço histórico inválido.")
        result.append({**row, **candle.as_dict()})
    return result


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo = math.floor(index)
    hi = math.ceil(index)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def describe(rows):
    spreads = [r["spread_pips"] for r in rows if r.get("spread_pips") is not None]
    ranges = [(r["high"] - r["low"]) / 0.0001 for r in rows]
    returns = [r["_return"] for r in rows if r.get("_return") is not None]
    return dict(
        bars=len(rows),
        returns=len(returns),
        spread_observed_fraction=len(spreads) / len(rows) if rows else None,
        mean_range_pips=statistics.fmean(ranges) if ranges else None,
        p95_range_pips=percentile(ranges, 0.95),
        mean_spread_pips=statistics.fmean(spreads) if spreads else None,
        p95_spread_pips=percentile(spreads, 0.95),
        mean_tick_volume=statistics.fmean(r["volume"] for r in rows) if rows else None,
        mean_log_return=statistics.fmean(returns) if returns else None,
        volatility_log_return=statistics.stdev(returns) if len(returns) > 1 else None,
        positive_return_fraction=sum(v > 0 for v in returns) / len(returns)
        if returns
        else None,
    )


def trading_age_seconds(start, end):
    """Elapsed open-market time under the existing NY weekly calendar.

    This does not excuse holidays or unexplained gaps. Live quote freshness is
    checked separately by source_clock and is never changed by this function.
    """
    stamp, end = utc(start), utc(end)
    total = 0.0
    while stamp < end:
        boundary = stamp.replace(second=0, microsecond=0) + timedelta(minutes=1)
        following = min(boundary, end)
        if market_open(stamp):
            total += (following - stamp).total_seconds()
        stamp = following
    return total


def summarize(rows, timeframe, *, start, as_of, days=30):
    start, as_of = utc(start), utc(as_of)
    seconds = SECONDS[timeframe]
    rows = closed_rows(rows, timeframe, start=start, as_of=as_of)
    sessions = defaultdict(list)
    hours = defaultdict(list)
    gaps = []
    previous = None
    for row in rows:
        stamp = utc(row["timestamp"])
        row["_return"] = None
        if previous is not None:
            elapsed = (stamp - utc(previous["timestamp"])).total_seconds()
            if elapsed == seconds:
                row["_return"] = math.log(row["close"] / previous["close"])
            elif len(gaps) < 100:
                gaps.append(
                    dict(
                        before=previous["timestamp"],
                        after=row["timestamp"],
                        seconds=elapsed,
                    )
                )
        previous = row
        session = SESSIONS.identify(stamp + timedelta(seconds=seconds)).active_sessions
        sessions[session[0] if session else "outside_session"].append(row)
        hours[str(stamp.hour)].append(row)
    # Five-day FX convention, not a provider holiday calendar. Large TFs use
    # coverage by trading duration: broker H4/D1 boundaries need not align to UTC midnight.
    minute = start.replace(second=0, microsecond=0)
    if minute < start:
        minute += timedelta(minutes=1)
    trading_minutes = 0
    while minute + timedelta(minutes=1) <= as_of:
        trading_minutes += market_open(minute)
        minute += timedelta(minutes=1)
    expected = max(1, int(trading_minutes * 60 / seconds))
    coverage = min(1.0, len(rows) / expected)
    first = utc(rows[0]["timestamp"]) if rows else None
    last = utc(rows[-1]["timestamp"]) if rows else None
    complete_start = first is not None and (first - start).total_seconds() <= max(
        3 * 86400, seconds * 2
    )
    freshness_limit = max(6 * 3600, seconds * 2)
    fresh = last is not None and (
        (as_of - last - timedelta(seconds=seconds)).total_seconds() <= freshness_limit
        or trading_age_seconds(last + timedelta(seconds=seconds), as_of) <= freshness_limit
    )
    ready = (
        coverage >= 0.95
        and complete_start
        and fresh
        and len(rows) >= max(10, int(expected * 0.95))
    )
    canonical = [
        {k: v for k, v in row.items() if not k.startswith("_")} for row in rows
    ]
    return dict(
        timeframe=timeframe,
        days=days,
        start=start.isoformat(),
        as_of=as_of.isoformat(),
        first=first.isoformat() if first else None,
        last=last.isoformat() if last else None,
        expected_bars=expected,
        coverage=coverage,
        calendar="FX weekly New York 17:00; holidays not modeled",
        freshness_basis="elapsed FX weekly trading time; original tolerance unchanged",
        gaps=gaps,
        gaps_truncated=len(gaps) == 100,
        ready=ready,
        status="ready" if ready else "insufficient_history",
        dataset_sha256=hashlib.sha256(
            json.dumps(canonical, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        statistics=describe(rows),
        by_session={k: describe(v) for k, v in sessions.items()},
        by_utc_hour={k: describe(v) for k, v in hours.items()},
    )


def readiness(baseline, *, as_of, clock_id):
    if not baseline:
        return "HISTORY_BASELINE_REQUIRED"
    cutoff = utc(as_of)
    if baseline.get("clock_id") != clock_id or baseline.get("version") != VERSION:
        return "HISTORY_SOURCE_MISMATCH"
    if utc(baseline["as_of"]) > cutoff:
        return "HISTORY_BASELINE_FROM_FUTURE"
    if (cutoff - utc(baseline["as_of"])).total_seconds() > 6 * 3600:
        return "HISTORY_BASELINE_STALE"
    if baseline.get("days", 0) < 30 or set(baseline.get("timeframes", {})) != set(
        TIMEFRAMES
    ):
        return "HISTORY_BASELINE_REQUIRED"
    if any(not item.get("ready") for item in baseline["timeframes"].values()):
        return "HISTORY_COVERAGE_INSUFFICIENT"
    return None
