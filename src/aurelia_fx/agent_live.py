"""Paper worker coordinator: durable positions, fresh quotes and explicit approval."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from .agent_model import predict
from .agent_forecast_view import forecast_view
from .agent_paper import PaperAccount, observed_quote
from .agent_research import SESSIONS, cached_forecast, intelligence_session
from .agent_strategy import attach_forecast, propose_pullback
from .forecasting.adapter import TimestralAdapter
from .forecasting.core import prepare
from .historical.core import closed_rows, readiness, utc
from .operation_control import LOCK
from .sessions import SessionEngine


def checkpoint(control, session_id):
    with control.memory.pool.connection() as c:
        row = c.execute(
            """SELECT payload_json FROM project_records
            WHERE record_type='agent_paper_checkpoint' AND record_key=%s
            ORDER BY recorded_at DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def claim(control, session_id, worker_id):
    with control.memory.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        state = control.latest(c)
        if state.get("session_id") != session_id:
            return False
        control.append(
            c,
            {**state, "sequence": state["sequence"] + 1, "execution_owner": worker_id},
        )
    return True


def project_account(control):
    with control.memory.pool.connection() as c:
        row = c.execute("""SELECT payload_json FROM project_records
            WHERE record_type='agent_paper_account' AND record_key='EURUSD:USD'
            ORDER BY recorded_at DESC LIMIT 1""").fetchone()
    return json.loads(row["payload_json"]) if row else None


def commit(control, account, worker_id, *, generation=None, **view):
    with control.memory.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        state = control.latest(c)
        if (
            state.get("session_id") != account.data["session_id"]
            or state.get("execution_owner") != worker_id
        ):
            return False
        if any(e["status"] == "opened" for e in account.events) and (
            state["desired"] != "running" or state.get("generation") != generation
        ):
            return False
        for event in account.events:
            text, digest = control.memory._encode(event)
            c.execute(
                """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
                VALUES('agent_paper_event',%s,%s,%s) ON CONFLICT DO NOTHING""",
                (event["event_id"], text, digest),
            )
        data = account.snapshot()
        text, digest = control.memory._encode(data)
        c.execute(
            """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('agent_paper_checkpoint',%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING""",
            (data["session_id"], text, digest),
        )
        desired = state["desired"]
        c.execute(
            """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('agent_paper_account','EURUSD:USD',%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING""",
            (text, digest),
        )
        target = "POSITION_OPEN" if data["position"] else "ANALYZING"
        message = (
            "Posição simulada em acompanhamento."
            if data["position"]
            else "Analisando candles fechados e aguardando uma oportunidade válida."
        )
        if desired == "stopped":
            target = "STOP_REQUESTED" if data["position"] else "STOPPED"
            message = (
                "Encerrando a posição simulada com cotação atual."
                if data["position"]
                else "Agente encerrado."
            )
        elif desired == "paused":
            target = "PAUSED"
            message = (
                "Novas entradas pausadas; posição existente continua em acompanhamento."
                if data["position"]
                else "Agente pausado."
            )
        control.append(
            c,
            {
                **state,
                **view,
                "sequence": state["sequence"] + 1,
                "state": target,
                "stage": "analysis",
                "message": view.get("message", message),
                "position": data["position"],
                "account": account.summary(),
            },
        )
    account.events.clear()
    return True


def management_tick(control, fetch, state, worker_id):
    saved = checkpoint(control, state["session_id"])
    if not saved or not saved.get("position"):
        if state.get("position"):
            raise ValueError(
                "Checkpoint da posição ausente. A posição não será descartada."
            )
        return False
    if not claim(control, state["session_id"], worker_id):
        return True
    account = PaperAccount(
        state["session_id"],
        state["lot"],
        state["symbol_contract"],
        saved["model_id"],
        saved["clock_id"],
        checkpoint=saved,
    )
    data = fetch("EURUSD", "M5", 100, include_current=True)
    quote = observed_quote(data, clock_id=saved["clock_id"])
    current = control.status()
    account.mark(
        quote, force_close="OPERATOR_STOP" if current["desired"] == "stopped" else None
    )
    commit(control, account, worker_id)
    if not account.data["position"] and current["desired"] == "running":
        control.publish(
            state["session_id"],
            expected_generation=current["generation"],
            expected_desired="running",
            state="QUEUED",
            message="Posição reconciliada. Verificando a versão para continuar a análise.",
        )
    return bool(account.data["position"])


