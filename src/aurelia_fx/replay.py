"""Causal replay orchestration with an append-only journal and portable report."""

from __future__ import annotations

import gzip
import hashlib
import html
import json
import math
import platform
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import time, timedelta
from pathlib import Path
from uuid import uuid4

from .decision_engine import DecisionEngine, IntelligencePolicy
from .domain import AgentState as S
from .domain import DataQuality, Decision, DecisionAction, RiskLimits
from .execution_simulator import EntryRequest, ExecutionConfig, ExecutionSimulator
from .expectations import ExpectationStatus
from .experience_memory import ExperienceMemory, ExperienceRecord
from .hypothesis_lab import regime_performance_matrix, v3_cohort_report
from .observer import MarketObserver
from .regime import RegimeConfig
from .replay_data import ReplayDataset, unexpected_gap
from .replay_strategy import (
    STRATEGY_ID,
    STRATEGY_METADATA,
    STRATEGY_VERSION,
    candidate,
    compare,
    propose,
)
from .risk import assess_candidate
from .sessions import SessionEngine, SessionWindow
from .state_machine import AgentStateMachine
from .trend import ClosedBarAggregator, HierarchyConfig, timeframe_seconds


def encode(payload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True)
class ReplayConfig:
    regime_config: RegimeConfig = field(default_factory=RegimeConfig)
    symbol: str = "EURUSD"
    timeframe: str = "M5"
    warmup_bars: int = 30
    swing_window: int = 2
    lookback_bars: int = 300
    lifetime_bars: int = 12
    zone_tolerance_pips: float = 2.0
    reward_multiple: float = 2.5
    pip_size: float = 0.0001
    slippage_pips: float = 0.2
    # EURUSD, synthetic account denominated in USD: one EUR unit per price unit.
    value_per_price_unit: float = 1.0
    initial_equity: float = 10_000.0
    minimum_samples: int = 30
    commission_per_million_side: float = 35.0
    max_holding_bars: int = 24
    hierarchy: HierarchyConfig | None = None
    intelligence_policy: IntelligencePolicy = field(default_factory=IntelligencePolicy)
    level_ttl_bars: int = 300
    sessions: tuple[SessionWindow, ...] = field(
        default_factory=lambda: (
            SessionWindow("london", "Europe/London", time(8), time(17)),
            SessionWindow("new_york", "America/New_York", time(8), time(17)),
        )
    )
    limits: RiskLimits = field(
        default_factory=lambda: RiskLimits(0.5, 2.0, 5.0, 2.0, 2.0, 5)
    )

    def __post_init__(self):
        if self.symbol != "EURUSD":
            raise ValueError("Este replay suporta EURUSD.")
        timeframe_seconds(self.timeframe)
        for value in (
            self.warmup_bars,
            self.swing_window,
            self.lookback_bars,
            self.lifetime_bars,
            self.minimum_samples,
            self.max_holding_bars,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Contagens do replay precisam ser inteiros positivos.")
        if (
            self.warmup_bars < max(30, 2 * self.swing_window + 3)
            or self.lookback_bars < self.warmup_bars
        ):
            raise ValueError("Warmup/lookback insuficientes para swings confirmados.")
        for value in (
            self.zone_tolerance_pips,
            self.reward_multiple,
            self.pip_size,
            self.value_per_price_unit,
            self.initial_equity,
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(
                    "Parametros do replay precisam ser finitos e positivos."
                )
        if not math.isfinite(self.slippage_pips) or self.slippage_pips < 0:
            raise ValueError("Slippage precisa ser finito e nao negativo.")
        if (
            not math.isfinite(self.commission_per_million_side)
            or self.commission_per_million_side < 0
        ):
            raise ValueError("Commission must be finite and nonnegative.")
        if not self.sessions or len({s.name for s in self.sessions}) != len(
            self.sessions
        ):
            raise ValueError("Configure sessoes com nomes unicos.")
        if self.hierarchy is None:
            object.__setattr__(
                self, "hierarchy", HierarchyConfig.for_execution(self.timeframe)
            )
        if self.hierarchy.execution_timeframe != self.timeframe:
            raise ValueError(
                "Hierarchy execution timeframe must match the dataset timeframe."
            )
        if self.level_ttl_bars < 1:
            raise ValueError("Level TTL must be positive.")

    def as_dict(self):
        payload = asdict(self)
        for session in payload["sessions"]:
            session["opens"] = session["opens"].isoformat()
            session["closes"] = session["closes"].isoformat()
        return payload


def run_replay(
    dataset: ReplayDataset,
    *,
    config: ReplayConfig,
    memory: ExperienceMemory,
    output_dir: Path,
    code_version: str = "unknown",
) -> dict:
    """Each step sees a prefix only; execution is simulated without a broker API."""
    if not dataset.candles:
        raise ValueError("Dataset vazio.")
    seconds = timeframe_seconds(config.timeframe)
    delta = timedelta(seconds=seconds)
    stamps = [c.timestamp for c in dataset.candles]
    if any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError("Candles duplicados ou fora de ordem.")
    if any(stamp.timestamp() % seconds for stamp in stamps):
        raise ValueError(
            "Timestamp desalinhado com timeframe (timestamp deve indicar abertura UTC)."
        )
    run_id = str(uuid4())
    directory = output_dir / run_id
    directory.mkdir(parents=True, exist_ok=False)
    config_hash = hashlib.sha256(encode(config.as_dict()).encode()).hexdigest()
    manifest = {
        "schema_version": 4,
        "regime_model_version": config.regime_config.regime_model_version,
        "strategy_metadata": asdict(STRATEGY_METADATA),
        "run_id": run_id,
        "dataset_sha256": dataset.sha256,
        "ALLOW_ORDER_EXECUTION": False,
        "ALLOW_LIVE_TRADING": False,
        "data_source": dataset.source,
        "data_reference": dataset.reference,
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "python_version": platform.python_version(),
        "source_tree_sha256": hashlib.sha256(
            b"".join(
                file.relative_to(Path(__file__).parent).as_posix().encode()
                + b"\0"
                + file.read_bytes()
                for file in sorted(Path(__file__).parent.rglob("*.py"))
            )
        ).hexdigest(),
        "config": config.as_dict(),
        "config_hash": config_hash,
        "code_version": code_version,
        "clock": "candle_open_utc + timeframe; closed bars only",
        "retrieval_policy": "same run, strictly earlier replay timestamps; no automatic cross-run retrieval",
        "financial_model": "bid_next_open_v1; one position; synthetic USD account; next-open entry and revalidation",
        "quote_basis": "input OHLC assumed BID; ask reconstructed with one constant spread per bar",
        "execution_policy": "stop first when both touched; target limit; adverse market-fill slippage; forced end close",
        "from_utc": stamps[0].isoformat(),
        "to_utc": (stamps[-1] + delta).isoformat(),
    }
    archive = "\n".join(encode(candle.as_dict()) for candle in dataset.candles) + "\n"
    (directory / "candles.jsonl").write_text(archive, encoding="utf-8")
    manifest["normalized_candles_sha256"] = hashlib.sha256(archive.encode()).hexdigest()
    (directory / "manifest.json").write_text(encode(manifest), encoding="utf-8")

    def artifact(status, extra):
        memory.record_artifact(
            artifact_id=f"{run_id}:{status}",
            dataset_reference=dataset.reference,
            code_version=code_version,
            strategy_version=STRATEGY_VERSION,
            config_hash=config_hash,
            status=status,
            payload={**manifest, **extra},
        )

    artifact("started", {})
    observer = MarketObserver(
        SessionEngine(config.sessions),
        regime_config=config.regime_config,
        swing_window=config.swing_window,
        max_spread_pips=config.limits.max_spread_pips,
        hierarchy_config=config.hierarchy,
        level_tolerance=config.zone_tolerance_pips * config.pip_size,
        level_ttl_bars=config.level_ttl_bars,
        required_trend_roles=config.intelligence_policy.required_trend_roles,
    )
    aggregator = ClosedBarAggregator(config.hierarchy, lookback=config.lookback_bars)
    decision_engine = DecisionEngine(config.intelligence_policy, STRATEGY_METADATA)
    machine = AgentStateMachine()
    pending = None
    history = []
    decisions = []
    events_count = Counter()
    simulator = ExecutionSimulator(
        ExecutionConfig(
            pip_size=config.pip_size,
            slippage_pips=config.slippage_pips,
            commission_per_million_side=config.commission_per_million_side,
            max_holding_bars=config.max_holding_bars,
            value_per_price_unit=config.value_per_price_unit,
            initial_equity=config.initial_equity,
            bar_seconds=seconds,
        ),
        config.limits,
    )

    def record_execution(events):
        for event in events:
            memory.record_execution(run_id, event)
            if event["status"] not in {"closed", "censored", "rejected"}:
                continue
            memory.record_experience(
                ExperienceRecord(
                    event["event_id"] + ":experience",
                    event["observed_at"],
                    config.symbol,
                    event["session"],
                    event["market_regime"],
                    event["snapshot_id"],
                    event["decision_id"],
                    STRATEGY_ID,
                    STRATEGY_VERSION,
                    config_hash,
                    event["side"],
                    "SIMULATED_" + event["status"].upper(),
                    "REAL_ORDER",
                    "next-open entry; frozen stop/target; bounded holding period",
                    event["reason"],
                    event.get("process_classification", "prevented_rule_violation"),
                    event.get(
                        "financial_result", {"result_in_r": None, "net_pnl": None}
                    ),
                    {
                        "hypothesis_id": event["hypothesis_id"],
                        "execution_event_id": event["event_id"],
                        "rule_compliance": event.get("rule_compliance"),
                        "simulation": True,
                        "reason": event["reason"],
                        "source_signal_decision_id": event["decision_id"],
                    },
                    source_data_reference=dataset.reference,
                    **event.get("intelligence_context", {}),
                )
            )

    previous = None
    try:
        with (
            (directory / "decisions.jsonl").open("w", encoding="utf-8") as journal,
            gzip.open(
                directory / "intelligence.jsonl.gz", "wt", encoding="utf-8"
            ) as intelligence_journal,
        ):
            for index, candle in enumerate(dataset.candles):
                with memory.transaction():
                    if hasattr(memory, "record_project_data"):
                        memory.record_project_data(
                            "closed_candle",
                            f"{dataset.sha256}:{candle.timestamp.isoformat()}",
                            {
                                **asdict(candle),
                                "timestamp": candle.timestamp.isoformat(),
                                "source": dataset.source,
                                "dataset_sha256": dataset.sha256,
                                "symbol": config.symbol,
                                "timeframe": config.timeframe,
                            },
                        )
                    now = candle.timestamp + delta

                    def move(state, reason):
                        machine.move(state, reason, at=now)

                    if machine.state == S.BOOTING:
                        move(S.SYNCING_DATA, "offline dataset loaded")
                        move(S.OBSERVING, "first closed bar")
                    elif machine.state == S.DATA_ERROR:
                        move(S.SYNCING_DATA, "restart context after data error")
                        move(S.OBSERVING, "next closed bar")
                    elif machine.state != S.OBSERVING:
                        move(S.OBSERVING, "next closed bar")
                    gap = previous is not None and unexpected_gap(
                        previous, candle, seconds
                    )
                    if gap:
                        history.clear()
                        aggregator.reset()
                        observer.reset()
                    history.append(candle)
                    history = history[-config.lookback_bars :]
                    quality = DataQuality(
                        not gap,
                        ("UNEXPECTED_MARKET_GAP",) if gap else (),
                        (),
                        candle.timestamp,
                    )
                    histories = aggregator.add(candle)
                    record_execution(
                        simulator.advance(
                            candle,
                            data_valid=quality.valid,
                            active_sessions=observer.sessions.identify(
                                candle.timestamp
                            ).active_sessions,
                            force_close_reason="END_OF_DATA"
                            if index == len(dataset.candles) - 1
                            else None,
                        )
                    )
                    snapshot = observer.observe(
                        symbol=config.symbol,
                        timeframe=config.timeframe,
                        candles=history,
                        quality=quality,
                        spread_pips=candle.spread_pips,
                        observed_at=now,
                        snapshot_id=f"{run_id}:snapshot:{index}",
                        validity_seconds=seconds,
                        histories_by_timeframe=histories,
                        data_reference=f"{dataset.reference}#bar={index}",
                    )
                    # Authorization uses decision time: a bar closing at session end cannot enter.
                    session_names = snapshot.session
                    session = session_names[0] if session_names else "outside_session"
                    regime = snapshot.market_regime
                    eligibility = STRATEGY_METADATA.evaluate(snapshot)
                    side = {"bullish": "long", "bearish": "short"}.get(
                        snapshot.dominant_direction
                    )
                    similar = memory.retrieve_similar(
                        symbol=config.symbol,
                        session=session,
                        market_regime=regime,
                        strategy_id=STRATEGY_ID,
                        strategy_version=STRATEGY_VERSION,
                        direction=side,
                        minimum_sample_count=config.minimum_samples,
                        run_id=run_id,
                        before=now,
                        trade_direction_class=snapshot.trend_alignment[
                            "trade_direction_class"
                        ],
                        evidence_state=snapshot.evidence_status,
                        regime_model_version=snapshot.regime_model_version,
                        regime_config_hash=snapshot.regime_config_hash,
                    )
                    reason = "WAITING_FOR_CONTEXT"
                    action = DecisionAction.NO_TRADE
                    risk = None
                    plan = None
                    evaluation = None
                    hypothesis_id = (
                        pending.hypothesis.hypothesis_id if pending else None
                    )
                    cancellation = None
                    terminal_confirmed = False
                    if not quality.valid:
                        reason, cancellation = "INVALID_MARKET_DATA", "invalidated"
                        move(S.DATA_ERROR, reason)
                    elif simulator.account_locked:
                        reason, cancellation = (
                            "EXECUTION_ACCOUNT_UNRESOLVED",
                            "invalidated",
                        )
                        move(S.DATA_ERROR, reason)
                    elif session == "outside_session" or (
                        pending and pending.contract.session != session
                    ):
                        reason, cancellation = "SESSION_NOT_AUTHORIZED", "invalidated"
                        move(S.SESSION_HALTED, reason)
                    elif snapshot.invalidating_evidence:
                        reason, cancellation = "EVIDENCE_INVALIDATED", "invalidated"
                        move(S.DATA_ERROR, reason)
                    elif eligibility["reason"]:
                        reason, cancellation = eligibility["reason"], "invalidated"
                        move(
                            S.BUILDING_CONTEXT,
                            "regime classified before strategy search",
                        )
                        move(S.OBSERVING, reason)
                    else:
                        move(S.BUILDING_CONTEXT, "closed-bar structure")
                        move(S.RETRIEVING_EXPERIENCE, "causal same-run retrieval")
                        if simulator.busy:
                            reason = "SIMULATED_EXPOSURE_ACTIVE"
                            move(S.OBSERVING, reason)
                        elif len(history) < config.warmup_bars:
                            reason = "WARMUP"
                            move(S.OBSERVING, reason)
                        elif pending is None and decision_engine.context_gate(snapshot):
                            reason = decision_engine.context_gate(snapshot)
                            move(S.OBSERVING, reason)
                        elif pending is None:
                            move(
                                S.FORMING_HYPOTHESIS,
                                "experimental frozen breakout/retest rules",
                            )
                            pending = propose(
                                history,
                                now=now,
                                hypothesis_id=f"{run_id}:hypothesis:{index}",
                                expectation_id=f"{run_id}:expectation:{index}",
                                session=session,
                                symbol=config.symbol,
                                swing_window=config.swing_window,
                                tolerance=config.zone_tolerance_pips * config.pip_size,
                                lifetime_seconds=config.lifetime_bars * seconds,
                                source_experiences=similar.experience_ids,
                            )
                            if pending:
                                direction_block = decision_engine.context_gate(
                                    snapshot, side=pending.contract.direction
                                )
                                if direction_block:
                                    pending = None
                                    reason = direction_block
                            if pending:
                                hypothesis_id = pending.hypothesis.hypothesis_id
                                payload = {
                                    **asdict(pending.hypothesis),
                                    "created_at": now.isoformat(),
                                    "run_id": run_id,
                                    "level": pending.level,
                                    "stop": pending.stop,
                                    "retrieval_sample_count": similar.sample_count,
                                }
                                memory.record_event(
                                    "hypothesis_events",
                                    f"{run_id}:proposal:{index}",
                                    hypothesis_id,
                                    "proposed",
                                    payload,
                                    observed_at=now,
                                )
                                contract_payload = asdict(pending.contract)
                                contract_payload.update(
                                    created_at=now.isoformat(),
                                    expires_at=pending.contract.expires_at.isoformat(),
                                    run_id=run_id,
                                )
                                memory.record_event(
                                    "expectation_events",
                                    f"{run_id}:contract:{index}",
                                    pending.contract.expectation_id,
                                    "proposed",
                                    contract_payload,
                                    observed_at=now,
                                )
                                events_count["proposed"] += 1
                                move(S.BUILDING_EXPECTATION, "freeze contract")
                                move(S.WAITING_FOR_ZONE, "wait for a future retest bar")
                                reason = "HYPOTHESIS_PROPOSED"
                            else:
                                move(S.OBSERVING, "no causal breakout")
                        else:
                            # Restore the documented causal sequence for this observation cycle.
                            move(S.FORMING_HYPOTHESIS, "existing immutable hypothesis")
                            move(S.BUILDING_EXPECTATION, "existing immutable contract")
                            move(S.WAITING_FOR_ZONE, "compare only later closed bars")
                            move(
                                S.WAITING_FOR_TRIGGER,
                                "evaluate zone and trigger evidence",
                            )
                            move(
                                S.COMPARING_EXPECTED_OBSERVED,
                                "compare immutable expectation with closed bar",
                            )
                            pending, evaluation = compare(
                                pending,
                                candle,
                                now=now,
                                evaluation_id=f"{run_id}:evaluation:{index}",
                                data_valid=quality.valid,
                                evidence_set=snapshot.evidence_set,
                                observed_context={
                                    "trend_direction": snapshot.trend_alignment[
                                        "dominant_direction"
                                    ],
                                    "structure": snapshot.market_structure["direction"],
                                    "price_action": snapshot.price_action[
                                        "directional_pressure"
                                    ],
                                    "level_reaction": snapshot.price_action[
                                        "retest_status"
                                    ],
                                    "momentum": snapshot.price_action[
                                        "momentum_behavior"
                                    ],
                                    "follow_through": snapshot.follow_through_status,
                                },
                            )
                            status = evaluation.status
                            event_payload = {
                                **asdict(evaluation),
                                "status": status.value,
                                "observed_at": now.isoformat(),
                                "run_id": run_id,
                            }
                            memory.record_event(
                                "expectation_events",
                                evaluation.evaluation_id,
                                pending.contract.expectation_id,
                                status.value,
                                event_payload,
                                observed_at=now,
                            )
                            events_count[status.value] += 1
                            reason = f"EXPECTATION_{status.value.upper()}"
                            if status == ExpectationStatus.CONFIRMED:
                                move(S.HYPOTHESIS_CONFIRMED, reason)
                                plan = candidate(
                                    pending,
                                    candle,
                                    reward_multiple=config.reward_multiple,
                                )
                                blocker = decision_engine.trigger_gate(
                                    evaluation
                                ) or decision_engine.context_gate(
                                    snapshot, side=plan.side, target=plan.target
                                )
                                if blocker:
                                    reason = blocker
                                    terminal_confirmed = (
                                        blocker != "WAITING_FOR_TRIGGER"
                                    )
                                    move(S.OBSERVING, reason)
                                else:
                                    terminal_confirmed = True
                                    move(
                                        S.VALIDATING_RISK,
                                        "independent gate after confirmation and trigger",
                                    )
                                    risk = assess_candidate(
                                        plan,
                                        quality=quality,
                                        session=session,
                                        allowed_sessions=frozenset(
                                            s.name for s in config.sessions
                                        ),
                                        spread_pips=candle.spread_pips,
                                        pip_size=config.pip_size,
                                        max_slippage_price=2
                                        * config.slippage_pips
                                        * config.pip_size,
                                        value_per_price_unit=config.value_per_price_unit,
                                        commission_per_unit=2
                                        * config.commission_per_million_side
                                        / 1_000_000,
                                        account=simulator.account(now),
                                        limits=config.limits,
                                        now=now,
                                    )
                                    if risk.approved:
                                        action, reason = (
                                            DecisionAction.HYPOTHETICAL_SIGNAL,
                                            "CONFIRMED_RISK_APPROVED",
                                        )
                                        move(
                                            S.READY_TO_EXECUTE,
                                            "hypothetical signal only",
                                        )
                                    else:
                                        reason = "RISK_VETO"
                                        move(S.RISK_LOCK, ",".join(risk.reasons))
                            elif status in {
                                ExpectationStatus.INVALIDATED,
                                ExpectationStatus.EXPIRED,
                            }:
                                move(S.HYPOTHESIS_INVALIDATED, reason)
                            else:
                                move(S.OBSERVING, reason)
                    if cancellation and pending:
                        payload = {
                            "hypothesis_id": pending.hypothesis.hypothesis_id,
                            "run_id": run_id,
                            "reason": reason,
                            "observed_at": now.isoformat(),
                        }
                        memory.record_event(
                            "expectation_events",
                            f"{run_id}:cancel:{index}",
                            pending.contract.expectation_id,
                            cancellation,
                            payload,
                            observed_at=now,
                        )
                        events_count[cancellation] += 1
                    if pending and (
                        cancellation
                        or terminal_confirmed
                        or (
                            evaluation
                            and evaluation.status
                            in {
                                ExpectationStatus.INVALIDATED,
                                ExpectationStatus.EXPIRED,
                            }
                        )
                    ):
                        memory.record_event(
                            "hypothesis_events",
                            f"{run_id}:terminal:{index}",
                            pending.hypothesis.hypothesis_id,
                            cancellation or evaluation.status.value,
                            {
                                "hypothesis_id": pending.hypothesis.hypothesis_id,
                                "run_id": run_id,
                                "reason": reason,
                                "decision_action": action.value,
                            },
                            observed_at=now,
                        )
                        pending = None
                    decision = Decision(
                        run_id,
                        config.symbol,
                        config.timeframe,
                        dataset.source,
                        candle.timestamp,
                        action,
                        reason,
                        machine.state,
                        evidence=snapshot.favorable_evidence,
                        contradictions=snapshot.conflicting_evidence,
                        missing_data=snapshot.missing_evidence,
                        candidate=plan,
                        risk=risk,
                        strategy_id=STRATEGY_ID,
                        strategy_version=STRATEGY_VERSION,
                        config_hash=config_hash,
                        decision_id=f"{run_id}:decision:{index}",
                        created_at=now,
                    )
                    payload = decision.as_dict()
                    intelligence_context = snapshot.learning_context(evaluation)
                    intelligence_context.update(
                        regime_match=eligibility["regime_match"],
                        strategy_regime_compatibility=eligibility,
                    )
                    payload.update(
                        snapshot_id=snapshot.snapshot_id,
                        hypothesis_id=hypothesis_id,
                        retrieval={
                            "sample_count": similar.sample_count,
                            "sufficient_sample": similar.sufficient_sample,
                            "scope": "same_run_before_current_bar_and_v3_context",
                            "financial_mean_r": similar.result_in_r_mean,
                        },
                        intelligence_context=intelligence_context,
                    )
                    classification = (
                        "technical_failure"
                        if not quality.valid or simulator.account_locked
                        else (
                            "insufficient_evidence"
                            if action == DecisionAction.HYPOTHETICAL_SIGNAL
                            else "prevented_rule_violation"
                            if reason == "RISK_VETO"
                            else "valid_no_trade"
                        )
                    )
                    experience = ExperienceRecord(
                        f"{run_id}:experience:{index}",
                        now.isoformat(),
                        config.symbol,
                        session,
                        regime,
                        snapshot.snapshot_id,
                        decision.decision_id,
                        STRATEGY_ID,
                        STRATEGY_VERSION,
                        config_hash,
                        side,
                        action.value,
                        "REAL_ORDER",
                        " -> ".join(evaluation.favorable + evaluation.missing)
                        if evaluation
                        else reason,
                        encode(
                            {
                                "close": candle.close,
                                "expectation_status": evaluation.status.value
                                if evaluation
                                else None,
                            }
                        ),
                        classification,
                        {
                            "result_in_r": None,
                            "net_pnl": None,
                            "execution_simulated": False,
                        },
                        {
                            "data_valid": quality.valid,
                            "reason_code": reason,
                            "hypothesis_id": hypothesis_id,
                            "risk_approved": risk.approved if risk else None,
                            "retrieval": payload["retrieval"],
                            "outcome_review": "outcomes appended later; observation records never overwritten",
                        },
                        source_data_reference=f"{dataset.reference}#bar={index}",
                        **intelligence_context,
                    )
                    memory.record_snapshot(
                        snapshot.as_dict(),
                        session=session,
                        regime=regime,
                        data_reference=experience.source_data_reference,
                    )
                    memory.record_intelligence(snapshot.as_dict())
                    memory.record_decision(
                        decision,
                        session=session,
                        regime=regime,
                        context={
                            key: payload[key]
                            for key in (
                                "snapshot_id",
                                "hypothesis_id",
                                "retrieval",
                                "intelligence_context",
                            )
                        },
                    )
                    memory.record_experience(experience)
                    if action == DecisionAction.HYPOTHETICAL_SIGNAL:
                        simulator.submit(
                            EntryRequest(
                                decision.decision_id,
                                snapshot.snapshot_id,
                                hypothesis_id,
                                plan,
                                now,
                                session,
                                regime,
                                intelligence_context,
                            )
                        )
                journal.write(encode(payload) + "\n")
                intelligence_journal.write(encode(snapshot.as_dict()) + "\n")
                decisions.append(payload)
                previous = candle
        with memory.transaction():
            record_execution(simulator.finish(stamps[-1] + delta))
        if pending:
            payload = {
                "run_id": run_id,
                "hypothesis_id": pending.hypothesis.hypothesis_id,
                "reason": "END_OF_DATA",
                "unresolved": True,
            }
            memory.record_event(
                "expectation_events",
                f"{run_id}:end",
                pending.contract.expectation_id,
                "insufficient_data",
                payload,
                observed_at=stamps[-1] + delta,
            )
            memory.record_event(
                "hypothesis_events",
                f"{run_id}:end-hypothesis",
                pending.hypothesis.hypothesis_id,
                "insufficient_data",
                payload,
                observed_at=stamps[-1] + delta,
            )
            events_count["end_of_data_unresolved"] += 1
        # Namespace IDs differ between runs. Historical clocks and decision contents do not.
        semantic = encode(decisions).replace(run_id, "<run>")
        report = {
            **manifest,
            "status": "completed",
            "bars": len(decisions),
            "actions": dict(Counter(d["action"] for d in decisions)),
            "reasons": dict(Counter(d["reason_code"] for d in decisions)),
            "expectation_events": dict(events_count),
            "intelligence": {
                "regimes": dict(
                    Counter(d["intelligence_context"]["regime"] for d in decisions)
                ),
                "regime_compatibility": dict(
                    Counter(
                        str(d["intelligence_context"]["regime_match"])
                        for d in decisions
                    )
                ),
                "evidence_states": dict(
                    Counter(
                        d["intelligence_context"]["evidence_state"] for d in decisions
                    )
                ),
                "trend_states": dict(
                    Counter(
                        d["intelligence_context"]["trend_state_at_decision"]
                        for d in decisions
                    )
                ),
                "direction_classes": dict(
                    Counter(
                        d["intelligence_context"]["trade_direction_class"]
                        for d in decisions
                    )
                ),
                "confirmation_states": dict(
                    Counter(
                        d["intelligence_context"]["confirmation_state"]
                        for d in decisions
                    )
                ),
                "trigger_states": dict(
                    Counter(
                        d["intelligence_context"]["trigger_state"] for d in decisions
                    )
                ),
            },
            "decision_digest": hashlib.sha256(semantic.encode()).hexdigest(),
            "execution": simulator.summary(),
            "execution_digest": hashlib.sha256(
                encode(simulator.events).replace(run_id, "<run>").encode()
            ).hexdigest(),
            "report_directory": str(directory.resolve()),
            "limitations": [
                "Experimental baseline; no statistical edge established.",
                "Simulated bid/ask OHLC execution; constant bar spread; no ticks, real fills or financing/swaps.",
                "MAE/MFE are conservative lower bounds; intrabar ordering is unknown.",
                "Experience counts are observations, not independent trades or calibrated probabilities.",
                "UTC complete-bucket multi-timeframe aggregation; no broker holiday calendar.",
                "Categorical evidence with feature-lineage deduplication; no calibrated probabilities.",
                "Prior runs excluded from automatic retrieval to prevent duplication and future leakage.",
            ],
        }
        report["execution"]["minimum_sample_floor_met"] = (
            report["execution"]["closed_trades"] >= config.minimum_samples
        )
        machine.move(S.SHUTDOWN, "dataset exhausted", at=stamps[-1] + delta)
        transitions = [
            {
                "before": t.before.value,
                "after": t.after.value,
                "at": t.at.isoformat(),
                "reason": t.reason,
            }
            for t in machine.transitions
        ]
        (directory / "transitions.json").write_text(
            encode(transitions), encoding="utf-8"
        )
        (directory / "execution.jsonl").write_text(
            "".join(encode(e) + "\n" for e in simulator.events), encoding="utf-8"
        )
        (directory / "equity.json").write_text(
            encode(simulator.equity_curve), encoding="utf-8"
        )
        (directory / "regime_performance.json").write_text(
            encode(
                regime_performance_matrix(
                    memory.research_experiences(run_id),
                    minimum_samples=config.minimum_samples,
                )
            ),
            encoding="utf-8",
        )
        (directory / "research_cohorts.json").write_text(
            encode(
                v3_cohort_report(
                    memory.research_experiences(run_id),
                    minimum_samples=config.minimum_samples,
                )
            ),
            encoding="utf-8",
        )
        (directory / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_html(
            directory / "report.html",
            report,
            decisions,
            simulator.events,
            simulator.equity_curve,
        )
        artifact(
            "completed",
            {"decision_digest": report["decision_digest"], "bars": len(decisions)},
        )
        return report
    except Exception as exc:
        artifact(
            "failed",
            {"error_type": type(exc).__name__, "steps_completed": len(decisions)},
        )
        raise


def write_html(
    path: Path,
    report: dict,
    decisions: list[dict],
    execution_events=(),
    equity_curve=(),
) -> None:
    rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(value))}</td>"
            for value in (
                d["data_timestamp_utc"],
                d["action"],
                d["reason_code"],
                d["intelligence_context"]["regime"],
                d["intelligence_context"]["regime_subtype"],
                d["intelligence_context"]["market_location"].get(
                    "relative_location", "UNDEFINED"
                ),
                d["intelligence_context"]["trend_state_at_decision"],
                d["intelligence_context"]["evidence_state"],
                d["intelligence_context"]["confirmation_state"],
                d["intelligence_context"]["trigger_state"],
                ", ".join(d["risk"]["reasons"]) if d["risk"] else "",
                d["retrieval"]["sample_count"],
            )
        )
        + "</tr>"
        for d in decisions
    )
    trade_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(value))}</td>"
            for value in (
                e.get("entry_at", "—"),
                e["observed_at"],
                e["side"],
                e["status"],
                e.get("reason", ""),
                e.get("financial_result", {}).get("net_pnl"),
                e.get("financial_result", {}).get("result_in_r"),
                e.get("financial_result", {}).get("mae_r"),
                e.get("financial_result", {}).get("mfe_r"),
                sum(
                    e.get("financial_result", {}).get(key, 0) or 0
                    for key in ("spread_cost", "slippage_cost", "commission")
                ),
                e.get("process_classification", "prevented_rule_violation"),
            )
        )
        + "</tr>"
        for e in execution_events
        if e["status"] in {"closed", "censored", "rejected"}
    )
    values = [point["equity"] for point in equity_curve if point["equity"] is not None]
    chart = ""
    if len(values) > 1:
        low, high = min(values), max(values)
        points = " ".join(
            f"{10 + i * 780 / (len(values) - 1):.2f},{110 - (v - low) * 100 / (high - low or 1):.2f}"
            for i, v in enumerate(values)
        )
        chart = (
            '<h2>Equity simulada no fechamento</h2><svg viewBox="0 0 800 130" role="img" '
            'aria-label="Curva da equity simulada"><polyline fill="none" stroke="#43d69a" stroke-width="2" points="'
            + points
            + f'"/></svg><p>Faixa USD {low:.2f} a {high:.2f}. Valores desconhecidos após lacunas são excluídos.</p>'
        )
    metrics = report.get("execution", {})
    path.write_text(
        """<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Aurelia FX - Replay EUR/USD</title><style>body{font:15px system-ui;background:#10181e;color:#e7edf0;margin:32px}
table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #30434d;text-align:left}
pre{white-space:pre-wrap;background:#17252e;padding:16px}h1{color:#43d69a}</style>
<h1>Replay EUR/USD</h1><p>Pesquisa experimental com candles fechados. Sinais hipotéticos, sem envio de ordens.</p>
<p>O horário da tabela indica a abertura do candle; a decisão ocorre no fechamento.</p>"""
        + f"<p><strong>{report['bars']} candles | {report['actions'].get('NO_TRADE', 0)} NO_TRADE | {report['actions'].get('HYPOTHETICAL_SIGNAL', 0)} sinais hipotéticos</strong></p>"
        + f"<p>Trades encerrados: {metrics.get('closed_trades', 0)} | P&amp;L líquido simulado USD: {metrics.get('net_pnl')} | Amostra mínima atingida: {metrics.get('minimum_sample_floor_met')}</p>"
        + chart
        + "<h2>Execuções simuladas e qualidade do processo</h2><p>Resultados históricos simulados; custos são hipóteses declaradas. MAE/MFE são limites conservadores, não medições por tick.</p>"
        + "<table><tr><th>Entrada UTC</th><th>Resultado conhecido UTC</th><th>Lado</th><th>Status</th><th>Saída/veto</th><th>Líquido USD</th><th>Resultado R</th><th>MAE R (mín.)</th><th>MFE R (mín.)</th><th>Custos USD</th><th>Processo</th></tr>"
        + trade_rows
        + "</table>"
        + "<details><summary>Configuração, contagens e auditoria da execução</summary><pre>"
        + html.escape(json.dumps(report, ensure_ascii=False, indent=2))
        + '</pre></details><p><a href="intelligence.jsonl.gz">Dados de auditoria da leitura V4</a></p><table><thead><tr><th>Candle UTC</th><th>Ação</th><th>Motivo</th><th>Regime</th><th>Subtipo</th><th>Localização</th><th>Tendência</th><th>Evidências</th><th>Confirmação</th><th>Gatilho</th><th>Veto de risco</th><th>Observações semelhantes anteriores</th></tr></thead><tbody>'
        + rows
        + "</tbody></table></html>",
        encoding="utf-8",
    )
