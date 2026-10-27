"""Causal candidate replay and joint V4/Timestral learning records.

Counterfactual candidate labels are explicitly separate from portfolio results.
"""

from __future__ import annotations

import json
from datetime import time,timedelta

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


def intelligence_session(*, profile=None):
    hierarchy = HierarchyConfig("H4", "H1", "M15", "M5")
    return MarketIntelligenceSession(
        symbol=profile.symbol if profile else "EURUSD",
        hierarchy=hierarchy,
        aggregator=CalendarBarAggregator(
            hierarchy, market_calendar=profile.calendar.slot_tradable if profile else slot_tradable,
            extra_periods={"D1": 86400}
        ),
        gap_detector=profile.calendar.unexpected_gap if profile else unexpected_broker_gap,
        sessions=profile.session_windows() if profile else SESSIONS,
        max_spread_pips=profile.max_spread_units if profile else 2,
        pip_size=profile.price_unit if profile else 0.0001,
    )


def simulator(units, *, profile=None):
    return ExecutionSimulator(
        profile.execution_config(units) if profile else ExecutionConfig(fixed_units=units, max_holding_bars=12),
        RiskLimits(0.5, 2, 5, profile.max_spread_units if profile else 2, 2, 5),
        instrument_context=dict(symbol=profile.symbol, profile_id=profile.fingerprint,
                                instrument_id=profile.contract.key, quantity_unit='lots') if profile else None,
    )


def simulation_window(profile,bar,active_sessions):
    if not profile:return active_sessions,None
    active=active_sessions if profile.allows_entry(bar.timestamp) else ()
    reason=None if profile.allows_entry(bar.timestamp+timedelta(minutes=5)) else 'CALENDAR_CLOSE'
    return active,reason


def request_for(setup, sample_id):
    if setup['snapshot'].get('profile_id'):
        sample_id=fingerprint(dict(profile=setup['snapshot']['profile_id'], sample_id=sample_id))
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


def cached_forecast(memory, candles, config, adapter, *, profile=None):
    identity = dict(configuration=config.fingerprint, context=[c.as_dict() for c in candles])
    if profile:
        identity['instrument'] = profile.learning_namespace
    key = fingerprint(identity)
    with memory.pool.connection() as c:
        row = c.execute(
            """SELECT payload_json FROM project_records
            WHERE record_type='agent_forecast_cache' AND record_key=%s LIMIT 1""",
            (key,),
        ).fetchone()
    if row:
        payload = json.loads(row["payload_json"])
        if payload.get('symbol', 'EURUSD') != (profile.symbol if profile else 'EURUSD') or payload.get('profile_id') != (profile.fingerprint if profile else None):
            raise ValueError('FORECAST_INSTRUMENT_MISMATCH')
        return key, payload["output"]
    output = adapter.forecast([c.close for c in candles])
    memory.record_project_data(
        "agent_forecast_cache",
        key,
        dict(
            cache_key=key,
            symbol=profile.symbol if profile else 'EURUSD',
            profile_id=profile.fingerprint if profile else None,
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
