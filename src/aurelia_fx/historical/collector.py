"""Read-only MT5 backfill and rolling refresh into the existing journal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from ..source_clock import validate_source_clock
from .core import SECONDS, TIMEFRAMES, VERSION, closed_rows, readiness, summarize, utc
from .research import study


def collect(repository, fetch, *, days=30, full=False, run_study=False, now=None):
    if not 30 <= days <= 60:
        raise ValueError("Histórico inicial requer 30 a 60 dias corridos.")
    reference_now = now
    now = utc(now or datetime.now(timezone.utc))
    start = now - timedelta(days=days)
    previous = repository.latest()
    clock = None
    reports = {}
    imports = {}
    for timeframe in TIMEFRAMES:
        seconds = SECONDS[timeframe]
        old = (previous or {}).get("timeframes", {}).get(timeframe, {})
        last = utc(old["last"]) if old.get("last") else None
        incremental = (
            not full
            and old.get("ready")
            and previous.get("days") == days
            and last is not None
        )
        span = (now - last).total_seconds() if incremental else days * 86400
        count = max(100, min(100_000, int(span / seconds) + 20))
        data = fetch("EURUSD", timeframe, count, include_current=False)
        checked = utc(reference_now or datetime.now(timezone.utc))
        source_clock = validate_source_clock(data, now=checked)
        if data.get("timeframe") != timeframe or data.get("symbol") not in {
            "EURUSD",
            "EUR/USD",
        }:
            raise ValueError("Identidade do histórico MT5 incompatível.")
        if clock is not None and clock["clock_id"] != source_clock["clock_id"]:
            raise ValueError("Servidor/relógio mudou durante a captura histórica.")
        if (
            previous
            and incremental
            and previous.get("clock_id") != source_clock["clock_id"]
        ):
            data = fetch(
                "EURUSD",
                timeframe,
                max(100, int(days * 86400 / seconds) + 20),
                include_current=False,
            )
            source_clock = validate_source_clock(
                data, now=utc(reference_now or datetime.now(timezone.utc))
            )
            if clock is not None and clock["clock_id"] != source_clock["clock_id"]:
                raise ValueError("Fonte mudou durante a recaptura histórica.")
        clock = source_clock
        rows = closed_rows(data["candles"], timeframe, start=start, as_of=now)
        imports[timeframe] = repository.ingest(rows, clock=clock, timeframe=timeframe)
        frozen = repository.candles(
            clock_id=clock["clock_id"], timeframe=timeframe, start=start, as_of=now
        )
        reports[timeframe] = summarize(
            frozen, timeframe, start=start, as_of=now, days=days
        )
    baseline = dict(
        version=VERSION,
        symbol="EURUSD",
        clock_id=clock["clock_id"],
        source_clock=clock,
        days=days,
        start=start.isoformat(),
        as_of=now.isoformat(),
        timeframes=reports,
        imports=imports,
        orders_enabled=False,
        learning_mode="offline_research_only",
    )
    baseline["baseline_id"] = hashlib.sha256(
        json.dumps(baseline, sort_keys=True).encode()
    ).hexdigest()
    baseline["blocker"] = readiness(baseline, as_of=now, clock_id=clock["clock_id"])
    baseline["status"] = (
        "ready" if baseline["blocker"] is None else "insufficient_history"
    )
    repository.record_baseline(baseline)
    if run_study and baseline["status"] == "ready":
        rows = repository.candles(
            clock_id=clock["clock_id"], timeframe="M5", start=start, as_of=now
        )
        research = study(rows, baseline_id=baseline["baseline_id"])
        repository.memory.record_project_data(
            "historical_hypothesis_study", research["study_id"], research
        )
    return baseline
