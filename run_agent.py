"""Windows product worker: persistent commands, MT5 preparation and research."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
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
from aurelia_fx.source_clock import SourceClockUnavailable  # noqa: E402


class InterruptedPreparation(Exception):
    pass


class RecoverableSourceError(RuntimeError):
    pass


def guarded_fetch(fetch, *args, **kwargs):
    try:
        return fetch(*args, **kwargs)
    except RuntimeError as exc:
        raise RecoverableSourceError(str(exc)) from exc


def retry_due(state, now=None):
    if state.get("state") not in {"WAITING_SOURCE","RECOVERING","INSUFFICIENT_DATA"} or state.get("desired") != "running":
        return False
    if state['state']=='INSUFFICIENT_DATA' and not autonomous_session(state):return False
    if not state.get('retry_after'):return False
    return (now or datetime.now(timezone.utc)) >= datetime.fromisoformat(state["retry_after"])


def autonomous_session(state):
    return (state.get('execution_profile') or 'autonomous_'+state.get('mode','paper')) in {'autonomous_paper','autonomous_demo'}


def recovery_changes(state,exc,*,now=None):
    attempt=state.get('recovery_attempts',0)+1
    delay=min(300,10*2**min(attempt-1,5))
    return dict(state='RECOVERING',stage='connection',recovery_attempts=attempt,
                retry_after=((now or datetime.now(timezone.utc))+timedelta(seconds=delay)).isoformat(),
                error_type=type(exc).__name__,
                message=f'Falha temporária na execução ({type(exc).__name__}). Sessão preservada; nova tentativa automática em {delay} segundos.')


def single_asset_main(*,symbol='EURUSD',managed_stop=None,progress=None):
    from mt5_provider import fetch_history

    stop = managed_stop if managed_stop is not None else threading.Event()
    if managed_stop is None:
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
    memory = open_memory()
    control = OperationControl(memory,symbol) if managed_stop is not None else OperationControl(memory)
    repository = HistoricalRepository(memory,symbol) if managed_stop is not None else HistoricalRepository(memory)
    if progress:
        original_heartbeat=control.heartbeat
        def heartbeat(*args,**kwargs):
            if getattr(control,'runtime_profile',None):kwargs['engine_version']='multi-instrument-v1'
            result=original_heartbeat(*args,**kwargs);progress();return result
        control.heartbeat=heartbeat
    worker_id = str(uuid4())
    handled = None
    pid_path = ROOT / "data/agent.pid" if managed_stop is None else None
    last_heartbeat = 0
    try:
        with memory.pool.connection() as lease:
            import hashlib
            lock_key=int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:4],'big',signed=True)
            lock_query="SELECT pg_try_advisory_lock(%s,%s) AS acquired" if managed_stop is not None else "SELECT pg_try_advisory_lock(%s) AS acquired"
            lock_args=(WORKER_LOCK,lock_key) if managed_stop is not None else (WORKER_LOCK,)
            if not lease.execute(lock_query,lock_args).fetchone()["acquired"]:
                print("O serviço do agente já está ativo.", flush=True)
                return 0
            if pid_path:pid_path.write_text(str(os.getpid()), encoding="ascii")
            initial = control.status()
            autonomous = autonomous_session(initial)
            if initial.get("session_id") and autonomous and initial["desired"] == "running" and initial["state"] != "STOPPED":
                control.publish(initial["session_id"],expected_desired='running',
                                expected_generation=initial.get('generation'),state="QUEUED",error_type=None,
                                execution_profile=initial.get('execution_profile') or 'autonomous_'+initial.get('mode','paper'),
                                message="Retomada automática: reconciliando a sessão e a memória do agente.")
            elif initial.get("session_id") and not autonomous and initial["state"] not in TERMINAL | {
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
                if managed_stop is not None and symbol!='EURUSD' and not getattr(control,'runtime_profile',None):
                    try:
                        from aurelia_fx.runtime_profiles import provision
                        from aurelia_fx.instrument_research import InstrumentResearchProfile
                        own=control.status();frozen=own.get('research_profile')
                        if frozen:
                            control.runtime_profile=InstrumentResearchProfile.from_dict(frozen)
                        else:
                            account_id=(OperationControl(memory).status().get('demo_authorization') or {}).get('account_id')
                            if not account_id:raise ValueError('DEMO_ACCOUNT_IDENTITY_REQUIRED')
                            def preparation_progress(**fields):
                                memory.record_project_data('instrument_preparation_status',symbol,dict(symbol=symbol,**fields))
                                control.heartbeat(worker_id)
                            control.runtime_profile=provision(memory,symbol,account_id,fetch_history,progress=preparation_progress)
                        repository=HistoricalRepository(memory,symbol,profile=control.runtime_profile)
                    except (RuntimeError,ValueError) as exc:
                        memory.record_project_data('instrument_preparation_status',symbol,
                            dict(symbol=symbol,stage='waiting',message=str(exc)[:180]))
                        control.heartbeat(worker_id);stop.wait(30);continue
                if time.monotonic() - last_heartbeat >= 15:
                    control.heartbeat(worker_id)
                    last_heartbeat = time.monotonic()
                state = control.status()
                session_id = state.get("session_id")
                from aurelia_fx.agent_live import management_tick,demo_recovery_required
                if session_id and (state.get("position") or state.get('pending_execution') or demo_recovery_required(control,state)):

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
                elif retry_due(state):
                    control.publish(
                        session_id,
                        expected_generation=state["generation"],
                        state="QUEUED",
                        message="Verificando novamente a conexão e o relógio do MT5.",
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
                    except (RecoverableSourceError, SourceClockUnavailable) as exc:
                        control.publish(
                            session_id,
                            expected_generation=state.get("generation"),
                            state="WAITING_SOURCE",
                            stage="connection",
                            retry_after=(datetime.now(timezone.utc)+timedelta(seconds=10)).isoformat(),
                            message="Aguardando o MT5 conectado e o horário da fonte validado. Nova tentativa automática em 10 segundos: " + str(exc)[:140],
                        )
                    except Exception as exc:
                        if lease.closed:
                            raise
                        changes=recovery_changes(state,exc) if autonomous_session(state) else dict(
                            state='ERROR',stage='error',error_type=type(exc).__name__,
                            message='Não foi possível preparar o agente: '+str(exc)[:220])
                        control.publish(
                            session_id,
                            expected_generation=state.get("generation"),
                            expected_desired='running',
                            **changes,
                        )
                        print(
                            "Agent preparation failed:", type(exc).__name__, flush=True
                        )
                    handled = (session_id, state.get("generation"))
                stop.wait(3)
    finally:
        if pid_path and pid_path.exists() and pid_path.read_text(encoding="ascii").strip() == str(
            os.getpid()
        ):
            pid_path.unlink()
        memory.close()
    return 0


def coordinated_main(settings=None):
    from aurelia_fx.asset_registry import AssetRegistry
    from aurelia_fx.multi_asset_coordinator import MultiAssetCoordinator
    from aurelia_fx.forecasting.shared import POOL
    from run_agent_supervisor import stall_limit
    stop=threading.Event()
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    memory=open_memory();pid_path=ROOT/'data/agent.pid';last_report=0.
    os.environ['AGENTE_TRADER_COORDINATED']='1'
    coordinator=MultiAssetCoordinator(
        lambda:[a['symbol'] for a in AssetRegistry(memory).list() if a.get('selected')],
        lambda symbol,event,progress:single_asset_main(symbol=symbol,managed_stop=event,progress=progress),
        stall_seconds=stall_limit(),max_workers=(settings or {}).get('max_workers',8))
    try:
        with memory.pool.connection() as lease:
            if not lease.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(WORKER_LOCK,)).fetchone()['acquired']:
                print('O serviço do agente já está ativo.',flush=True);return 0
            pid_path.write_text(str(os.getpid()),encoding='ascii')
            try:
                while not stop.is_set():
                    lease.execute('SELECT 1')
                    status=coordinator.poll()
                    if time.monotonic()-last_report>=15:
                        memory.record_project_data('agent_multi_asset_coordinator','current',status)
                        if status['healthy'] and os.environ.get('AURELIA_AGENT_SUPERVISED')=='1':
                            print('AFX_AGENT_PROGRESS:coordinator',flush=True)
                        last_report=time.monotonic()
                    stop.wait(3)
            finally:
                if not coordinator.close(timeout=15):
                    # Do not release the singleton lease while a worker may still
                    # send. The supervisor will terminate the owned process tree.
                    print('Asset worker still stopping; singleton lease preserved for watchdog recovery.',flush=True)
                    while any(w['alive'] for w in coordinator.status()['workers'].values()):time.sleep(1)
                POOL.close()
                lease.execute('SELECT pg_advisory_unlock(%s)',(WORKER_LOCK,))
    finally:
        if pid_path.exists() and pid_path.read_text(encoding='ascii').strip()==str(os.getpid()):pid_path.unlink()
        memory.close()
    return 0


def main():
    from aurelia_fx.multi_asset_settings import load_settings
    settings=load_settings(ROOT)
    return coordinated_main(settings) if settings['enabled'] else single_asset_main()


def prepare(control, repository, state, fetch, worker_id, stop, lease=None):
    symbol=getattr(control,'symbol','EURUSD');profile=getattr(repository,'profile',None)
    if symbol!='EURUSD' and not profile:
        raise ValueError('O ciclo deste ativo ainda exige a integração do perfil e da execução multiativo.')
    if profile and state.get('mode')!='demo':raise ValueError('Este ativo requer MT5 Demo no ciclo coordenado.')
    original_fetch = fetch
    def fetch(*args, **kwargs):
        return guarded_fetch(original_fetch, *args, **kwargs)

    session_id = state["session_id"]
    generation = state["generation"]

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

    history_days=30
    def capture(symbol, timeframe, count, *, include_current=False):
        check()
        publish(
            state="LOADING_HISTORY",
            stage="history",
            message=f"Atualizando {history_days} dias de {symbol} em {timeframe}. Os dados válidos existentes serão reutilizados.",
            current_timeframe=timeframe,
        )
        return fetch(symbol, timeframe, count, include_current=include_current)

    check()
    publish(
        state="CONNECTING",
        stage="connection",
        error_type=None,
        message="Conectando ao MT5 e verificando o lote de "+symbol+".",
    )
    source = fetch(symbol, "M5", 100, include_current=False)
    if profile and source.get('symbol')!=symbol:raise ValueError('PREPARATION_SOURCE_INSTRUMENT_MISMATCH')
    contract = source.get("symbol_contract")
    if not contract:
        raise ValueError(
            "A fonte não informou o contrato de lotes do ativo. Atualize a ponte MT5."
        )
    publish(symbol_contract=contract)
    validate_lot(state["lot"], contract)
    if not profile and (
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
        **(dict(symbol=symbol,profile_id=profile.fingerprint) if profile else {}),
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
            retry_after=(datetime.now(timezone.utc)+timedelta(seconds=60)).isoformat(),
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
            "Configure e valide o calendário desta corretora antes da análise."
        )
    publish(
        state="LOADING_HISTORY",
        stage="history",
        history=history,
        symbol_contract=contract,
        message="Os 30 dias estão preparados. Capturando mais 30 dias anteriores para aquecer a análise sem usar informações futuras.",
    )
    if profile:
        history_days=60
        from aurelia_fx.historical.collector import collect_warmup
        warmup=collect_warmup(repository,capture,clock_id=history['clock_id'],days=60)
        check()
        if warmup['status']!='ready':raise ValueError('INSTRUMENT_WARMUP_HISTORY_NOT_READY')
        publish(research_profile=profile.as_dict(),profile_id=profile.fingerprint,
                warmup_history=dict(start=warmup['start'],as_of=warmup['as_of'],baseline_id=warmup['baseline_id']))
    from aurelia_fx.forecasting.config import load_config

    from aurelia_fx.agent_live import profile_config
    config = profile_config(load_config(),profile)
    if not config.enabled or config.revision == "main":
        raise ValueError(
            "Ative o Timestral com uma revisão imutável dos pesos antes de analisar."
        )
    from aurelia_fx.autonomous_lab import AutonomousLab
    from aurelia_fx.agent_live import run_paper
    mode=state.get('mode','paper')
    policy=AutonomousLab(config.fingerprint,execution_mode=mode,profile=profile)
    if config.local_release:
        # Adaptive weights do not change the user's existing demo/account/lot authority.
        from aurelia_fx.training.releases import resolve
        resolve(ROOT,config.local_release,config.local_artifact_sha256)
        if mode=='demo' and state.get('demo_authorization'):
            policy.protocol_id=state['demo_authorization']['protocol_id']
        elif mode=='paper':
            from aurelia_fx.agent_live import checkpoint
            prior=checkpoint(control,session_id)
            if prior and prior.get('research_mode'):policy.protocol_id=prior['model_id']
    if mode=='demo':
        from aurelia_fx.demo_terminal import demo_terminal
        from aurelia_fx.agent_model import fingerprint
        expected_account=(state.get('demo_authorization') or {}).get('account_id')
        if profile and not expected_account:
            expected_account=(OperationControl(control.memory).status().get('demo_authorization') or {}).get('account_id')
        with demo_terminal(clock_id=history['clock_id'],**(dict(profile=profile,account_id=expected_account) if profile else {})) as terminal:
            terminal.check_account()
            authorization=dict(scope='autonomous_demo_research',real_orders=False,
                account_id=terminal.account_id,session_id=session_id,lot=state['lot'],
                clock_id=history['clock_id'],protocol_id=policy.protocol_id)
            if profile:authorization.update(symbol=symbol,research_profile=profile.as_dict(),profile_id=profile.fingerprint)
            authorization['authorization_id']=fingerprint(authorization)
        old=state.get('demo_authorization')
        if old and old!=authorization:
            raise ValueError('A conta demo ou a fonte mudou; autorização anterior preservada.')
        repository.memory.record_project_data('agent_demo_authorization',authorization['authorization_id'],authorization)
        publish(demo_authorization=authorization)
    publish(
        state="ANALYSIS_WARMUP",stage="analysis",
        training=dict(status="autonomous_research",active_version=None,
                      samples=None,partitions=None,validation=None,final=None,
                      candidate_version=None,report_id=None,final_accessed=False,
                      protocol_id=policy.protocol_id,reason=None,message="Pesquisa simulada autônoma: hipóteses são selecionadas, executadas e revistas pelo agente. Não há aprovação manual por hipótese."),
        message="Preparando o laboratório autônomo e a memória histórica do ativo.",
    )
    run_paper(control,repository,control.status(),None,fetch,config,worker_id,stop,lease,
              research_policy=policy)
    return


if __name__ == "__main__":
    raise SystemExit(main())
