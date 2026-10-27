"""Read-only MT5 backfill and rolling refresh into the existing journal."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from ..source_clock import validate_source_clock
from .core import SECONDS, TIMEFRAMES, VERSION, closed_rows, readiness, summarize, utc
from .research import study


def collect_warmup(repository,fetch,*,clock_id,days=60,now=None):
    """Extra M5 context for aggregated H4/H1/M15/D1, without duplicating M1."""
    if not 30<=days<=60:raise ValueError('Warmup requires 30 to 60 days.')
    reference_now=now
    now=utc(now or datetime.now(timezone.utc));start=now-timedelta(days=days)
    symbol=repository.symbol;profile=getattr(repository,'profile',None)
    data=fetch(symbol,'M5',int(days*86400/300)+20,include_current=False)
    source=validate_source_clock(data,now=utc(reference_now or datetime.now(timezone.utc)))
    if source['clock_id']!=clock_id or data.get('symbol')!=symbol or data.get('timeframe')!='M5':
        raise ValueError('WARMUP_SOURCE_INSTRUMENT_MISMATCH')
    unit=data.get('pip_size',.0001)
    if profile and unit!=profile.price_unit:raise ValueError('WARMUP_PRICE_UNIT_MISMATCH')
    rows=closed_rows(data['candles'],'M5',start=start,as_of=now)
    imported=repository.ingest(rows,clock=source,timeframe='M5')
    frozen=repository.candles(clock_id=clock_id,timeframe='M5',start=start,as_of=now)
    measured=summarize(frozen,'M5',start=start,as_of=now,days=days,pip_size=unit,profile=profile)
    report=dict(version='historical-warmup-v1',symbol=symbol,clock_id=clock_id,
        **(dict(profile_id=profile.fingerprint) if profile else {}),
        start=start.isoformat(),as_of=now.isoformat(),days=days,timeframe='M5',
        status='ready' if measured['ready'] else 'insufficient_history',statistics=measured,
        scope='M5 context for causal timeframe aggregation; full 30-day baseline remains separate',imports=imported)
    report['baseline_id']=hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
    repository.memory.record_project_data(repository.record_type('historical_warmup'),report['baseline_id'],report)
    return report


def collect(repository, fetch, *, days=30, full=False, run_study=False, now=None):
    if not 30 <= days <= 60:
        raise ValueError("Histórico inicial requer 30 a 60 dias corridos.")
    reference_now = now
    symbol=getattr(repository,'symbol','EURUSD')
    profile=getattr(repository,'profile',None)
    now = utc(now or datetime.now(timezone.utc))
    start = now - timedelta(days=days)
    previous = repository.latest()
    clock = None
    reports = {}
    imports = {}
    price_unit=None
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
        data = fetch(symbol, timeframe, count, include_current=False)
        checked = utc(reference_now or datetime.now(timezone.utc))
        source_clock = validate_source_clock(data, now=checked)
        unit=data.get('pip_size',0.0001)
        if profile and unit!=profile.price_unit:raise ValueError('HISTORY_PRICE_UNIT_PROFILE_MISMATCH')
        if price_unit is not None and price_unit!=unit:raise ValueError('Unidade de preço mudou durante a coleta.')
        price_unit=unit
        accepted={symbol,'EUR/USD'} if symbol=='EURUSD' else {symbol}
        if data.get("timeframe") != timeframe or data.get("symbol") not in accepted:
            raise ValueError("Identidade do histórico MT5 incompatível.")
        if clock is not None and clock["clock_id"] != source_clock["clock_id"]:
            raise ValueError("Servidor/relógio mudou durante a captura histórica.")
        if (
            previous
            and incremental
            and previous.get("clock_id") != source_clock["clock_id"]
        ):
            data = fetch(
                symbol,
                timeframe,
                max(100, int(days * 86400 / seconds) + 20),
                include_current=False,
            )
            source_clock = validate_source_clock(
                data, now=utc(reference_now or datetime.now(timezone.utc))
            )
            if data.get('symbol') not in accepted or data.get('timeframe')!=timeframe:
                raise ValueError('Identidade do histórico mudou durante a recaptura.')
            if clock is not None and clock["clock_id"] != source_clock["clock_id"]:
                raise ValueError("Fonte mudou durante a recaptura histórica.")
        clock = source_clock
        rows = closed_rows(data["candles"], timeframe, start=start, as_of=now)
        imports[timeframe] = repository.ingest(rows, clock=clock, timeframe=timeframe)
        frozen = repository.candles(
            clock_id=clock["clock_id"], timeframe=timeframe, start=start, as_of=now
        )
        reports[timeframe] = summarize(
            frozen, timeframe, start=start, as_of=now, days=days, pip_size=price_unit,profile=profile
        )
    baseline = dict(
        version=VERSION,
        symbol=symbol,
        **(dict(profile_id=profile.fingerprint,research_profile=profile.as_dict()) if profile else {}),
        price_unit=price_unit,
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
    baseline["blocker"] = readiness(baseline, as_of=now, clock_id=clock["clock_id"],profile=profile)
    baseline["status"] = (
        "ready" if baseline["blocker"] is None else "insufficient_history"
    )
    repository.record_baseline(baseline)
    if run_study and baseline["status"] == "ready":
        rows = repository.candles(
            clock_id=clock["clock_id"], timeframe="M5", start=start, as_of=now
        )
        research = study(rows, baseline_id=baseline["baseline_id"])
        research['symbol']=symbol
        repository.memory.record_project_data(
            repository.record_type("historical_hypothesis_study"), research["study_id"], research
        )
    return baseline
