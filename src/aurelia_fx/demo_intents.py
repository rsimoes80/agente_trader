"""Durable demo intent protocol. This module cannot call a broker or approve a model.

SENDING is committed before the caller may invoke order_send. An uncertain send
stays unresolved; absence from a later positions query is not proof of rejection.
"""

from __future__ import annotations

import copy
import json
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .agent_model import fingerprint

DEMO_LOCK = 70616040
PENDING = frozenset({"PREPARED", "SENDING", "UNCERTAIN", "PARTIAL", "UNPROTECTED"})
TRANSITIONS = {
    "PREPARED": {"SENDING", "CANCELLED"},
    "SENDING": {"CONFIRMED", "REJECTED", "UNCERTAIN", "PARTIAL", "UNPROTECTED"},
    "UNCERTAIN": {"CONFIRMED", "PARTIAL", "UNPROTECTED"},
    "PARTIAL": {"CONFIRMED", "PARTIAL", "UNCERTAIN", "UNPROTECTED"},
    "UNPROTECTED": {"CONFIRMED", "CLOSED"},
    "CONFIRMED": {"UNPROTECTED", "PARTIAL", "CLOSED"},
}
OWNER_FIELDS = ("account_id", "approval_id", "model_id", "session_id", "clock_id")


class DemoIntentJournal:
    def __init__(self, memory, *, now=None):
        self.memory = memory
        self.now = now or (lambda: datetime.now(timezone.utc))

    @contextmanager
    def locked(self):
        with self.memory.pool.connection() as connection:
            # A transaction wrapping the whole broker call would roll back the
            # send marker after an exception and allow an unsafe duplicate.
            if not connection.autocommit or connection.info.transaction_status != 0:
                raise ValueError("O journal demo exige conexão independente em autocommit.")
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(hashtext(current_schema()),%s) AS acquired", (DEMO_LOCK,)
            ).fetchone()["acquired"]
            if not acquired:
                raise RuntimeError("Outra reconciliação demo está em andamento.")
            scope = IntentScope(self, connection)
            try:
                yield scope
            finally:
                scope.active = False
                if not connection.closed:
                    connection.execute("SELECT pg_advisory_unlock(hashtext(current_schema()),%s)", (DEMO_LOCK,))


