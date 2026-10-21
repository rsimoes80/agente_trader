"""Paper worker coordinator: durable positions, fresh quotes and explicit approval."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from .agent_model import predict
from .autonomous_lab import AutonomousLab
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


def project_account(control, account_key='EURUSD:USD'):
    with control.memory.pool.connection() as c:
        row = c.execute("""SELECT payload_json FROM project_records
            WHERE record_type='agent_paper_account' AND record_key=%s
            ORDER BY recorded_at DESC LIMIT 1""",(account_key,)).fetchone()
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
        native=account.data.get('execution_mode')=='demo'
        if not native and any(e["status"] == "opened" for e in account.events) and (
            state["desired"] != "running" or state.get("generation") != generation
        ):
            return False
        for event in account.events:
            text, digest = control.memory._encode(event)
            c.execute(
                """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
                VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                ('agent_demo_event' if native else 'agent_paper_event',event["event_id"], text, digest),
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
            VALUES('agent_paper_account',%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING""",
            (data.get('account_key','EURUSD:USD'),text, digest),
        )
        if native:
            for key in account.applied:
                applied,hashed=control.memory._encode(dict(key=key,session_id=data['session_id']))
                c.execute("""INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
                    VALUES('agent_demo_applied',%s,%s,%s) ON CONFLICT DO NOTHING""",(key,applied,hashed))
        target = "POSITION_OPEN" if data["position"] else "ANALYZING"
        message = (
            "Posição simulada em acompanhamento."
            if data["position"]
            else "Analisando candles fechados e aguardando uma oportunidade válida."
        )
        if data.get("research_mode"):
            message = "Experimento simulado em acompanhamento; o resultado atualizará a memória deste contexto." if data["position"] else "Pesquisa autônoma ativa: analisando o mercado e selecionando o próximo experimento."
        if native:
            message='Operação no MT5 Demo em acompanhamento.' if data['position'] else 'Analisando o mercado para a próxima hipótese na conta demo.'
            if data.get('pending_execution'):message='Reconciliando uma execução demo; novas entradas bloqueadas para evitar duplicação.'
            elif not data.get('trading_enabled'):message='MT5 Demo conectado. Ative AlgoTrading no terminal para permitir os envios automáticos.'
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
                "recovery_attempts":0,
                "error_type":None,
                "state": target,
                "stage": "analysis",
                "message": view.get("message", message),
                "position": data["position"],
                "pending_execution":data.get('pending_execution',False),
                "account": account.summary(),
                "autonomy": AutonomousLab("",execution_mode='demo' if native else 'paper').summary(data["lab_state"])
                    if data.get("research_mode") else None,
            },
        )
    account.events.clear()
    if native:account.applied.clear()
    return True


def management_tick(control, fetch, state, worker_id):
    saved = checkpoint(control, state["session_id"])
    native=state.get('mode')=='demo' and bool(state.get('demo_authorization'))
    if not native and (not saved or not (saved.get("position") or saved.get('pending_execution'))):
        if state.get("position"):
            raise ValueError(
                "Checkpoint da posição ausente. A posição não será descartada."
            )
        return False
    if not claim(control, state["session_id"], worker_id):
        return True
    account = make_account(control,state,saved=saved) if native else PaperAccount(
        state["session_id"],
        state["lot"],
        state["symbol_contract"],
        saved["model_id"],
        saved["clock_id"],
        checkpoint=saved,
        research_mode=saved.get("research_mode",False),
    )
    data = fetch("EURUSD", "M5", 100, include_current=True)
    quote = observed_quote(data, clock_id=account.data["clock_id"])
    current = control.status()
    account.mark(
        quote, force_close="OPERATOR_STOP" if current["desired"] == "stopped" else None
    )
    commit(control, account, worker_id)
    if not account.data["position"] and not account.data.get('pending_execution') and current["desired"] == "running":
        control.publish(
            state["session_id"],
            expected_generation=current["generation"],
            expected_desired="running",
            state="QUEUED",
            message="Posição reconciliada. Verificando a versão para continuar a análise.",
        )
    return bool(account.data["position"] or account.data.get('pending_execution'))


def make_account(control,state,*,saved=None):
    from .agent_demo import NativeDemoAccount
    from .demo_gateway import DemoGateway
    from .demo_terminal import demo_terminal
    auth=(saved or {}).get('authorization') or state['demo_authorization']
    gateway=DemoGateway(control,auth,demo_terminal)
    return NativeDemoAccount(gateway,state['symbol_contract'],checkpoint=saved,
                             previous_account=None if saved else project_account(control,'DEMO:'+auth['account_id']))


def demo_recovery_required(control,state):
    """Find accepted sends even if the process died before its first checkpoint."""
    auth=state.get('demo_authorization')
    if state.get('mode')!='demo' or not auth:return False
    with control.memory.pool.connection() as c:
        row=c.execute("""SELECT 1 FROM (
            SELECT DISTINCT ON (record_key) record_key,payload_json::jsonb AS p
            FROM project_records WHERE record_type='agent_demo_intent'
            AND payload_json::jsonb #>> '{owner,account_id}'=%s
            AND payload_json::jsonb #>> '{owner,session_id}'=%s
            ORDER BY record_key,(payload_json::jsonb->>'sequence')::bigint DESC
            ) latest WHERE NOT (p #> '{request,broker}' ? 'position')
            AND (p->>'status' NOT IN ('CLOSED','REJECTED','CANCELLED')
            OR (p->>'status'='CLOSED' AND NOT EXISTS (
                SELECT 1 FROM project_records applied WHERE applied.record_type='agent_demo_applied'
                AND applied.record_key=latest.record_key||':closed'))) LIMIT 1""",
            (auth['account_id'],state['session_id'])).fetchone()
    return bool(row)


def run_paper(
    control, repository, state, version, fetch, config, worker_id, stop, lease,
    *, research_policy=None,
):
    session_id = state["session_id"]
    saved = checkpoint(control, session_id)
    account = make_account(control,state,saved=saved) if state.get('mode')=='demo' else PaperAccount(
        session_id,
        state["lot"],
        state["symbol_contract"],
        research_policy.protocol_id if research_policy else version["model"]["model_id"],
        state["history"]["clock_id"] if research_policy else version["approval"]["clock_id"],
        checkpoint=saved,
        previous_account=project_account(control) if not saved else None,
        research_mode=bool(research_policy),
    )
    if not claim(control, session_id, worker_id):
        return
    session = intelligence_session()
    model = version["model"] if version else None
    threshold = version["report"]["threshold"] if version else None
    if research_policy and (account.data["lab_state"].get("protocol_id") != research_policy.protocol_id
                            or not account.data["lab_state"].get("seed_complete")):
        seeded = research_policy.seed(control.memory,
            clock_id=account.data["clock_id"],configuration=config.fingerprint,
            as_of=datetime.now(timezone.utc))
        if account.data['lab_state'].get('protocol_id')==research_policy.protocol_id:
            for key in ('live','last_result','last_failed','excluded_uncertain'):
                if key in account.data['lab_state']:seeded[key]=account.data['lab_state'][key]
        account.data['lab_state']=seeded
    if research_policy:
        control.publish(session_id,expected_generation=state.get("generation"),
                        autonomy=research_policy.summary(account.data["lab_state"]))
    if state.get('mode')=='demo':
        account.sync()
        commit(control,account,worker_id)
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
            if (account.data["position"] or account.data.get('pending_execution')) and time.monotonic() - last_management >= 2:
                data = fetch("EURUSD", "M5", 100, include_current=True)
                account.mark(
                    observed_quote(data, clock_id=account.data["clock_id"]),
                    force_close="OPERATOR_STOP"
                    if current["desired"] == "stopped"
                    else None,
                )
                commit(control, account, worker_id)
                last_management = time.monotonic()
            if current["desired"] != "running" and not account.data["position"] and not account.data.get('pending_execution'):
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
    last_history_refresh = 0
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
                    if not account.data["position"] and not account.data.get('pending_execution'):
                        return
                    stop.wait(3)
                    continue
                baseline = repository.latest(clock_id=account.data["clock_id"])
                history_block = readiness(
                    baseline,
                    as_of=datetime.now(timezone.utc),
                    clock_id=account.data["clock_id"],
                )
                if research_policy and history_block and time.monotonic()-last_history_refresh >= 60:
                    from .historical.collector import collect
                    last_history_refresh=time.monotonic()
                    baseline=collect(repository,fetch,days=30,full=False)
                    history_block=readiness(baseline,as_of=datetime.now(timezone.utc),clock_id=account.data["clock_id"])
                expired = not research_policy and datetime.now(timezone.utc) >= utc(
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
                        **({"research":True} if research_policy else {}),
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
                        hypothesis = research_policy.select(features,setup["snapshot"],account.data["lab_state"]) if research_policy else None
                        probability = None if research_policy else predict(model, features)
                        decision.update(
                            probability=probability,
                            threshold=threshold,
                            forecast=forecast_view(
                                output, context, clock_id=account.data["clock_id"],
                                configuration=config.fingerprint,
                                generated_at=datetime.now(timezone.utc),
                            ),
                            hypothesis=hypothesis,
                        )
                        if research_policy or probability >= threshold:
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
                                    **({"hypothesis":hypothesis} if research_policy else {}),
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
                                    reason=("Hipótese de pesquisa selecionada automaticamente; risco aceitou a entrada simulada." if research_policy else "Modelo, contexto e risco aprovaram a entrada simulada.")
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
                                    if account.data.get('execution_mode')=='demo':
                                        raise RuntimeError('A reconciliação demo requer recuperação do proprietário da sessão.')
                                    account = PaperAccount(
                                        session_id,
                                        state["lot"],
                                        state["symbol_contract"],
                                        account.data["model_id"],
                                        account.data["clock_id"],
                                        checkpoint=before,
                                        research_mode=bool(research_policy),
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
                        technical_snapshot=snapshot.as_dict(),
                        candles=closed[-100:],
                        clock_id=account.data['clock_id'],
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
            except (RuntimeError, ValueError, KeyError, OSError) as exc:
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
