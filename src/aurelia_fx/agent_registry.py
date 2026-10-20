"""Explicit, bounded paper approvals. A training result cannot promote itself."""

import json
from datetime import datetime, timedelta, timezone

from .agent_model import PROTOCOL, fingerprint
from .agent_strategy import FEATURES, SPEC_HASH
from .agent_validation import economic_gate


def load_record(connection, kind, key):
    row = connection.execute(
        """SELECT payload_json FROM project_records
        WHERE record_type=%s AND record_key=%s ORDER BY recorded_at DESC LIMIT 1""",
        (kind, key),
    ).fetchone()
    if row is None:
        raise ValueError("Registro de modelo ou validação não encontrado.")
    return json.loads(row["payload_json"])


def checked_candidate(connection, report):
    if report.get("report_id") != fingerprint(
        {k: v for k, v in report.items() if k != "report_id"}
    ):
        raise ValueError("Relatório de validação inconsistente.")
    final = report.get("final", {})
    age = datetime.now(timezone.utc) - datetime.fromisoformat(
        report["training_period"]["end"]
    )
    if age < timedelta(seconds=-60) or age > timedelta(days=7):
        raise ValueError(
            "A validação está desatualizada. Prepare uma nova versão com dados recentes."
        )
    combined = final.get("combined", {})
    validation = report.get("validation", {})
    selection = next(
        (
            r["result"]
            for r in validation.get("thresholds", [])
            if r["threshold"] == report.get("threshold")
        ),
        None,
    )
    sufficient = all(
        report.get("partitions", {}).get(phase, 0) >= PROTOCOL[minimum]
        for phase, minimum in (
            ("development", "minimum_development"),
            ("validation", "minimum_validation"),
            ("final", "minimum_final"),
        )
    )
    if (
        report.get("status") != "validated_pending_approval"
        or report.get("spec_hash") != SPEC_HASH
        or report.get("protocol") != PROTOCOL
        or not report.get("final_accessed")
        or not sufficient
        or len(report.get("walk_forward", [])) < 2
        or report.get("threshold") not in PROTOCOL["probability_thresholds"]
        or selection is None
        or not economic_gate(selection, PROTOCOL["minimum_trades_validation"])
        or validation.get("probability", {}).get("brier_improvement", -1)
        < PROTOCOL["required_brier_improvement"]
        or not economic_gate(combined, PROTOCOL["minimum_trades_final"])
        or combined["net_pnl"]
        <= max(final["technical"]["net_pnl"] or 0, final["timestral"]["net_pnl"] or 0)
        or final.get("probability", {}).get("brier_improvement", -1)
        < PROTOCOL["required_brier_improvement"]
    ):
        raise ValueError(
            "Esta versão não atende ao contrato atual de aprovação para simulação."
        )
    model = load_record(
        connection, "agent_model_candidate", report["candidate_version"]
    )
    if (
        model.get("model_id")
        != fingerprint({k: v for k, v in model.items() if k != "model_id"})
        or model.get("spec_hash") != SPEC_HASH
        or model.get("feature_schema") != list(FEATURES)
    ):
        raise ValueError("Modelo incompatível ou inconsistente.")
    return model


def approve(connection, memory, state, report_id, actor):
    if (
        state["state"] != "AWAITING_APPROVAL"
        or (state.get("training") or {}).get("report_id") != report_id
    ):
        raise ValueError("Selecione a versão validada apresentada nesta sessão.")
    report = load_record(connection, "agent_training_report", report_id)
    checked_candidate(connection, report)
    if report.get("lot") != state["lot"] or report.get("clock_id") != (
        state.get("history") or {}
    ).get("clock_id"):
        raise ValueError("A versão não corresponde ao lote e à fonte desta sessão.")
    now = datetime.now(timezone.utc)
    record = dict(
        approval_id=fingerprint(
            dict(report_id=report_id, actor=actor, at=now.isoformat())
        ),
        report_id=report_id,
        model_id=report["candidate_version"],
        spec_hash=SPEC_HASH,
        lot=state["lot"],
        clock_id=report["clock_id"],
        model_configuration=report["model_configuration"],
        approved_at=now.isoformat(),
        valid_until=(now + timedelta(days=7)).isoformat(),
        actor=actor,
        scope="paper_only",
        live_trading=False,
        session_id=state["session_id"],
    )
    text, digest = memory._encode(record)
    connection.execute(
        """INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256)
        VALUES('agent_paper_approval',%s,%s,%s)""",
        (record["approval_id"], text, digest),
    )
    return record


def approved_version(memory, *, lot, clock_id, configuration):
    with memory.pool.connection() as c:
        rows = c.execute(
            """SELECT payload_json FROM project_records
            WHERE record_type='agent_paper_approval' AND payload_json::jsonb ->> 'lot'=%s
            AND payload_json::jsonb ->> 'clock_id'=%s AND payload_json::jsonb ->> 'spec_hash'=%s
            AND payload_json::jsonb ->> 'model_configuration'=%s ORDER BY recorded_at DESC LIMIT 20""",
            (lot, clock_id, SPEC_HASH, configuration),
        ).fetchall()
        for row in rows:
            approval = json.loads(row["payload_json"])
            if approval.get("scope") != "paper_only" or datetime.fromisoformat(
                approval["valid_until"]
            ) <= datetime.now(timezone.utc):
                continue
            report = load_record(c, "agent_training_report", approval["report_id"])
            model = checked_candidate(c, report)
            if approval["model_id"] != model["model_id"]:
                raise ValueError("A aprovação não corresponde ao modelo validado.")
            return dict(approval=approval, report=report, model=model)
    return None