class IntentScope:
    def __init__(self, journal, connection):
        self.journal, self.connection = journal, connection
        self.active = True

    def _check(self):
        if not self.active:
            raise RuntimeError("O lock da execução demo já foi liberado.")

    def latest(self, client_id):
        self._check()
        row = self.connection.execute("""SELECT payload_json,payload_sha256
            FROM project_records WHERE record_type='agent_demo_intent' AND record_key=%s
            ORDER BY (payload_json::jsonb ->> 'sequence')::bigint DESC LIMIT 1""", (client_id,)).fetchone()
        if not row:
            return None
        value = json.loads(row["payload_json"])
        if value.get("client_id") != client_id or self.journal.memory._encode(value)[1] != row["payload_sha256"]:
            raise ValueError("Journal demo inconsistente; execução bloqueada.")
        return value

    def for_account(self, account_id):
        self._check()
        rows = self.connection.execute("""SELECT payload_json,payload_sha256 FROM (
            SELECT DISTINCT ON (record_key) record_key,payload_json,payload_sha256,recorded_at
            FROM project_records WHERE record_type='agent_demo_intent'
            AND payload_json::jsonb #>> '{owner,account_id}'=%s
            ORDER BY record_key,(payload_json::jsonb ->> 'sequence')::bigint DESC) intents""", (account_id,)).fetchall()
        result = []
        for row in rows:
            data = json.loads(row["payload_json"])
            if self.journal.memory._encode(data)[1] != row["payload_sha256"]:
                raise ValueError("Journal demo inconsistente; execução bloqueada.")
            result.append(data)
        return result

    def pending(self, account_id):
        return [data for data in self.for_account(account_id) if data["status"] in PENDING]

    def _append(self, value):
        self._check()
        text, digest = self.journal.memory._encode(value)
        self.connection.execute("""INSERT INTO project_records
            (record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('agent_demo_intent',%s,%s,%s,clock_timestamp())""",
            (value["client_id"],text,digest))
        return copy.deepcopy(value)

    def prepare(self, client_id, request, owner, *, risk_reduction_for=None):
        if not re.fullmatch(r"[a-f0-9]{32}", client_id):
            raise ValueError("Identificador de intenção demo inválido.")
        if set(owner) != set(OWNER_FIELDS) or not all(
            isinstance(owner[k],str) and owner[k] for k in OWNER_FIELDS
        ):
            raise ValueError("A intenção exige conta, aprovação, modelo, sessão e fonte.")
        if not isinstance(request,dict) or not request:
            raise ValueError("Pedido demo congelado ausente.")
        request_hash = fingerprint(dict(request=request,owner=owner,risk_reduction_for=risk_reduction_for))
        previous = self.latest(client_id)
        if previous:
            if previous["request_hash"] != request_hash:
                raise ValueError("Identificador já usado para outro pedido ou autorização.")
            return previous
        pending = self.pending(owner["account_id"])
        if risk_reduction_for:
            exposure = self.latest(risk_reduction_for)
            ticket = request.get("position")
            if not exposure or exposure["status"] not in {"UNPROTECTED","PARTIAL","CONFIRMED"} or (
                exposure["owner"] != owner
                or not isinstance(ticket,int) or isinstance(ticket,bool) or ticket <= 0
                or ticket not in exposure.get("evidence",{}).get("position_tickets",[])
            ):
                raise ValueError("Redução de risco sem posição reconciliada e identificada.")
            # Closing a positively identified ticket reduces known exposure even
            # when another instrument has an unresolved send. An uncertain close
            # for this same ticket still forbids a second closing request.
            pending = [p for p in pending if p["client_id"] != risk_reduction_for
                       and p['request'].get('position')==ticket]
        if pending:
            raise ValueError("Há intenção demo sem reconciliação; nova entrada bloqueada.")
        now = self.journal.now().isoformat()
        return self._append(dict(
            client_id=client_id,request=copy.deepcopy(request),owner=dict(owner),
            request_hash=request_hash,status="PREPARED",sequence=1,
            created_at=now,updated_at=now,mode="demo_only",
            risk_reduction_for=risk_reduction_for,
        ))

    def transition(self, client_id, target, *, evidence=None):
        if target == "SENDING":
            raise ValueError("Use begin_send para verificar o prazo do pedido.")
        return self._transition(client_id,target,evidence=evidence)

    def _transition(self, client_id, target, *, evidence=None):
        previous = self.latest(client_id)
        if not previous or target not in TRANSITIONS.get(previous["status"],set()):
            raise ValueError("Transição demo inválida; o pedido não será reenviado.")
        return self._append({
            **previous,"status":target,"sequence":previous["sequence"]+1,
            "updated_at":self.journal.now().isoformat(),
            "previous_hash":self.journal.memory._encode(previous)[1],
            "evidence":copy.deepcopy(evidence or {}),
        })

    def begin_send(self, client_id):
        previous = self.latest(client_id)
        if not previous or previous["status"] != "PREPARED":
            raise ValueError("A intenção já foi enviada ou encerrada; não reenviar.")
        age = self.journal.now()-datetime.fromisoformat(previous["created_at"])
        if not timedelta(0) <= age <= timedelta(seconds=5):
            self.transition(client_id,"CANCELLED",evidence=dict(reason="STALE_PREPARED_REQUEST"))
            raise ValueError("Pedido preparado expirou; nenhuma ordem deve ser enviada.")
        # This INSERT is a separate committed statement under autocommit.
        return self._transition(client_id,"SENDING")
