"""Audited observation sessions. This controller has no execution gateway."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from .historical.core import readiness, utc
from .replay_strategy import STRATEGY_ID, STRATEGY_VERSION
from .source_clock import validate_source_clock

ACTIVE = {"RUNNING", "PAUSED", "PAUSED_BY_DATA", "RECOVERY_REQUIRED"}


def preflight(observer, baseline, *, disk_free, now=None):
    now = now or datetime.now(timezone.utc)
    checked = observer.get("checked_at")
    try:
        fresh = checked is not None and 0 <= (now - utc(checked)).total_seconds() <= 90
    except (ValueError, TypeError):
        fresh = False
    try:
        validate_source_clock(
            dict(
                timestamp_semantics="utc_v1",
                source_clock=observer.get("source_clock", {}),
            ),
            now,
        )
        source_recent = True
    except (RuntimeError, ValueError, TypeError):
        source_recent = False
    history_block = readiness(
        baseline,
        as_of=now,
        clock_id=(observer.get("source_clock") or {}).get("clock_id"),
    )
    checks = [
        dict(
            name="observer",
            passed=observer.get("status") == "observing" and fresh and source_recent,
            reason="SOURCE_OR_OBSERVER_NOT_READY",
        ),
        dict(
            name="monthly_history", passed=history_block is None, reason=history_block
        ),
        dict(name="disk", passed=disk_free >= 256 * 1024**2, reason="DISK_SPACE_LOW"),
    ]
    return dict(
        mode="observe_only",
        ready=all(c["passed"] for c in checks),
        checks=checks,
        strategy_id=STRATEGY_ID,
        strategy_version=STRATEGY_VERSION,
        orders_enabled=False,
        external_llm_required=False,
        model_policy="Timestral optional evidence; no model authorizes execution.",
        baseline_id=baseline.get("baseline_id") if baseline else None,
        source_clock_id=(observer.get("source_clock") or {}).get("clock_id"),
        disk_free_bytes=disk_free,
        checked_at=now.isoformat(),
    )


class ObservationController:
    def __init__(self, memory, check):
        self.memory, self.check = memory, check
        self.boot_id = str(uuid4())

    @staticmethod
    def _latest(connection):
        row = connection.execute("""SELECT payload_json FROM project_records
            WHERE record_type='observation_session_event' ORDER BY recorded_at DESC LIMIT 1""").fetchone()
        return (
            json.loads(row["payload_json"])
            if row
            else dict(state="STOPPED", session_id=None, sequence=0)
        )

    def _append(self, connection, event):
        text, digest = self.memory._encode(event)
        connection.execute(
            """INSERT INTO project_records
            (record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('observation_session_event',%s,%s,%s,clock_timestamp())""",
            (f"{event['session_id']}:{event['sequence']:08d}", text, digest),
        )

    def _event(
        self, c, state, after, *, actor, reason, correlation_id, origin, checks=None
    ):
        event = {
            **state,
            "previous_state": state["state"],
            "state": after,
            "sequence": state["sequence"] + 1,
            "actor": actor,
            "reason": reason,
            "correlation_id": correlation_id,
            "origin": origin,
            "owner_boot": self.boot_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "mode": "observe_only",
            "orders_enabled": False,
            "preflight": checks if checks is not None else state.get("preflight"),
        }
        self._append(c, event)
        return event

    def status(self):
        with self.memory.pool.connection() as c:
            state = self._latest(c)
        return {
            **state,
            "mode": "observe_only",
            "orders_enabled": False,
            "automatic_collection_independent": True,
        }

    def recover(self):
        with self.memory.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(70616024)")
            state = self._latest(c)
            if state["state"] in ACTIVE and state.get("owner_boot") != self.boot_id:
                self._event(
                    c,
                    state,
                    "RECOVERY_REQUIRED",
                    actor="service",
                    reason="BACKEND_RESTARTED",
                    correlation_id=str(uuid4()),
                    origin="startup",
                )

    def command(self, payload, key, *, origin):
        action = str(payload.get("action", "")).upper()
        if action not in {
            "START",
            "PAUSE",
            "RESUME",
            "STOP",
            "EMERGENCY_STOP",
            "RESET",
        }:
            raise ValueError("Comando de sessão inválido.")
        if payload.get("mode", "observe_only") != "observe_only":
            raise ValueError(
                "Este build permite somente sessões de observação; execução não implementada."
            )
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", key):
            raise ValueError("Idempotency-Key obrigatório: 16 a 128 caracteres.")
        actor = str(payload.get("actor", "")).strip()
        reason = str(payload.get("reason", "")).strip()
        if not 1 <= len(actor) <= 80 or not 1 <= len(reason) <= 500:
            raise ValueError("Informe operador e justificativa da ação.")
        canonical = dict(action=action, actor=actor, reason=reason, mode="observe_only")
        fingerprint = hashlib.sha256(
            json.dumps(canonical, sort_keys=True).encode()
        ).hexdigest()
        checked = self.check() if action in {"START", "RESUME"} else None
        with self.memory.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(70616024)")
            old = c.execute(
                "SELECT payload_json FROM project_records WHERE record_type='observation_session_command' AND record_key=%s",
                (key,),
            ).fetchone()
            if old:
                record = json.loads(old["payload_json"])
                if record["fingerprint"] != fingerprint:
                    raise ValueError("Idempotency-Key já utilizado com outro comando.")
                return record["response"]
            state = self._latest(c)
            correlation = str(uuid4())
            if action == "START":
                if state["state"] == "EMERGENCY_STOP":
                    raise ValueError(
                        "Emergência permanece ativa. Verifique e rearme a sessão primeiro."
                    )
                if state["state"] not in ACTIVE:
                    state = dict(state="STOPPED", session_id=str(uuid4()), sequence=0)
                    state = self._event(
                        c,
                        state,
                        "CHECKING_PREREQUISITES",
                        actor=actor,
                        reason=reason,
                        correlation_id=correlation,
                        origin=origin,
                    )
                    check = checked
                    state = self._event(
                        c,
                        state,
                        "RUNNING" if check["ready"] else "ERROR",
                        actor=actor,
                        reason=reason if check["ready"] else "PREREQUISITES_FAILED",
                        correlation_id=correlation,
                        origin=origin,
                        checks=check,
                    )
            elif action == "RESUME":
                if state["state"] not in {
                    "PAUSED",
                    "PAUSED_BY_DATA",
                    "RECOVERY_REQUIRED",
                }:
                    raise ValueError("A sessão não está pausada.")
                check = checked
                state = self._event(
                    c,
                    state,
                    "RUNNING" if check["ready"] else "PAUSED_BY_DATA",
                    actor=actor,
                    reason=reason if check["ready"] else "PREREQUISITES_FAILED",
                    correlation_id=correlation,
                    origin=origin,
                    checks=check,
                )
            else:
                target = {
                    "PAUSE": "PAUSED",
                    "STOP": "STOPPED",
                    "EMERGENCY_STOP": "EMERGENCY_STOP",
                    "RESET": "STOPPED",
                }[action]
                if action == "RESET" and state["state"] != "EMERGENCY_STOP":
                    raise ValueError("Não há emergência para rearmar.")
                if action == "PAUSE" and state["state"] != "RUNNING":
                    raise ValueError(
                        "Somente uma sessão em observação pode ser pausada."
                    )
                if action == "STOP" and state["state"] == "EMERGENCY_STOP":
                    raise ValueError("Use rearmar para reconhecer a emergência.")
                if state.get("session_id") is None:
                    state = {**state, "session_id": str(uuid4())}
                if state["state"] != target:
                    state = self._event(
                        c,
                        state,
                        target,
                        actor=actor,
                        reason=reason,
                        correlation_id=correlation,
                        origin=origin,
                    )
            response = dict(
                session_id=state.get("session_id"),
                state=state["state"],
                mode="observe_only",
                orders_enabled=False,
            )
            record = dict(
                fingerprint=fingerprint,
                response=response,
                request=canonical,
                correlation_id=correlation,
                origin=origin,
            )
            text, digest = self.memory._encode(record)
            c.execute(
                """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
                VALUES('observation_session_command',%s,%s,%s)""",
                (key, text, digest),
            )
            return response

    def pause_on_failure(self, reason):
        with self.memory.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(70616024)")
            state = self._latest(c)
            if state["state"] == "RUNNING":
                self._event(
                    c,
                    state,
                    "PAUSED_BY_DATA",
                    actor="observer",
                    reason=reason,
                    correlation_id=str(uuid4()),
                    origin="observer",
                )

    def observation_reference(self, as_of=None):
        state = self.status()
        if state["state"] != "RUNNING" or (
            as_of is not None and utc(as_of) < utc(state["at"])
        ):
            return None
        return dict(session_id=state["session_id"], sequence=state["sequence"])
