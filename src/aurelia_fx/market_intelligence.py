"""Read-only streaming facade for the legacy monitor; never authorizes trades."""

from datetime import datetime, timedelta, timezone

from .domain import DataQuality
from .market_data import validate_candles
from .observer import MarketObserver
from .replay_data import unexpected_gap
from .sessions import SessionEngine, SessionWindow
from .trend import ClosedBarAggregator, HierarchyConfig, timeframe_seconds


class MarketIntelligenceSession:
    def __init__(
        self,
        *,
        symbol,
        hierarchy: HierarchyConfig,
        sessions: tuple[SessionWindow, ...],
        max_spread_pips: float,
        pip_size: float,
        swing_window: int = 2,
    ):
        self.symbol, self.hierarchy = symbol, hierarchy
        self.seconds = timeframe_seconds(hierarchy.execution_timeframe)
        self.aggregator = ClosedBarAggregator(hierarchy)
        self.observer = MarketObserver(
            SessionEngine(sessions),
            hierarchy_config=hierarchy,
            max_spread_pips=max_spread_pips,
            swing_window=swing_window,
            level_tolerance=2 * pip_size,
        )
        self.history = []
        self.last = None
        self.snapshot = None

    def update(self, rows, *, spread_pips, observed_at=None):
        candles, quality = validate_candles(rows)
        if not quality.valid:
            raise ValueError("Invalid stream candles: " + "; ".join(quality.errors))
        now = observed_at or datetime.now(timezone.utc)
        if self.last and candles[-1].timestamp == self.last.timestamp:
            self.snapshot = self.observer.observe(
                symbol=self.symbol,
                timeframe=self.hierarchy.execution_timeframe,
                candles=self.history,
                quality=DataQuality(True, latest_timestamp=self.last.timestamp),
                spread_pips=spread_pips,
                observed_at=now,
                histories_by_timeframe=self.aggregator.history,
                validity_seconds=self.seconds,
                data_reference="live_closed_bars",
            )
            return self.snapshot
        if self.last and candles[-1].timestamp < self.last.timestamp:
            raise ValueError("Cannot rewind a streaming intelligence session.")
        fresh = [
            bar
            for bar in candles
            if self.last is None or bar.timestamp > self.last.timestamp
        ]
        for i, bar in enumerate(fresh):
            gap = self.last is not None and unexpected_gap(self.last, bar, self.seconds)
            if gap:
                self.history.clear()
                self.observer.reset()
                self.aggregator.reset()
            self.history.append(bar)
            self.history = self.history[-300:]
            histories = self.aggregator.add(bar)
            stamp = (
                now
                if i == len(fresh) - 1
                else bar.timestamp + timedelta(seconds=self.seconds)
            )
            self.snapshot = self.observer.observe(
                symbol=self.symbol,
                timeframe=self.hierarchy.execution_timeframe,
                candles=self.history,
                quality=DataQuality(
                    not gap,
                    ("UNEXPECTED_MARKET_GAP",) if gap else (),
                    (),
                    bar.timestamp,
                ),
                spread_pips=spread_pips,
                observed_at=stamp,
                histories_by_timeframe=histories,
                validity_seconds=self.seconds,
                data_reference="live_closed_bars",
            )
            self.last = bar
        return self.snapshot


def observation_only_result(legacy: dict, snapshot) -> dict:
    plan = {key: legacy[key] for key in ("entry", "stop", "target") if key in legacy}
    result = {
        key: value
        for key, value in legacy.items()
        if key not in {"entry", "stop", "target", "confidence_pct", "risk_scale"}
    }
    result.update(
        signal="WAIT",
        legacy_candidate=legacy.get("signal", "WAIT"),
        hypothetical_legacy_plan=plan,
        market_intelligence=snapshot.as_dict(),
        operational_status="OBSERVATION_ONLY",
        orders_enabled_by_application=False,
        reason_code="EXPECTATION_TRIGGER_RISK_REQUIRED",
        evidence_calibrated=False,
        message=f"Leitura V3: {snapshot.evidence_status}. Aguarda hipótese, confirmação, gatilho e validação de risco no agente.",
    )
    return result
