"""Causal replay orchestration with an append-only journal and portable report."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import time, timedelta
import hashlib
import html
import json
import math
import platform
from pathlib import Path
from uuid import uuid4

from .domain import AccountSnapshot, AgentState as S, DataQuality, Decision, DecisionAction, RiskLimits
from .expectations import ExpectationStatus
from .experience_memory import ExperienceMemory, ExperienceRecord
from .observer import MarketObserver
from .replay_data import ReplayDataset, TIMEFRAMES, unexpected_gap
from .replay_strategy import STRATEGY_ID, STRATEGY_VERSION, candidate, compare, propose
from .risk import assess_candidate
from .sessions import SessionEngine, SessionWindow
from .state_machine import AgentStateMachine


def encode(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class ReplayConfig:
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
    sessions: tuple[SessionWindow, ...] = field(default_factory=lambda: (
        SessionWindow("london", "Europe/London", time(8), time(17)),
        SessionWindow("new_york", "America/New_York", time(8), time(17)),
    ))
    limits: RiskLimits = field(default_factory=lambda: RiskLimits(0.5, 2.0, 5.0, 2.0, 2.0, 5))

    def __post_init__(self):
        if self.symbol != "EURUSD" or self.timeframe not in TIMEFRAMES:
            raise ValueError("Este replay suporta EURUSD e timeframes fixos documentados.")
        for value in (self.warmup_bars, self.swing_window, self.lookback_bars, self.lifetime_bars, self.minimum_samples):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("Contagens do replay precisam ser inteiros positivos.")
        if self.warmup_bars < max(30, 2 * self.swing_window + 3) or self.lookback_bars < self.warmup_bars:
            raise ValueError("Warmup/lookback insuficientes para swings confirmados.")
        for value in (self.zone_tolerance_pips, self.reward_multiple, self.pip_size,
                      self.value_per_price_unit, self.initial_equity):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Parametros do replay precisam ser finitos e positivos.")
        if not math.isfinite(self.slippage_pips) or self.slippage_pips < 0:
            raise ValueError("Slippage precisa ser finito e nao negativo.")
        if not self.sessions or len({s.name for s in self.sessions}) != len(self.sessions):
            raise ValueError("Configure sessoes com nomes unicos.")

    def as_dict(self):
        payload = asdict(self)
        for session in payload["sessions"]:
            session["opens"] = session["opens"].isoformat()
            session["closes"] = session["closes"].isoformat()
        return payload


def run_replay(dataset: ReplayDataset, *, config: ReplayConfig, memory: ExperienceMemory,
               output_dir: Path, code_version: str = "unknown") -> dict:
    """Each step sees a prefix only. No fills, P&L, broker writes or rule updates."""
    if not dataset.candles:
        raise ValueError("Dataset vazio.")
    seconds = TIMEFRAMES[config.timeframe]
    delta = timedelta(seconds=seconds)
    stamps = [c.timestamp for c in dataset.candles]
    if any(b <= a for a, b in zip(stamps, stamps[1:])):
        raise ValueError("Candles duplicados ou fora de ordem.")
    if any(stamp.timestamp() % seconds for stamp in stamps):
        raise ValueError("Timestamp desalinhado com timeframe (timestamp deve indicar abertura UTC).")
    run_id = str(uuid4())
    directory = output_dir / run_id
    directory.mkdir(parents=True, exist_ok=False)
    config_hash = hashlib.sha256(encode(config.as_dict()).encode()).hexdigest()
    manifest = {
        "schema_version": 1, "run_id": run_id, "dataset_sha256": dataset.sha256,
        "data_source": dataset.source, "data_reference": dataset.reference,
        "strategy_id": STRATEGY_ID, "strategy_version": STRATEGY_VERSION,
        "python_version": platform.python_version(),
        "source_tree_sha256": hashlib.sha256(b"".join(
            file.name.encode() + b"\0" + file.read_bytes()
            for file in sorted(Path(__file__).parent.glob("*.py")))).hexdigest(),
        "config": config.as_dict(), "config_hash": config_hash, "code_version": code_version,
        "clock": "candle_open_utc + timeframe; closed bars only",
        "retrieval_policy": "same run, strictly earlier replay timestamps; no automatic cross-run retrieval",
        "financial_model": "fixed synthetic USD equity; signals only, no fills or financial returns",
        "from_utc": stamps[0].isoformat(), "to_utc": (stamps[-1] + delta).isoformat(),
    }
    archive = "\n".join(encode(candle.as_dict()) for candle in dataset.candles) + "\n"
    (directory / "candles.jsonl").write_text(archive, encoding="utf-8")
    manifest["normalized_candles_sha256"] = hashlib.sha256(archive.encode()).hexdigest()
    (directory / "manifest.json").write_text(encode(manifest), encoding="utf-8")
    def artifact(status, extra):
        memory.record_artifact(artifact_id=f"{run_id}:{status}", dataset_reference=dataset.reference,
                               code_version=code_version, strategy_version=STRATEGY_VERSION,
                               config_hash=config_hash, status=status, payload={**manifest, **extra})
    artifact("started", {})
    observer = MarketObserver(SessionEngine(config.sessions), swing_window=config.swing_window,
                              max_spread_pips=config.limits.max_spread_pips)
    machine = AgentStateMachine()
    pending = None
    history = []
    decisions = []
    events_count = Counter()
    signals_by_day = Counter()
    previous = None
    try:
        with (directory / "decisions.jsonl").open("w", encoding="utf-8") as journal:
            for index, candle in enumerate(dataset.candles):
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
                gap = previous is not None and unexpected_gap(previous, candle, seconds)
                if gap:
                    history.clear()
                history.append(candle)
                history = history[-config.lookback_bars:]
                quality = DataQuality(not gap, ("UNEXPECTED_MARKET_GAP",) if gap else (), (), candle.timestamp)
                snapshot = observer.observe(symbol=config.symbol, timeframe=config.timeframe, candles=history,
                                            quality=quality, spread_pips=candle.spread_pips, observed_at=now,
                                            snapshot_id=f"{run_id}:snapshot:{index}", validity_seconds=seconds)
                # Authorization uses decision time: a bar closing at session end cannot enter.
                session_names = snapshot.session
                session = session_names[0] if session_names else "outside_session"
                regime = snapshot.market_regime
                side = {"bullish": "long", "bearish": "short"}.get(snapshot.dominant_direction)
                similar = memory.retrieve_similar(symbol=config.symbol, session=session, market_regime=regime,
                    strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION, direction=side,
                    minimum_sample_count=config.minimum_samples, run_id=run_id, before=now)
                reason = "WAITING_FOR_CONTEXT"
                action = DecisionAction.NO_TRADE
                risk = None
                plan = None
                evaluation = None
                hypothesis_id = pending.hypothesis.hypothesis_id if pending else None
                cancellation = None
                if not quality.valid:
                    reason, cancellation = "INVALID_MARKET_DATA", "invalidated"
                    move(S.DATA_ERROR, reason)
                elif session == "outside_session" or (pending and pending.contract.session != session):
                    reason, cancellation = "SESSION_NOT_AUTHORIZED", "invalidated"
                    move(S.SESSION_HALTED, reason)
                else:
                    move(S.BUILDING_CONTEXT, "closed-bar structure")
                    move(S.RETRIEVING_EXPERIENCE, "causal same-run retrieval")
                    if len(history) < config.warmup_bars:
                        reason = "WARMUP"
                        move(S.OBSERVING, reason)
                    elif pending is None:
                        move(S.FORMING_HYPOTHESIS, "experimental frozen breakout/retest rules")
                        pending = propose(history, now=now, hypothesis_id=f"{run_id}:hypothesis:{index}",
                            expectation_id=f"{run_id}:expectation:{index}", session=session, symbol=config.symbol,
                            swing_window=config.swing_window, tolerance=config.zone_tolerance_pips * config.pip_size,
                            lifetime_seconds=config.lifetime_bars * seconds, source_experiences=similar.experience_ids)
                        if pending:
                            hypothesis_id = pending.hypothesis.hypothesis_id
                            payload = {**asdict(pending.hypothesis), "created_at": now.isoformat(), "run_id": run_id,
                                       "level": pending.level, "stop": pending.stop,
                                       "retrieval_sample_count": similar.sample_count}
                            memory.record_event("hypothesis_events", f"{run_id}:proposal:{index}", hypothesis_id,
                                                "proposed", payload, observed_at=now)
                            contract_payload = asdict(pending.contract)
                            contract_payload.update(created_at=now.isoformat(), expires_at=pending.contract.expires_at.isoformat(), run_id=run_id)
                            memory.record_event("expectation_events", f"{run_id}:contract:{index}", pending.contract.expectation_id,
                                                "proposed", contract_payload, observed_at=now)
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
                        move(S.WAITING_FOR_TRIGGER, "evaluate zone and trigger evidence")
                        move(S.COMPARING_EXPECTED_OBSERVED, "compare immutable expectation with closed bar")
                        pending, evaluation = compare(pending, candle, now=now,
                            evaluation_id=f"{run_id}:evaluation:{index}", data_valid=quality.valid)
                        status = evaluation.status
                        event_payload = {**asdict(evaluation), "status": status.value,
                                         "observed_at": now.isoformat(), "run_id": run_id}
                        memory.record_event("expectation_events", evaluation.evaluation_id, pending.contract.expectation_id,
                                            status.value, event_payload, observed_at=now)
                        events_count[status.value] += 1
                        reason = f"EXPECTATION_{status.value.upper()}"
                        if status == ExpectationStatus.CONFIRMED:
                            move(S.HYPOTHESIS_CONFIRMED, reason)
                            move(S.VALIDATING_RISK, "independent gate, includes costs")
                            plan = candidate(pending, candle, reward_multiple=config.reward_multiple)
                            day = now.date().isoformat()
                            risk = assess_candidate(plan, quality=quality, session=session,
                                allowed_sessions=frozenset(s.name for s in config.sessions), spread_pips=candle.spread_pips,
                                pip_size=config.pip_size, max_slippage_price=config.slippage_pips * config.pip_size,
                                value_per_price_unit=config.value_per_price_unit,
                                account=AccountSnapshot(config.initial_equity, config.initial_equity, config.initial_equity,
                                                        signals_by_day[day]), limits=config.limits, now=now)
                            if risk.approved:
                                action, reason = DecisionAction.HYPOTHETICAL_SIGNAL, "CONFIRMED_RISK_APPROVED"
                                signals_by_day[day] += 1
                                move(S.READY_TO_EXECUTE, "hypothetical signal only")
                            else:
                                reason = "RISK_VETO"
                                move(S.RISK_LOCK, ",".join(risk.reasons))
                        elif status in {ExpectationStatus.INVALIDATED, ExpectationStatus.EXPIRED}:
                            move(S.HYPOTHESIS_INVALIDATED, reason)
                        else:
                            move(S.OBSERVING, reason)
                if cancellation and pending:
                    payload = {"hypothesis_id": pending.hypothesis.hypothesis_id, "run_id": run_id,
                               "reason": reason, "observed_at": now.isoformat()}
                    memory.record_event("expectation_events", f"{run_id}:cancel:{index}", pending.contract.expectation_id,
                                        cancellation, payload, observed_at=now)
                    events_count[cancellation] += 1
                if pending and (cancellation or (evaluation and evaluation.status in {
                        ExpectationStatus.CONFIRMED, ExpectationStatus.INVALIDATED, ExpectationStatus.EXPIRED})):
                    memory.record_event("hypothesis_events", f"{run_id}:terminal:{index}", pending.hypothesis.hypothesis_id,
                        cancellation or evaluation.status.value,
                        {"hypothesis_id": pending.hypothesis.hypothesis_id, "run_id": run_id,
                         "reason": reason, "decision_action": action.value}, observed_at=now)
                    pending = None
                decision = Decision(run_id, config.symbol, config.timeframe, dataset.source, candle.timestamp,
                    action, reason, machine.state, evidence=snapshot.favorable_evidence,
                    contradictions=snapshot.conflicting_evidence, missing_data=snapshot.missing_evidence,
                    candidate=plan, risk=risk, strategy_id=STRATEGY_ID, strategy_version=STRATEGY_VERSION,
                    config_hash=config_hash, decision_id=f"{run_id}:decision:{index}", created_at=now)
                payload = decision.as_dict()
                payload.update(snapshot_id=snapshot.snapshot_id, hypothesis_id=hypothesis_id,
                    retrieval={"sample_count": similar.sample_count, "sufficient_sample": similar.sufficient_sample,
                               "scope": "same_run_before_current_bar", "financial_mean_r": similar.result_in_r_mean})
                classification = "technical_failure" if not quality.valid else (
                    "insufficient_evidence" if action == DecisionAction.HYPOTHETICAL_SIGNAL else
                    "prevented_rule_violation" if reason == "RISK_VETO" else "valid_no_trade")
                experience = ExperienceRecord(f"{run_id}:experience:{index}", now.isoformat(), config.symbol, session,
                    regime, snapshot.snapshot_id, decision.decision_id, STRATEGY_ID, STRATEGY_VERSION, config_hash,
                    side, action.value, "REAL_ORDER", " -> ".join(evaluation.favorable + evaluation.missing) if evaluation else reason,
                    encode({"close": candle.close, "expectation_status": evaluation.status.value if evaluation else None}),
                    classification, {"result_in_r": None, "net_pnl": None, "execution_simulated": False},
                    {"data_valid": quality.valid, "reason_code": reason, "hypothesis_id": hypothesis_id,
                     "risk_approved": risk.approved if risk else None, "retrieval": payload["retrieval"],
                     "outcome_review": "pending; no future outcome or financial result assumed"},
                    source_data_reference=f"{dataset.reference}#bar={index}")
                memory.record_snapshot(snapshot.as_dict(), session=session, regime=regime, data_reference=experience.source_data_reference)
                memory.record_decision(decision, session=session, regime=regime,
                    context={key: payload[key] for key in ("snapshot_id", "hypothesis_id", "retrieval")})
                memory.record_experience(experience)
                journal.write(encode(payload) + "\n")
                decisions.append(payload)
                previous = candle
        if pending:
            payload = {"run_id": run_id, "hypothesis_id": pending.hypothesis.hypothesis_id,
                       "reason": "END_OF_DATA", "unresolved": True}
            memory.record_event("expectation_events", f"{run_id}:end", pending.contract.expectation_id,
                                "insufficient_data", payload, observed_at=stamps[-1] + delta)
            memory.record_event("hypothesis_events", f"{run_id}:end-hypothesis", pending.hypothesis.hypothesis_id,
                                "insufficient_data", payload, observed_at=stamps[-1] + delta)
            events_count["end_of_data_unresolved"] += 1
        # Namespace IDs differ between runs. Historical clocks and decision contents do not.
        semantic = encode(decisions).replace(run_id, "<run>")
        report = {**manifest, "status": "completed", "bars": len(decisions),
                  "actions": dict(Counter(d["action"] for d in decisions)),
                  "reasons": dict(Counter(d["reason_code"] for d in decisions)),
                  "expectation_events": dict(events_count),
                  "decision_digest": hashlib.sha256(semantic.encode()).hexdigest(),
                  "report_directory": str(directory.resolve()),
                  "limitations": ["Experimental baseline; no statistical edge established.",
                    "No fills, commissions, financial P&L or independent trade-outcome labels.",
                    "Experience counts are observations, not independent trades or calibrated probabilities.",
                    "Single timeframe; weekly FX closure convention without broker holiday calendar.",
                    "Prior runs excluded from automatic retrieval to prevent duplication and future leakage."]}
        machine.move(S.SHUTDOWN, "dataset exhausted", at=stamps[-1] + delta)
        transitions = [{"before": t.before.value, "after": t.after.value, "at": t.at.isoformat(), "reason": t.reason}
                       for t in machine.transitions]
        (directory / "transitions.json").write_text(encode(transitions), encoding="utf-8")
        (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        write_html(directory / "report.html", report, decisions)
        artifact("completed", {"decision_digest": report["decision_digest"], "bars": len(decisions)})
        return report
    except Exception as exc:
        artifact("failed", {"error_type": type(exc).__name__, "steps_completed": len(decisions)})
        raise


def write_html(path: Path, report: dict, decisions: list[dict]) -> None:
    rows = "".join("<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in (
        d["data_timestamp_utc"], d["action"], d["reason_code"],
        ", ".join(d["risk"]["reasons"]) if d["risk"] else "", d["retrieval"]["sample_count"])) + "</tr>" for d in decisions)
    path.write_text("""<!doctype html><html lang="pt-BR"><meta charset="utf-8">
<title>Aurelia FX - Replay EUR/USD</title><style>body{font:15px system-ui;background:#10181e;color:#e7edf0;margin:32px}
table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #30434d;text-align:left}
pre{white-space:pre-wrap;background:#17252e;padding:16px}h1{color:#43d69a}</style>
<h1>Replay EUR/USD</h1><p>Pesquisa experimental com candles fechados. Sinais hipotéticos, sem envio de ordens.</p>
<p>O horário da tabela indica a abertura do candle; a decisão ocorre no fechamento.</p>"""
        + f"<p><strong>{report['bars']} candles | {report['actions'].get('NO_TRADE', 0)} NO_TRADE | {report['actions'].get('HYPOTHETICAL_SIGNAL', 0)} sinais hipotéticos</strong></p>"
        + "<details><summary>Configuração, contagens e auditoria da execução</summary><pre>"
        + html.escape(json.dumps(report, ensure_ascii=False, indent=2))
        + "</pre></details><table><thead><tr><th>Candle UTC</th><th>Ação</th><th>Motivo</th><th>Veto de risco</th><th>Observações semelhantes anteriores</th></tr></thead><tbody>"
        + rows + "</tbody></table></html>", encoding="utf-8")