def run_paper(
    control, repository, state, version, fetch, config, worker_id, stop, lease
):
    session_id = state["session_id"]
    saved = checkpoint(control, session_id)
    account = PaperAccount(
        session_id,
        state["lot"],
        state["symbol_contract"],
        version["model"]["model_id"],
        version["approval"]["clock_id"],
        checkpoint=saved,
        previous_account=project_account(control) if not saved else None,
    )
    if not claim(control, session_id, worker_id):
        return
    session = intelligence_session()
    model = version["model"]
    threshold = version["report"]["threshold"]
    now = datetime.now(timezone.utc)
    rows = repository.candles(
        clock_id=account.data["clock_id"],
        timeframe="M5",
        start=now - timedelta(days=60),
        as_of=now,
    )
    last_management = 0
    for index, row in enumerate(rows):
        if index % 48 == 0:
            lease.execute("SELECT 1")
            current = control.status()
            if current.get("session_id") != session_id or stop.is_set():
                return
            control.heartbeat(worker_id)
            if account.data["position"] and time.monotonic() - last_management >= 2:
                data = fetch("EURUSD", "M5", 100, include_current=True)
                account.mark(
                    observed_quote(data, clock_id=account.data["clock_id"]),
                    force_close="OPERATOR_STOP"
                    if current["desired"] == "stopped"
                    else None,
                )
                commit(control, account, worker_id)
                last_management = time.monotonic()
            if current["desired"] != "running" and not account.data["position"]:
                commit(control, account, worker_id)
                return
            control.publish(
                session_id,
                expected_desired=current["desired"],
                state="ANALYSIS_WARMUP",
                stage="analysis",
                message=f"Preparando o contexto ao vivo: {index}/{len(rows)} candles. Posições existentes continuam em acompanhamento.",
            )
        session.update(
            [row],
            spread_pips=row.get("spread_pips"),
            observed_at=utc(row["timestamp"]) + timedelta(minutes=5),
        )
    adapter = TimestralAdapter(config)
    sessions = SessionEngine(SESSIONS)
    last_persist = 0
    try:
        while not stop.is_set():
            lease.execute("SELECT 1")
            current = control.status()
            if current.get("session_id") != session_id:
                return
            control.heartbeat(worker_id)
            try:
                data = fetch("EURUSD", "M5", 500, include_current=True)
                quote = observed_quote(data, clock_id=account.data["clock_id"])
                account.mark(
                    quote,
                    force_close="OPERATOR_STOP"
                    if current["desired"] == "stopped"
                    else None,
                )
                if current["desired"] != "running":
                    commit(control, account, worker_id)
                    if not account.data["position"]:
                        return
                    stop.wait(3)
                    continue
                baseline = repository.latest(clock_id=account.data["clock_id"])
                history_block = readiness(
                    baseline,
                    as_of=datetime.now(timezone.utc),
                    clock_id=account.data["clock_id"],
                )
                expired = datetime.now(timezone.utc) >= utc(
                    version["approval"]["valid_until"]
                )
                closed = closed_rows(
                    data["candles"],
                    "M5",
                    start=utc(data["candles"][0]["timestamp"]),
                    as_of=utc(quote["at"]),
                )
                latest = closed[-1] if closed else None
                decision = None
                if latest and latest["timestamp"] != account.data["last_candle"]:
                    if (
                        session.last
                        and utc(latest["timestamp"]) < session.last.timestamp
                    ):
                        raise ValueError(
                            "A fonte retornou candles anteriores ao contexto carregado."
                        )
                    snapshot = session.update(
                        closed,
                        spread_pips=latest.get("spread_pips"),
                        observed_at=utc(latest["timestamp"]) + timedelta(minutes=5),
                    )
                    setup, reason = propose_pullback(
                        snapshot,
                        session.history,
                        daily_history=session.aggregator.history["D1"],
                    )
                    age = (
                        utc(quote["at"])
                        - utc(latest["timestamp"])
                        - timedelta(minutes=5)
                    ).total_seconds()
                    reason = (
                        "HISTORY_NOT_READY"
                        if history_block
                        else "MODEL_APPROVAL_EXPIRED"
                        if expired
                        else "SIGNAL_TOO_OLD"
                        if age > 90 or age < 0
                        else "POSITION_ALREADY_OPEN"
                        if account.data["position"]
                        else reason
                    )
                    decision = dict(
                        action="WAIT",
                        reason=reason or "Aguardando avaliação do modelo.",
                        at=datetime.now(timezone.utc).isoformat(),
                        quote_at=quote["at"],
                        candle=latest["timestamp"],
                    )
                    if setup and not reason:
                        context = prepare(
                            session.history,
                            utc(latest["timestamp"]) + timedelta(minutes=5),
                            config,
                        )
                        _, output = cached_forecast(
                            control.memory, context, config, adapter
                        )
                        features = attach_forecast(setup, output)
                        probability = predict(model, features)
                        decision.update(
                            probability=probability,
                            threshold=threshold,
                            forecast=forecast_view(
                                output, context, clock_id=account.data["clock_id"],
                                configuration=config.fingerprint,
                                generated_at=datetime.now(timezone.utc),
                            ),
                        )
                        if probability >= threshold:
                            fresh = control.status()
                            fresh_data = fetch(
                                "EURUSD", "M5", 100, include_current=True
                            )
                            fresh_quote = observed_quote(
                                fresh_data, clock_id=account.data["clock_id"]
                            )
                            account.mark(fresh_quote)
                            if (
                                fresh["desired"] == "running"
                                and fresh.get("generation") == current.get("generation")
                                and utc(fresh_quote["observed_at"])
                                - utc(fresh_quote["at"])
                                <= timedelta(seconds=5)
                                and utc(fresh_quote["observed_at"])
                                - utc(setup["signal_at"])
                                <= timedelta(seconds=90)
                            ):
                                before = account.snapshot()
                                before_events = list(account.events)
                                outcome = account.open(
                                    setup,
                                    features,
                                    probability,
                                    fresh_quote,
                                    active_sessions=sessions.identify(
                                        utc(fresh_quote["at"])
                                    ).active_sessions,
                                )
                                decision.update(
                                    at=fresh_quote["observed_at"],
                                    quote_at=fresh_quote["at"],
                                    action="BUY"
                                    if outcome["approved"]
                                    and setup["candidate"].side == "long"
                                    else "SELL"
                                    if outcome["approved"]
                                    else "WAIT",
                                    reason="Modelo, contexto e risco aprovaram a entrada simulada."
                                    if outcome["approved"]
                                    else ", ".join(outcome["reasons"]),
                                    entry=account.data["position"]["entry"]
                                    if outcome["approved"]
                                    else None,
                                    stop=setup["candidate"].stop,
                                    target=setup["candidate"].target,
                                    risk=account.data["position"]["initial_risk"]
                                    if outcome["approved"]
                                    else None,
                                )
                                if not commit(
                                    control,
                                    account,
                                    worker_id,
                                    generation=current["generation"],
                                    last_decision=decision,
                                ):
                                    account = PaperAccount(
                                        session_id,
                                        state["lot"],
                                        state["symbol_contract"],
                                        model["model_id"],
                                        version["approval"]["clock_id"],
                                        checkpoint=before,
                                    )
                                    account.events = before_events
                                    continue
                            else:
                                decision["reason"] = (
                                    "A intenção mudou ou a confirmação ficou antiga durante a inferência."
                                )
                        else:
                            decision["reason"] = (
                                "O filtro aprendido não aprovou esta oportunidade."
                            )
                    account.data["last_candle"] = latest["timestamp"]
                    account.event(
                        "decision",
                        decision["at"],
                        decision=decision,
                        snapshot_id=snapshot.snapshot_id,
                    )
                if account.events or decision or time.monotonic() - last_persist >= 10:
                    view = dict(last_decision=decision) if decision else {}
                    if expired or history_block:
                        view["message"] = (
                            "Novas entradas bloqueadas: aprovação expirada ou histórico indisponível. A posição existente continua em acompanhamento."
                        )
                    if not commit(
                        control,
                        account,
                        worker_id,
                        generation=current["generation"],
                        **view,
                    ):
                        return
                    last_persist = time.monotonic()
            except (RuntimeError, ValueError, KeyError) as exc:
                control.publish(
                    session_id,
                    expected_desired=current["desired"],
                    state="WAITING_QUOTE",
                    stage="analysis",
                    message="Aguardando fonte ou modelo válido: " + str(exc)[:180],
                )
            stop.wait(3)
    finally:
        adapter.close()
