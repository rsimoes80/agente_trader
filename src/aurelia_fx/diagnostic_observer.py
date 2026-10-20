"""Continuous read-only MT5 observation through the existing bridge proxy."""

import hashlib
import json
import threading
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from urllib.request import urlopen
from urllib.error import HTTPError
from uuid import uuid4

from .decision_engine import DecisionEngine, IntelligencePolicy
from .domain import AgentState, Decision, DecisionAction
from .experience_memory import ExperienceRecord
from .market_intelligence import MarketIntelligenceSession
from .replay_strategy import STRATEGY_METADATA
from .sessions import SessionWindow
from .trend import HierarchyConfig, timeframe_seconds


class MarketSourceUnavailable(RuntimeError):
    def __init__(self, status, message):
        self.status, self.public_message = status, message
        super().__init__(message)


class DiagnosticObserver:
    def __init__(self, memory, repository, url, stop, code_version="unknown"):
        self.code_version = code_version
        self.memory, self.repository, self.url, self.stop = (
            memory,
            repository,
            url,
            stop,
        )
        self.state = {
            "status": "starting",
            "source": "MT5 read-only",
            "orders_enabled": False,
        }
        self.lock = threading.Lock()
        self.session = None
        self.ready = False
        self.last_saved = None
        self.run_id = "observer-" + str(uuid4())
        self.hierarchy = HierarchyConfig.for_execution("M5")
        self.policy = DecisionEngine(IntelligencePolicy(), STRATEGY_METADATA)

    def status(self):
        with self.lock:
            return dict(self.state)

    def update_status(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self):
        thread = threading.Thread(target=self.run, name="regime-observer", daemon=True)
        thread.start()

    def run(self):
        while not self.stop.is_set():
            try:
                with self.memory.pool.connection() as lease:
                    acquired = lease.execute(
                        "SELECT pg_try_advisory_lock(70616010) AS acquired"
                    ).fetchone()["acquired"]
                    if acquired:
                        try:
                            self.collect(lease)
                        finally:
                            if not lease.closed:
                                lease.execute("SELECT pg_advisory_unlock(70616010)")
                    else:
                        self.update_status(
                            status="passive",
                            message="Outro observador já mantém a coleta neste banco.",
                        )
            except Exception as exc:
                self.update_status(
                    status="unavailable",
                    message="Reconectando ao PostgreSQL.",
                    error_type=type(exc).__name__,
                )
            self.stop.wait(20)

    def collect(self, lease):
        checkpoint = self.repository.recent_records("diagnostic_observer_checkpoint", 1)
        self.last_saved = checkpoint[0]["last_candle"] if checkpoint else None
        while not self.stop.is_set():
            lease.execute("SELECT 1")
            try:
                self.poll()
            except Exception as exc:
                self.update_status(
                    status="unavailable",
                    error_type=type(exc).__name__,
                    message=exc.public_message
                    if isinstance(exc, MarketSourceUnavailable)
                    else "Fonte ou persistência indisponível. Nenhuma observação foi autorizada para operar.",
                    source_status=exc.status
                    if isinstance(exc, MarketSourceUnavailable)
                    else None,
                    checked_at=datetime.now(timezone.utc).isoformat(),
                )
            self.stop.wait(20)

    def poll(self):
        now = datetime.now(timezone.utc)
        try:
            with urlopen(self.url, timeout=12) as response:
                raw = response.read(4_000_001)
        except HTTPError as exc:
            body = exc.read(4000).decode("utf-8", errors="replace")
            if "Falha ao ler histórico" in body:
                raise MarketSourceUnavailable(
                    "history_unavailable",
                    "MT5 conectado, mas sem histórico pela API. Abra EURUSD M5 no terminal e carregue os candles.",
                ) from None
            raise MarketSourceUnavailable(
                "bridge_unavailable",
                "Ponte MT5 indisponível. Verifique Windows, ponte e terminal conectado.",
            ) from None
        if len(raw) > 4_000_000:
            raise ValueError("Bridge response too large")
        data = json.loads(raw)
        if not data.get("ok") or data.get("timeframe") != "M5":
            raise ValueError("Invalid bridge data")
        seconds = timeframe_seconds("M5")
        if any(
            datetime.fromisoformat(row["timestamp"]) > now + timedelta(seconds=5)
            for row in data["candles"]
        ):
            raise MarketSourceUnavailable(
                "source_clock_ahead",
                "O histórico contém horários futuros em relação a UTC. Verifique o fuso da fonte antes de coletar; horários não foram corrigidos automaticamente.",
            )
        rows = [
            row
            for row in data["candles"]
            if datetime.fromisoformat(row["timestamp"]) + timedelta(seconds=seconds)
            <= now
        ]
        if not rows:
            raise ValueError("No closed candles")
        quote = data.get("quote") or {}
        pip = float(data.get("pip_size", 0.0001))
        spread = (
            (quote["ask"] - quote["bid"]) / pip
            if "ask" in quote and "bid" in quote
            else None
        )
        if self.session is None or not self.ready:
            self.update_status(
                status="warming",
                message="Preparando histórico fechado e classificação inicial.",
                history_bars=len(rows),
            )
            self.session = MarketIntelligenceSession(
                symbol="EURUSD",
                hierarchy=self.hierarchy,
                sessions=(
                    SessionWindow("london", "Europe/London", time(8), time(17)),
                    SessionWindow("new_york", "America/New_York", time(8), time(17)),
                ),
                max_spread_pips=2,
                pip_size=pip,
            )
            config = {
                "timeframe": "M5",
                "symbol": "EURUSD",
                "hierarchy": asdict(self.hierarchy),
                "regime_config": asdict(self.session.observer.regimes.config),
            }
            self.config_hash = hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest()
            if not self.repository.query(
                "SELECT artifact_id FROM experiment_artifacts WHERE artifact_id=%s",
                (self.run_id + ":started",),
            ):
                self.record_start(config)
            # Bootstrap state; only new observations after the checkpoint are journaled.
            prior = [
                row
                for row in rows
                if self.last_saved and row["timestamp"] <= self.last_saved
            ]
            if prior:
                self.session.update(
                    prior,
                    spread_pips=spread,
                    observed_at=datetime.fromisoformat(prior[-1]["timestamp"])
                    + timedelta(seconds=seconds),
                )
            if not self.last_saved:
                if len(rows) > 1:
                    self.session.update(
                        rows[:-1],
                        spread_pips=spread,
                        observed_at=datetime.fromisoformat(rows[-1]["timestamp"]),
                    )
                fresh = [rows[-1]]
            else:
                fresh = [row for row in rows if row["timestamp"] > self.last_saved]
            with self.memory.transaction():
                for row in rows:
                    self.memory.record_project_data(
                        "closed_candle",
                        f"mt5:EURUSD:M5:{row['timestamp']}",
                        {
                            **row,
                            "source": "mt5_diagnostics_readonly",
                            "symbol": "EURUSD",
                            "timeframe": "M5",
                        },
                    )
            self.ready = True
        else:
            fresh = [
                row
                for row in rows
                if not self.last_saved or row["timestamp"] > self.last_saved
            ]
        for row in fresh:
            self.save_row(row, rows, spread, seconds)
        now = datetime.now(timezone.utc)
        age = (
            now
            - datetime.fromisoformat(rows[-1]["timestamp"])
            - timedelta(seconds=seconds)
        ).total_seconds()
        self.update_status(
            status="stale" if age > seconds * 1.5 else "observing",
            run_id=self.run_id,
            last_candle=rows[-1]["timestamp"],
            last_saved=self.last_saved,
            freshness_seconds=age,
            checked_at=now.isoformat(),
            message="Observação somente leitura; candles fechados.",
            error_type=None,
            source_status="ok",
        )

    def record_start(self, config):
        self.memory.record_artifact(
            artifact_id=self.run_id + ":started",
            dataset_reference="mt5_bridge_readonly",
            code_version=self.code_version,
            strategy_version=STRATEGY_METADATA.version,
            config_hash=self.config_hash,
            status="observer_started",
            payload={
                "run_id": self.run_id,
                "schema_version": 4,
                "data_source": "mt5_diagnostics_readonly",
                "config": config,
                "config_hash": self.config_hash,
                "regime_model_version": config["regime_config"]["regime_model_version"],
                "ALLOW_ORDER_EXECUTION": False,
            },
        )

    def save_row(self, row, rows, spread, seconds):
        stamp = datetime.fromisoformat(row["timestamp"])
        current = row is rows[-1]
        snapshot = self.session.update(
            [r for r in rows if r["timestamp"] <= row["timestamp"]],
            spread_pips=spread if current else row.get("spread_pips"),
            observed_at=datetime.now(timezone.utc)
            if current
            else stamp + timedelta(seconds=seconds),
        )
        eligibility = STRATEGY_METADATA.evaluate(snapshot)
        reason = (
            self.policy.context_gate(snapshot) or "OBSERVATION_ONLY_HYPOTHESIS_REQUIRED"
        )
        context = snapshot.learning_context()
        context.update(
            regime_match=eligibility["regime_match"],
            strategy_regime_compatibility=eligibility,
        )
        decision = Decision(
            self.run_id,
            "EURUSD",
            "M5",
            "mt5_diagnostics_readonly",
            stamp,
            DecisionAction.NO_TRADE,
            reason,
            AgentState.OBSERVING,
            strategy_id=STRATEGY_METADATA.strategy_id,
            strategy_version=STRATEGY_METADATA.version,
            config_hash=self.config_hash,
            created_at=datetime.fromisoformat(snapshot.timestamp_utc),
        )
        session = snapshot.session[0] if snapshot.session else "outside_session"
        with self.memory.transaction():
            self.memory.record_project_data(
                "diagnostic_chart_window",
                decision.decision_id,
                {
                    "candles": [r for r in rows if r["timestamp"] <= row["timestamp"]][
                        -200:
                    ],
                    "decision_id": decision.decision_id,
                    "cutoff": row["timestamp"],
                    "ingestion_mode": "current" if current else "catch_up",
                    "spread_basis": "current_quote" if current else "bar_history",
                },
            )
            self.memory.record_project_data(
                "closed_candle",
                f"mt5:EURUSD:M5:{row['timestamp']}",
                {
                    **row,
                    "source": "mt5_diagnostics_readonly",
                    "symbol": "EURUSD",
                    "timeframe": "M5",
                },
            )
            self.memory.record_snapshot(
                snapshot.as_dict(),
                session=session,
                regime=snapshot.regime,
                data_reference="mt5_bridge_readonly",
            )
            self.memory.record_intelligence(snapshot.as_dict())
            self.memory.record_decision(
                decision,
                session=session,
                regime=snapshot.regime,
                context={
                    "snapshot_id": snapshot.snapshot_id,
                    "intelligence_context": context,
                },
            )
            self.memory.record_experience(
                ExperienceRecord(
                    experience_id=str(uuid4()),
                    created_at_utc=snapshot.timestamp_utc,
                    symbol="EURUSD",
                    session=session,
                    market_regime=snapshot.regime,
                    snapshot_id=snapshot.snapshot_id,
                    decision_id=decision.decision_id,
                    strategy_id=decision.strategy_id,
                    strategy_version=decision.strategy_version,
                    config_version=self.config_hash,
                    direction=None,
                    action_taken="NO_TRADE",
                    action_not_taken="REAL_ORDER",
                    expected_behavior="observation_only",
                    observed_behavior=reason,
                    process_classification="valid_no_trade",
                    financial_result={"result_in_r": None},
                    process_result={
                        "reason_code": reason,
                        "execution_enabled": False,
                    },
                    source_data_reference="mt5_bridge_readonly",
                    **context,
                )
            )
            self.memory.record_project_data(
                "diagnostic_observer_checkpoint",
                row["timestamp"],
                {
                    "last_candle": row["timestamp"],
                    "run_id": self.run_id,
                    "snapshot_id": snapshot.snapshot_id,
                },
            )
        self.last_saved = row["timestamp"]
