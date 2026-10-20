"""Frozen-config chronological partitions with a reserved final holdout."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from uuid import uuid4

from .experience_memory import ExperienceMemory
from .replay import ReplayConfig, encode, run_replay
from .replay_data import ReplayDataset
from .replay_strategy import STRATEGY_VERSION


def split_dataset(
    dataset: ReplayDataset, *, warmup_bars: int
) -> dict[str, ReplayDataset]:
    size = len(dataset.candles)
    boundaries = (0, int(size * 0.6), int(size * 0.8), size)
    parts = {}
    for index, label in enumerate(("development", "validation", "holdout")):
        start, end = boundaries[index : index + 2]
        bars = dataset.candles[start:end]
        if len(bars) <= warmup_bars:
            raise ValueError(
                "Cada janela temporal precisa superar o warmup; aumente o historico."
            )
        raw = "\n".join(encode(c.as_dict()) for c in bars) + "\n"
        digest = hashlib.sha256(raw.encode()).hexdigest()
        parts[label] = ReplayDataset(
            bars,
            digest,
            dataset.source,
            f"{dataset.reference}#rows={start}:{end}#partition={label}#sha256={digest}",
            dataset.source_clock,
        )
    return parts


def run_temporal_validation(
    dataset: ReplayDataset,
    *,
    config: ReplayConfig,
    memory: ExperienceMemory,
    output_dir: Path,
    code_version: str = "unknown",
    include_holdout: bool = False,
) -> dict:
    parts = split_dataset(dataset, warmup_bars=config.warmup_bars)
    plan_id = "validation-" + str(uuid4())
    directory = output_dir / plan_id
    directory.mkdir(parents=True, exist_ok=False)
    config_hash = hashlib.sha256(encode(config.as_dict()).encode()).hexdigest()
    plan = {
        "schema_version": 1,
        "plan_id": plan_id,
        "dataset_sha256": dataset.sha256,
        "config_hash": config_hash,
        "config": config.as_dict(),
        "code_version": code_version,
        "split_policy": "chronological 60/20/20; independent accounts, warmup and memories",
        "adjustments": "none; config frozen before evaluating any partition",
        "holdout_requested": include_holdout,
        "prior_access": "not auditable; previously viewed data cannot establish a fresh independent holdout",
        "partitions": {
            label: {
                "sha256": part.sha256,
                "bars": len(part.candles),
                "first_open": part.candles[0].timestamp.isoformat(),
                "last_open": part.candles[-1].timestamp.isoformat(),
            }
            for label, part in parts.items()
        },
    }
    plan["plan_sha256"] = hashlib.sha256(encode(plan).encode()).hexdigest()
    (directory / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    memory.record_artifact(
        artifact_id=plan_id + ":sealed",
        dataset_reference=dataset.reference,
        code_version=code_version,
        strategy_version=STRATEGY_VERSION,
        config_hash=config_hash,
        status="temporal_plan_sealed",
        payload=plan,
    )
    reports = {}
    try:
        for label in ("development", "validation", "holdout"):
            if label == "holdout" and not include_holdout:
                continue
            reports[label] = run_replay(
                parts[label],
                config=config,
                memory=memory,
                output_dir=directory,
                code_version=code_version,
            )
        summary = {
            **plan,
            "status": "completed",
            "reports": reports,
            "holdout_status": "evaluated_with_frozen_config"
            if include_holdout
            else "reserved_not_evaluated",
            "report_directory": str(directory.resolve()),
            "interpretation": "Descriptive research only; no tuning, promotion, significance or profitability claim.",
        }
        (directory / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rows = []
        for label, part in parts.items():
            report = reports.get(label)
            if report:
                name = Path(report["report_directory"]).name
                metrics = report["execution"]
                rows.append(
                    f"<tr><td>{label}</td><td>{len(part.candles)}</td><td>{metrics['closed_trades']}</td>"
                    f'<td>{metrics["net_pnl"]}</td><td><a href="{name}/report.html">Relatório</a></td></tr>'
                )
            else:
                rows.append(
                    f'<tr><td>{label}</td><td>{len(part.candles)}</td><td colspan="3">Reservado — não avaliado</td></tr>'
                )
        (directory / "report.html").write_text(
            '<!doctype html><html lang="pt-BR"><meta charset="utf-8">'
            "<title>Validação temporal — Aurelia FX</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;"
            "background:#10181e;color:#eee}td,th{padding:14px;text-align:left}a{color:#43d69a}pre{white-space:pre-wrap}</style>"
            "<h1>Validação temporal EUR/USD</h1><p>Configuração congelada, contas e memórias independentes por janela.</p>"
            "<table><tr><th>Janela</th><th>Candles</th><th>Trades encerrados</th><th>P&amp;L líquido simulado USD</th><th>Detalhes</th></tr>"
            + "".join(rows)
            + "</table><details><summary>Plano de pesquisa</summary><pre>"
            + html.escape(json.dumps(plan, ensure_ascii=False, indent=2))
            + "</pre></details></html>",
            encoding="utf-8",
        )
        memory.record_artifact(
            artifact_id=plan_id + ":completed",
            dataset_reference=dataset.reference,
            code_version=code_version,
            strategy_version=STRATEGY_VERSION,
            config_hash=config_hash,
            status="temporal_validation_completed",
            payload={
                "plan_id": plan_id,
                "holdout_status": summary["holdout_status"],
                "runs": {key: report["run_id"] for key, report in reports.items()},
            },
        )
        return summary
    except Exception:
        memory.record_artifact(
            artifact_id=plan_id + ":failed",
            dataset_reference=dataset.reference,
            code_version=code_version,
            strategy_version=STRATEGY_VERSION,
            config_hash=config_hash,
            status="temporal_validation_failed",
            payload={"plan_id": plan_id, "completed_partitions": list(reports)},
        )
        raise
