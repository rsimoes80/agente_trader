"""Durable product commands and worker state in the existing PostgreSQL journal."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

LOCK = 70616031
WORKER_LOCK = 70616032
TERMINAL = {
    "STOPPED",
    "ERROR",
    "INSUFFICIENT_DATA",
    "TRAINING_UNAVAILABLE",
    "TRAINING_BLOCKED",
}


def validate_lot(value, contract=None):
    try:
        lot = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("Informe um lote numérico válido.") from None
    if not lot.is_finite() or lot <= 0 or lot > 100:
        raise ValueError("O lote deve ser positivo e não pode exceder 100.")
    if contract:
        minimum, maximum, step = (
            Decimal(str(contract[k]))
            for k in ("volume_min", "volume_max", "volume_step")
        )
        if not all(v.is_finite() and v > 0 for v in (minimum, maximum, step)):
            raise ValueError("Contrato de lote do MT5 inválido.")
        if not minimum <= lot <= maximum or (lot - minimum) % step:
            raise ValueError(
                f"O ativo aceita lote de {minimum} a {maximum}, em passos de {step}."
            )
    return str(lot.normalize())


class OperationControl:
    def __init__(self, memory):
        self.memory = memory

    @staticmethod
    def latest(connection):
        row = connection.execute("""SELECT payload_json FROM project_records
            WHERE record_type='agent_operation_state' ORDER BY recorded_at DESC LIMIT 1""").fetchone()
        return (
            json.loads(row["payload_json"])
            if row
            else dict(
                session_id=None,
                state="STOPPED",
                desired="stopped",
                sequence=0,
                message="Escolha o lote e clique em Iniciar agente.",
                mode="paper",
                orders_enabled=False,
            )
        )

    def append(self, connection, state):
        state = {
            **state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "orders_enabled": state.get("mode")=="demo" and bool(state.get("demo_authorization")),
        }
        text, digest = self.memory._encode(state)
        connection.execute(
            """INSERT INTO project_records
            (record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('agent_operation_state',%s,%s,%s,clock_timestamp())""",
            (str(uuid4()), text, digest),
        )
        return state

    def status(self):
        with self.memory.pool.connection() as c:
            return self.latest(c)


    def command(self, payload, key, *, actor):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", key):
            raise ValueError("Identificador de comando inválido. Atualize a página.")
        action = payload.get("action")
        if action not in {"START", "PAUSE", "RESUME", "STOP"}:
            raise ValueError("Comando inválido.")
        mode=payload.get("mode", "paper")
        if mode not in {"paper","demo"}:
            raise ValueError(
                "Esta versão permite apenas simulação. Demo e conta real não estão habilitadas."
            )
        lot = validate_lot(payload.get("lot")) if action == "START" else None
        request = dict(action=action, lot=lot, mode=mode, actor=actor)
        fingerprint = hashlib.sha256(
            json.dumps(request, sort_keys=True).encode()
        ).hexdigest()
        with self.memory.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            old = c.execute(
                """SELECT payload_json FROM project_records
                WHERE record_type='agent_operation_command' AND record_key=%s LIMIT 1""",
                (key,),
            ).fetchone()
            if old:
                cached = json.loads(old["payload_json"])
                if cached["fingerprint"] != fingerprint:
                    raise ValueError(
                        "Este identificador já foi usado para outro comando."
                    )
                return cached["response"]
            state = self.latest(c)
            if action == "START":
                unresolved=c.execute("""SELECT 1 FROM (
                    SELECT DISTINCT ON (record_key) record_key,payload_json::jsonb AS p
                    FROM project_records WHERE record_type='agent_demo_intent'
                    ORDER BY record_key,(payload_json::jsonb ->> 'sequence')::bigint DESC
                    ) latest WHERE NOT (p #> '{request,broker}' ? 'position')
                    AND (p->>'status' NOT IN ('CLOSED','REJECTED','CANCELLED')
                    OR (p->>'status'='CLOSED' AND NOT EXISTS (
                        SELECT 1 FROM project_records applied WHERE applied.record_type='agent_demo_applied'
                        AND applied.record_key=latest.record_key||':closed'))) LIMIT 1""").fetchone()
                if unresolved:
                    raise ValueError('Há uma execução demo pendente de reconciliação. Retome a sessão existente.')
                if state.get("position") or state.get("pending_execution"):
                    raise ValueError(
                        "Existe uma posição em acompanhamento. Resolva a sessão atual antes de iniciar outra."
                    )
                if state["state"] not in TERMINAL:
                    if state.get("lot") != lot or state.get('mode','paper')!=mode:
                        raise ValueError(
                            "Encerre a sessão atual antes de alterar o lote."
                        )
                else:
                    state = self.append(
                        c,
                        dict(
                            session_id=str(uuid4()),
                            state="QUEUED",
                            desired="running",
                            sequence=1,
                            generation=1,
                            mode=mode,
                            execution_profile="autonomous_"+mode,
                            lot=lot,
                            symbol="EURUSD",
                            timeframe="M5",
                            actor=actor,
                            created_at=datetime.now(timezone.utc).isoformat(),
                            message="Início solicitado. Aguardando o serviço do agente no Windows.",
                            stage="connection",
                            history=None,
                            training=None,
                            last_decision=None,
                            position=None,
                        ),
                    )
            else:
                if not state.get("session_id") or state["state"] in TERMINAL:
                    raise ValueError("Não há sessão ativa para este comando.")
                if action == "RESUME" and state["desired"] != "paused":
                    raise ValueError("O agente não está pausado.")
                desired, target, message = {
                    "PAUSE": (
                        "paused",
                        "PAUSE_REQUESTED",
                        "Pausa solicitada. Aguardando confirmação do agente.",
                    ),
                    "RESUME": (
                        "running",
                        "QUEUED",
                        "Retomada solicitada. Os dados serão verificados novamente.",
                    ),
                    "STOP": (
                        "stopped",
                        "STOP_REQUESTED",
                        "Parada solicitada. Aguardando confirmação do agente.",
                    ),
                }[action]
                if state["desired"] != desired:
                    state = self.append(
                        c,
                        {
                            **state,
                            "sequence": state["sequence"] + 1,
                            "generation": state.get("generation", 1)
                            + (1 if action == "RESUME" else 0),
                            "desired": desired,
                            "state": target,
                            "message": message,
                            "actor": actor,
                        },
                    )
            record = dict(request=request, fingerprint=fingerprint, response=state)
            text, digest = self.memory._encode(record)
            c.execute(
                """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
                VALUES('agent_operation_command',%s,%s,%s)""",
                (key, text, digest),
            )
            return state

    def publish(
        self,
        session_id,
        *,
        expected_desired="running",
        expected_generation=None,
        **changes,
    ):
        with self.memory.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            state = self.latest(c)
            if (
                state.get("session_id") != session_id
                or state["desired"] != expected_desired
                or (
                    expected_generation is not None
                    and state.get("generation") != expected_generation
                )
            ):
                return None
            if isinstance(changes.get("training"), dict):
                changes["training"] = {
                    **(state.get("training") or {}),
                    **changes["training"],
                }
            return self.append(
                c, {**state, **changes, "sequence": state["sequence"] + 1}
            )

    def heartbeat(self, worker_id):
        import psutil
        self.memory.record_project_data(
            "agent_worker_heartbeat",
            worker_id,
            dict(
                worker_id=worker_id,
                at=datetime.now(timezone.utc).isoformat(),
                pid=os.getpid(),host=socket.gethostname(),
                process_created_at=psutil.Process().create_time(),
                mode="paper",
            ),
        )
        if os.environ.get('AURELIA_AGENT_SUPERVISED')=='1':
            print('AFX_AGENT_PROGRESS:'+worker_id,flush=True)

    def worker_status(self):
        with self.memory.pool.connection() as c:
            row = c.execute("""SELECT payload_json,
                EXTRACT(EPOCH FROM (clock_timestamp()-recorded_at)) AS heartbeat_age_seconds
                FROM project_records
                WHERE record_type='agent_worker_heartbeat' ORDER BY recorded_at DESC LIMIT 1""").fetchone()
        data = json.loads(row["payload_json"]) if row else None
        # Liveness is measured on receipt by the database, on one clock. A host
        # clock difference must not hide a worker that is actively checking in.
        age = float(row['heartbeat_age_seconds']) if row and row['heartbeat_age_seconds'] is not None else None
        return dict(available=age is not None and 0 <= age < 180, heartbeat=data,
                    heartbeat_age_seconds=age,age_basis='postgres_received_at')
