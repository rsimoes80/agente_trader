"""Causal candidate replay and joint V4/Timestral learning records.

Counterfactual candidate labels are explicitly separate from portfolio results.
"""

from __future__ import annotations

import json
from datetime import time

from .agent_model import fingerprint
from .broker_calendar import slot_tradable, unexpected_broker_gap
from .calendar_aggregation import CalendarBarAggregator
from .domain import RiskLimits
from .execution_simulator import EntryRequest, ExecutionConfig, ExecutionSimulator
from .historical.core import utc
from .market_intelligence import MarketIntelligenceSession
from .sessions import SessionWindow
from .trend import HierarchyConfig

SESSIONS = (
    SessionWindow("london", "Europe/London", time(8), time(17)),
    SessionWindow("new_york", "America/New_York", time(8), time(17)),
)


def intelligence_session():
    hierarchy = HierarchyConfig("H4", "H1", "M15", "M5")
    return MarketIntelligenceSession(
        symbol="EURUSD",
        hierarchy=hierarchy,
        aggregator=CalendarBarAggregator(
            hierarchy, market_calendar=slot_tradable, extra_periods={"D1": 86400}
        ),
        gap_detector=unexpected_broker_gap,
        sessions=SESSIONS,
        max_spread_pips=2,
        pip_size=0.0001,
    )


def simulator(units):
    return ExecutionSimulator(
        ExecutionConfig(fixed_units=units, max_holding_bars=12),
        RiskLimits(0.5, 2, 5, 2, 2, 5),
    )


def request_for(setup, sample_id):
    return EntryRequest(
        sample_id,
        setup["snapshot"]["snapshot_id"],
        sample_id + ":hypothesis",
        setup["candidate"],
        utc(setup["signal_at"]),
        setup["snapshot"]["session"][0],
        setup["snapshot"]["regime"],
        setup["snapshot"],
    )


def cached_forecast(memory, candles, config, adapter):
    key = fingerprint(
        dict(configuration=config.fingerprint, context=[c.as_dict() for c in candles])
    )
    with memory.pool.connection() as c:
        row = c.execute(
            """SELECT payload_json FROM project_records
            WHERE record_type='agent_forecast_cache' AND record_key=%s LIMIT 1""",
            (key,),
        ).fetchone()
    if row:
        return key, json.loads(row["payload_json"])["output"]
    output = adapter.forecast([c.close for c in candles])
    memory.record_project_data(
        "agent_forecast_cache",
        key,
        dict(
            cache_key=key,
            input_hash=fingerprint([c.as_dict() for c in candles]),
            configuration=config.fingerprint,
            input_last=candles[-1].timestamp.isoformat(),
            input_bars=len(candles),
            output=output,
        ),
    )
    return key, output


def build_samples(*args, **kwargs):
    from .agent_dataset import build_samples as build

    return build(*args, **kwargs)
