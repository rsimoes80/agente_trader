"""Bounded diagnostic queries and append-only human annotations."""

import json
from datetime import datetime, timezone
from uuid import uuid4


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def stage(reason):
    if reason.startswith(("REGIME_", "RANGE_", "BREAKOUT_", "TRANSITION_")):
        return "regime"
    if reason.startswith(("INVALID_", "EVIDENCE_INVALIDATED")):
        return "dados"
    if reason.startswith("SESSION_"):
        return "sessão"
    if reason.startswith(("TREND_", "DIRECTION_", "COUNTERTREND_", "TARGET_")):
        return "contexto"
    if reason.startswith("EVIDENCE_"):
        return "evidências"
    if reason.startswith(("RISK_", "EXECUTION_")):
        return "risco"
    if reason.startswith(("EXPECTATION_", "WAITING_FOR_TRIGGER")):
        return "confirmação / gatilho"
    return "observação / hipótese"


class DiagnosticsRepository:
    def __init__(self, memory):
        self.memory = memory

    def query(self, sql, args=()):
        with self.memory.pool.connection() as connection:
            return connection.execute(sql, args).fetchall()

    def runs(self):
        rows = self.query("""SELECT artifact_id,status,created_at_utc,payload_json FROM experiment_artifacts
            WHERE status IN ('completed','observer_started','temporal_validation_completed')
            ORDER BY created_at_utc DESC LIMIT 250""")
        partitions = {}
        for row in rows:
            payload = decode(row["payload_json"])
            if row["status"] == "temporal_validation_completed":
                partitions.update(
                    {run: phase for phase, run in payload.get("runs", {}).items()}
                )
        result = []
        for row in rows:
            payload = decode(row["payload_json"])
            run = payload.get("run_id")
            if not run or payload.get("schema_version", 0) < 4:
                continue
            result.append(
                {
                    "run_id": run,
                    "created_at": row["created_at_utc"],
                    "source": payload.get("data_source", ""),
                    "timeframe": payload.get("config", {}).get("timeframe", "M5"),
                    "partition": partitions.get(
                        run,
                        "live" if row["status"] == "observer_started" else "unassigned",
                    ),
                    "model_version": payload.get("regime_model_version", ""),
                    "bars": payload.get("bars"),
                    "config_hash": payload.get("config_hash", ""),
                    "utc_normalized": payload.get("source_clock", {}).get("contract")
                    == "mt5-utc-v1",
                }
            )
        return result

    def manifest(self, run_id):
        rows = self.query(
            """SELECT payload_json FROM experiment_artifacts
            WHERE payload_json::jsonb ->> 'run_id'=%s
            AND status IN ('completed','observer_started') ORDER BY created_at_utc DESC LIMIT 1""",
            (run_id,),
        )
        if not rows:
            raise ValueError("Execução não encontrada.")
        return decode(rows[0]["payload_json"])

    @staticmethod
    def where(filters):
        if not filters.get("run_id") or len(filters["run_id"]) > 128:
            raise ValueError("Selecione uma execução.")
        parts = ["d.run_id=%s"]
        args = [filters["run_id"]]
        for name, column in (
            ("regime", "s.payload_json::jsonb ->> 'regime'"),
            ("session", "d.session"),
            ("timeframe", "d.payload_json::jsonb ->> 'timeframe'"),
            ("reason", "d.reason_code"),
        ):
            value = filters.get(name)
            if value:
                if len(value) > 128:
                    raise ValueError("Filtro inválido.")
                parts.append(column + "=%s")
                args.append(value)
        for name, op in (("from", ">="), ("to", "<=")):
            if filters.get(name):
                value = datetime.fromisoformat(filters[name].replace("Z", "+00:00"))
                if value.tzinfo is None:
                    raise ValueError("Datas precisam de timezone.")
                parts.append("d.created_at_utc" + op + "%s")
                args.append(value.astimezone(timezone.utc).isoformat())
        return " AND ".join(parts), args

    def audit(self, filters):
        where, args = self.where(filters)
        rows = self.query(
            """SELECT s.payload_json::jsonb ->> 'regime' AS regime,
            s.payload_json::jsonb -> 'regime_state' ->> 'timeframe' AS regime_timeframe,
            d.payload_json::jsonb ->> 'timeframe' AS timeframe,d.session,d.reason_code,d.action,
            s.payload_json::jsonb -> 'regime_state' ->> 'classification_status' AS classification_status,
            s.payload_json::jsonb -> 'regime_state' -> 'missing_data' AS missing_data,
            count(*) AS count FROM decisions d JOIN market_snapshots s
            ON d.payload_json::jsonb ->> 'snapshot_id'=s.snapshot_id WHERE """
            + where
            + """
            GROUP BY 1,2,3,4,5,6,7,8 ORDER BY count(*) DESC""",
            args,
        )
        for row in rows:
            row["stage"] = stage(row["reason_code"])
        return {
            "groups": rows,
            "total": sum(r["count"] for r in rows),
            "signals": sum(
                r["count"] for r in rows if r["action"] == "HYPOTHETICAL_SIGNAL"
            ),
            "scope": "one_run_no_cross_run_deduplication_needed",
            "human_review": self.review_summary(where, args),
        }

    def review_summary(self, where, args):
        rows = self.query(
            """WITH latest AS (
            SELECT DISTINCT ON (lower(trim(payload_json::jsonb ->> 'reviewer')),payload_json::jsonb ->> 'snapshot_id')
                payload_json::jsonb AS review FROM project_records WHERE record_type='human_regime_review'
            ORDER BY lower(trim(payload_json::jsonb ->> 'reviewer')),payload_json::jsonb ->> 'snapshot_id',recorded_at DESC)
            SELECT r.review ->> 'label' AS human_regime,s.payload_json::jsonb ->> 'regime' AS model_regime,
                count(*) AS count,array_agg(DISTINCT s.snapshot_id) AS snapshot_ids
            FROM latest r JOIN decisions d ON r.review ->> 'decision_id'=d.decision_id
            JOIN market_snapshots s ON d.payload_json::jsonb ->> 'snapshot_id'=s.snapshot_id
            WHERE """
            + where
            + " GROUP BY 1,2",
            args,
        )
        snapshots = set()
        for row in rows:
            snapshots.update(row.pop("snapshot_ids"))
        total = sum(row["count"] for row in rows)
        matches = sum(
            row["count"] for row in rows if row["human_regime"] == row["model_regime"]
        )
        return {
            "judgments": total,
            "unique_snapshots": len(snapshots),
            "agreements": matches,
            "confusion": rows,
            "interpretation": "informed_agreement_not_independent_accuracy",
        }

    def samples(self, filters, offset=0):
        where, args = self.where(filters)
        offset = max(0, min(100000, int(offset)))
        rows = self.query(
            """SELECT d.decision_id,d.created_at_utc,d.session,d.reason_code,d.action,
            s.snapshot_id,s.payload_json::jsonb ->> 'regime' AS regime,
            s.payload_json::jsonb ->> 'regime_subtype' AS subtype,
            s.payload_json::jsonb -> 'regime_state' ->> 'timeframe' AS regime_timeframe,
            s.payload_json::jsonb -> 'regime_state' ->> 'classification_status' AS classification_status,
            s.payload_json::jsonb -> 'regime_state' -> 'missing_data' AS missing_data,
            s.payload_json::jsonb ->> 'evidence_status' AS evidence_status,
            d.payload_json::jsonb ->> 'timeframe' AS timeframe
            FROM decisions d JOIN market_snapshots s ON d.payload_json::jsonb ->> 'snapshot_id'=s.snapshot_id
            WHERE """
            + where
            + " ORDER BY d.created_at_utc DESC,d.decision_id DESC LIMIT 60 OFFSET %s",
            [*args, offset],
        )
        return {"rows": rows, "offset": offset, "page_size": 60}

    def detail(self, decision_id):
        rows = self.query(
            """SELECT d.payload_json AS decision,s.payload_json AS snapshot FROM decisions d
            JOIN market_snapshots s ON d.payload_json::jsonb ->> 'snapshot_id'=s.snapshot_id
            WHERE d.decision_id=%s""",
            (decision_id,),
        )
        if not rows:
            raise ValueError("Decisão não encontrada.")
        decision, snapshot = decode(rows[0]["decision"]), decode(rows[0]["snapshot"])
        manifest = self.manifest(decision["run_id"])
        source_filter = (
            "payload_json::jsonb ->> 'dataset_sha256'=%s"
            if manifest.get("dataset_sha256")
            else "payload_json::jsonb ->> 'source'=%s"
        )
        source_value = manifest.get("dataset_sha256") or "mt5_diagnostics_readonly"
        candles = self.query(
            """SELECT payload_json FROM project_records WHERE record_type='closed_candle'
            AND """
            + source_filter
            + """ AND payload_json::jsonb ->> 'symbol'=%s
            AND payload_json::jsonb ->> 'timeframe'=%s AND payload_json::jsonb ->> 'timestamp'<=%s
            ORDER BY payload_json::jsonb ->> 'timestamp' DESC LIMIT 200""",
            (
                source_value,
                decision["symbol"],
                decision["timeframe"],
                decision["data_timestamp_utc"],
            ),
        )
        data = list(reversed([decode(r["payload_json"]) for r in candles]))
        frozen = self.query(
            """SELECT payload_json FROM project_records WHERE record_type='diagnostic_chart_window'
            AND record_key=%s ORDER BY recorded_at DESC LIMIT 1""",
            (decision_id,),
        )
        if frozen:
            data = decode(frozen[0]["payload_json"])["candles"]
        reviews = self.query(
            """SELECT payload_json FROM project_records WHERE record_type='human_regime_review'
            AND payload_json::jsonb ->> 'snapshot_id'=%s ORDER BY recorded_at DESC LIMIT 20""",
            (snapshot["snapshot_id"],),
        )
        timeline = self.query(
            """SELECT d.payload_json::jsonb ->> 'data_timestamp_utc' AS timestamp,
            s.payload_json::jsonb ->> 'regime' AS regime FROM decisions d JOIN market_snapshots s
            ON d.payload_json::jsonb ->> 'snapshot_id'=s.snapshot_id
            WHERE d.run_id=%s AND d.created_at_utc<=%s ORDER BY d.created_at_utc DESC LIMIT 200""",
            (decision["run_id"], decision["created_at_utc"]),
        )
        return {
            "decision": decision,
            "snapshot": snapshot,
            "candles": data,
            "timeline": list(reversed(timeline)),
            "reviews": [decode(r["payload_json"]) for r in reviews],
            "chart_cutoff": decision["data_timestamp_utc"],
            "future_candles_included": False,
        }

    def review(self, payload):
        label = payload.get("label")
        reviewer = str(payload.get("reviewer", "")).strip()
        note = str(payload.get("note", "")).strip()
        if (
            label not in {"TREND", "RANGE", "TRANSITION", "UNKNOWN"}
            or not 1 <= len(reviewer) <= 80
            or len(note) > 2000
        ):
            raise ValueError(
                "Informe revisor, classificação válida e observação de até 2.000 caracteres."
            )
        detail = self.detail(str(payload.get("decision_id", "")))
        snapshot = detail["snapshot"]
        decision = detail["decision"]
        record = {
            "review_id": str(uuid4()),
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewer": reviewer,
            "label": label,
            "note": note,
            "decision_id": decision["decision_id"],
            "snapshot_id": snapshot["snapshot_id"],
            "run_id": decision["run_id"],
            "observed_regime": snapshot["regime"],
            "regime_timeframe": snapshot["regime_state"]["timeframe"],
            "regime_model_version": snapshot["regime_model_version"],
            "regime_config_hash": snapshot["regime_config_hash"],
            "data_timestamp_utc": decision["data_timestamp_utc"],
            "review_mode": "informed_retrospective",
            "training_authorized": False,
            "changes_classifier": False,
        }
        self.memory.record_project_data(
            "human_regime_review", record["review_id"], record
        )
        return record

    def research_candles(self, run_id):
        run = next((r for r in self.runs() if r["run_id"] == run_id), None)
        if not run or run["partition"] != "development":
            raise ValueError(
                "Comparações aceitam apenas partições seladas como desenvolvimento."
            )
        if not run.get("utc_normalized"):
            raise ValueError(
                "Horário legado sem validação UTC. Recapture os candles antes de comparar parâmetros."
            )
        manifest = self.manifest(run_id)
        rows = self.query(
            """SELECT DISTINCT p.payload_json FROM decisions d JOIN project_records p
            ON p.payload_json::jsonb ->> 'timestamp'=d.payload_json::jsonb ->> 'data_timestamp_utc'
            WHERE d.run_id=%s AND p.record_type='closed_candle'
            AND p.payload_json::jsonb ->> 'dataset_sha256'=%s
            AND p.payload_json::jsonb ->> 'timeframe'=%s AND p.payload_json::jsonb ->> 'symbol'=%s""",
            (
                run_id,
                manifest["dataset_sha256"],
                manifest["config"]["timeframe"],
                manifest["config"]["symbol"],
            ),
        )
        bars = sorted(
            [decode(r["payload_json"]) for r in rows], key=lambda b: b["timestamp"]
        )
        count = self.query(
            "SELECT count(*) AS n FROM decisions WHERE run_id=%s", (run_id,)
        )[0]["n"]
        if len(bars) != count or len(bars) > 10000:
            raise ValueError("Dataset incompleto ou acima do limite de pesquisa.")
        return manifest, bars

    def recent_records(self, kind, limit=15):
        return [
            decode(r["payload_json"])
            for r in self.query(
                """SELECT payload_json FROM project_records
            WHERE record_type=%s ORDER BY recorded_at DESC LIMIT %s""",
                (kind, limit),
            )
        ]
