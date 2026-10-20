"""Windows product worker: persistent commands, MT5 preparation and research."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from aurelia_fx.historical.collector import collect  # noqa: E402
from aurelia_fx.historical.repository import HistoricalRepository  # noqa: E402
from aurelia_fx.operation_control import (  # noqa: E402
    TERMINAL,
    WORKER_LOCK,
    OperationControl,
    validate_lot,
)
from aurelia_fx.storage import open_memory  # noqa: E402


class InterruptedPreparation(Exception):
    pass


def main():
    from mt5_provider import fetch_history

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    memory = open_memory()
    control = OperationControl(memory)
    repository = HistoricalRepository(memory)
    worker_id = str(uuid4())
    handled = None
    pid_path = ROOT / "data/agent.pid"
    last_heartbeat = 0
    try:
        with memory.pool.connection() as lease:
            if not lease.execute(
                "SELECT pg_try_advisory_lock(%s) AS acquired", (WORKER_LOCK,)
            ).fetchone()["acquired"]:
                print("O serviço do agente já está ativo.", flush=True)
                return 0
            pid_path.write_text(str(os.getpid()), encoding="ascii")
            initial = control.status()
            if initial.get("session_id") and initial["state"] not in TERMINAL | {
                "QUEUED"
            }:
                control.publish(
                    initial["session_id"],
                    expected_desired=initial["desired"],
                    state="RECOVERY_REQUIRED",
                    desired="paused",
                    message="O serviço reiniciou. Revise o estado e clique em Retomar.",
                )
            while not stop.is_set():
                lease.execute("SELECT 1")
                if time.monotonic() - last_heartbeat >= 15:
                    control.heartbeat(worker_id)
                    last_heartbeat = time.monotonic()
                state = control.status()
                session_id = state.get("session_id")
                if session_id and state.get("position"):
                    from aurelia_fx.agent_live import management_tick

                    try:
                        management_tick(control, fetch_history, state, worker_id)
                    except (RuntimeError, ValueError) as exc:
                        control.publish(
                            session_id,
                            expected_desired=state["desired"],
                            state="WAITING_QUOTE",
                            stage="analysis",
                            message="Posição preservada. Aguardando cotação para reconciliar: "
                            + str(exc)[:160],
                        )
                    handled = None
                elif session_id and state["desired"] in {"stopped", "paused"}:
                    target = "STOPPED" if state["desired"] == "stopped" else "PAUSED"
                    if state["state"] not in {target, "RECOVERY_REQUIRED"}:
                        control.publish(
                            session_id,
                            expected_generation=state.get("generation"),
                            expected_desired=state["desired"],
                            state=target,
                            message="Agente encerrado."
                            if target == "STOPPED"
                            else "Agente pausado. Clique em Retomar para continuar.",
                        )
                    handled = None
                elif (
                    session_id
                    and state["state"] == "QUEUED"
                    and handled != (session_id, state.get("generation"))
                ):
                    try:
                        prepare(
                            control,
                            repository,
                            state,
                            fetch_history,
                            worker_id,
                            stop,
                            lease,
                        )
                    except InterruptedPreparation:
                        pass
                    except Exception as exc:
                        if lease.closed:
                            raise
                        control.publish(
                            session_id,
                            expected_generation=state.get("generation"),
                            state="ERROR",
                            stage="error",
                            error_type=type(exc).__name__,
                            message="Não foi possível preparar o agente: "
                            + str(exc)[:220],
                        )
                        print(
                            "Agent preparation failed:", type(exc).__name__, flush=True
                        )
                    handled = (session_id, state.get("generation"))
                stop.wait(3)
    finally:
        if pid_path.exists() and pid_path.read_text(encoding="ascii").strip() == str(
            os.getpid()
        ):
            pid_path.unlink()
        memory.close()
    return 0


def prepare(control, repository, state, fetch, worker_id, stop, lease=None):
    session_id = state["session_id"]
    generation = state["generation"]
    capture_days = 30

    def publish(**changes):
        result = control.publish(session_id, expected_generation=generation, **changes)
        if result is None:
            raise InterruptedPreparation()
        return result

    def check():
        current = control.status()
        if (
            stop.is_set()
            or current.get("session_id") != session_id
            or current["desired"] != "running"
            or current.get("generation") != generation
        ):
            raise InterruptedPreparation()
        control.heartbeat(worker_id)

    def capture(symbol, timeframe, count, *, include_current=False):
        check()
        publish(
            state="LOADING_HISTORY"
            if capture_days == 30
            else "LOADING_RESEARCH_HISTORY",
            stage="history" if capture_days == 30 else "training",
            message=f"Atualizando {capture_days} dias de {symbol} em {timeframe}. Os dados válidos existentes serão reutilizados.",
            current_timeframe=timeframe,
        )
        return fetch(symbol, timeframe, count, include_current=include_current)

    check()
    publish(
        state="CONNECTING",
        stage="connection",
        message="Conectando ao MT5 e verificando o lote do EUR/USD.",
    )
    source = fetch("EURUSD", "M5", 100, include_current=False)
    contract = source.get("symbol_contract")
    if not contract:
        raise ValueError(
            "A fonte não informou o contrato de lotes do ativo. Atualize a ponte MT5."
        )
    publish(symbol_contract=contract)
    validate_lot(state["lot"], contract)
    if (
        contract.get("currency_profit") != "USD"
        or not contract.get("contract_size", 0) > 0
    ):
        raise ValueError(
            "A simulação inicial requer contrato EURUSD com resultado em USD e tamanho de contrato válido."
        )
    check()
    baseline = collect(repository, capture, days=30, full=False)
    check()
    history = dict(
        baseline_id=baseline["baseline_id"],
        start=baseline["start"],
        end=baseline["as_of"],
        status=baseline["status"],
        blocker=baseline["blocker"],
        bars={tf: r["statistics"]["bars"] for tf, r in baseline["timeframes"].items()},
        clock_id=baseline["clock_id"],
    )
    if baseline["status"] != "ready":
        publish(
            state="INSUFFICIENT_DATA",
            stage="history",
            history=history,
            message="O histórico foi capturado, mas ainda não atende à qualidade exigida: "
            + str(baseline["blocker"]),
        )
        return
    if baseline["clock_id"] != source["source_clock"]["clock_id"]:
        raise ValueError(
            "A fonte mudou durante a preparação. Inicie novamente para validar o novo contrato."
        )
    if source["source_clock"].get("profile") != "thinkmarkets-ny-close-v1":
        raise ValueError(
            "Configure e valide o calendário desta corretora antes do treinamento integrado."
        )
    publish(
        state="LOADING_HISTORY",
        stage="history",
        history=history,
        symbol_contract=contract,
        message="Os 30 dias estão preparados. Capturando mais 30 dias anteriores para aquecer a análise sem usar informações futuras.",
    )
    from aurelia_fx.agent_history import collect_training_history
    from aurelia_fx.agent_model import PROTOCOL
    from aurelia_fx.agent_research import build_samples
    from aurelia_fx.agent_validation import validate
    from aurelia_fx.forecasting.adapter import TimestralAdapter
    from aurelia_fx.forecasting.config import load_config

    config = load_config()
    if not config.enabled or config.revision == "main":
        raise ValueError(
            "Ative o Timestral com uma revisao imutavel dos pesos antes de treinar."
        )
    from aurelia_fx.agent_registry import approved_version

    version = approved_version(
        repository.memory,
        lot=state["lot"],
        clock_id=baseline["clock_id"],
        configuration=config.fingerprint,
    )
    if version:
        check()
        publish(
            training={
                **version["report"],
                "status": "approved",
                "active_version": version["model"]["model_id"],
            },
            approval_id=version["approval"]["approval_id"],
            history=history,
            symbol_contract=contract,
        )
        from aurelia_fx.agent_live import run_paper

        run_paper(
            control,
            repository,
            control.status(),
            version,
            fetch,
            config,
            worker_id,
            stop,
            lease,
        )
        return
    adapter = TimestralAdapter(config)
    report = None
    try:
        publish(
            state="CHECKING_MODEL",
            stage="training",
            message="Verificando o Timestral local antes da pesquisa historica.",
        )
        adapter.warmup()
        for capture_days in PROTOCOL["research_history_days"]:
            check()
            publish(
                state="LOADING_RESEARCH_HISTORY",
                stage="training",
                history=history,
                message=f"Preparando {capture_days - 30} dias de pesquisa M5 e 30 dias anteriores de aquecimento.",
                training=dict(
                    status="preparing_examples",
                    samples=None,
                    candidate_version=None,
                    report_id=None,
                    partitions=None,
                    final_accessed=False,
                    validation=None,
                    final=None,
                    reason=None,
                    message=None,
                    walk_forward=None,
                    operational_validation_samples=None,
                    research_history_days=capture_days,
                ),
            )
            warmup = collect_training_history(
                repository,
                capture,
                days=capture_days,
                expected_clock_id=baseline["clock_id"],
            )
            check()
            if warmup["status"] != "ready":
                if report is not None:
                    report = {**report, "history_extension_unavailable": capture_days}
                    break
                publish(
                    state="INSUFFICIENT_DATA",
                    stage="history",
                    history=history,
                    message="O historico recente foi preparado, mas o arquivo anterior M5 ainda nao tem cobertura suficiente. Carregue mais historico no MT5.",
                )
                return
            frozen, rows = repository.frozen_candles(
                warmup, record_type="agent_training_history"
            )
            dataset, partitions, candles = build_samples(
                repository.memory,
                rows,
                baseline=frozen,
                lot=state["lot"],
                contract=contract,
                forecast_config=config,
                adapter=adapter,
                progress=publish,
                check=check,
            )
            report = validate(
                repository.memory,
                dataset,
                partitions,
                candles,
                lot=state["lot"],
                contract=contract,
                progress=publish,
                check=check,
            )
            if report["status"] != "insufficient_samples":
                break
    finally:
        adapter.close()
    check()
    message = {
        "insufficient_samples": "A simulação histórica terminou, mas ainda não há amostra suficiente para validar o modelo.",
        "rejected": "O modelo candidato não passou na validação. A operação permanece bloqueada.",
        "validated_pending_approval": "A versão candidata passou nos critérios para simulação. Revise o relatório antes de aprová-la.",
    }[report["status"]]
    publish(
        state="AWAITING_APPROVAL"
        if report["status"] == "validated_pending_approval"
        else "TRAINING_BLOCKED",
        stage="validation",
        history=history,
        symbol_contract=contract,
        training=report,
        message=message,
    )


if __name__ == "__main__":
    raise SystemExit(main())
