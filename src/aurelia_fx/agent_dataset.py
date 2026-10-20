"""Frozen research candidates, batched forecasts and separate benchmark labels."""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from uuid import uuid4

from .agent_model import PROTOCOL, fingerprint, partition_samples
from .agent_research import SESSIONS, intelligence_session, request_for, simulator
from .agent_strategy import (
    SPEC,
    SPEC_HASH,
    STRATEGY_ID,
    VERSION,
    attach_forecast,
    propose_pullback,
)
from .domain import Candidate, Candle
from .forecasting.config import SDK_REVISION
from .forecasting.core import prepare
from .historical.core import utc
from .sessions import SessionEngine


def forecast_contexts(memory, contexts, config, adapter, *, progress, check):
    indexed = {}
    for index, context in contexts.items():
        key = fingerprint(
            dict(
                configuration=config.fingerprint,
                sdk_revision=SDK_REVISION,
                context=[c.as_dict() for c in context],
            )
        )
        indexed[index] = (key, context)
    unique = {key: context for key, context in indexed.values()}
    output = {}
    with memory.pool.connection() as c:
        stored = (
            c.execute(
                """SELECT DISTINCT ON(record_key) record_key,payload_json FROM project_records
            WHERE record_type='agent_forecast_cache' AND record_key=ANY(%s)
            ORDER BY record_key,recorded_at,payload_sha256""",
                (list(unique),),
            ).fetchall()
            if unique
            else []
        )
    for row in stored:
        output[row["record_key"]] = json.loads(row["payload_json"])["output"]
    missing = [(key, context) for key, context in unique.items() if key not in output]
    for offset in range(0, len(missing), 8):
        check()
        group = missing[offset : offset + 8]
        progress(
            state="FORECASTING",
            stage="training",
            message=f"Gerando previsões históricas Timestral: {len(output)}/{len(unique)} contextos preparados.",
            training=dict(
                status="forecasting",
                samples=None,
                forecast_contexts=len(unique),
                forecast_completed=len(output),
            ),
        )
        results = adapter.forecast_batch(
            [[c.close for c in context] for _, context in group]
        )
        if len(results) != len(group):
            raise ValueError("O Timestral não devolveu todas as previsões solicitadas.")
        for (key, context), result in zip(group, results):
            memory.record_project_data(
                "agent_forecast_cache",
                key,
                dict(
                    cache_key=key,
                    configuration=config.fingerprint,
                    sdk_revision=SDK_REVISION,
                    input_hash=fingerprint([c.as_dict() for c in context]),
                    input_last=context[-1].timestamp.isoformat(),
                    input_bars=len(context),
                    output=result,
                ),
            )
            output[key] = result
    return {index: (key, output[key]) for index, (key, _) in indexed.items()}


def benchmark_setup(snapshot, history, output):
    last = history[-1]
    change = output["quantiles"][2][1] - last.close
    if abs(change) < 1e-12:
        return None
    sign = 1 if change > 0 else -1
    atr = mean(
        max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close))
        for a, b in zip(history[-15:-1], history[-14:])
    )
    if atr <= 0:
        return None
    distance = 1.5 * atr
    return dict(
        candidate=Candidate(
            "long" if sign > 0 else "short",
            last.close,
            last.close - sign * distance,
            last.close + sign * distance * 2.5,
            last.timestamp + timedelta(seconds=600),
            ("timestral_fixed_hourly_baseline",),
        ),
        snapshot=snapshot,
        signal_at=(last.timestamp + timedelta(seconds=300)).isoformat(),
        atr=atr,
        reference_close=last.close,
        features=dict(forecast_3_atr=abs(change) / atr),
        production_eligible=True,
    )


def label(
    memory,
    setup,
    following,
    *,
    run_id,
    experiment_hash,
    kind,
    features,
    cache_id,
    units,
):
    sample_id = fingerprint(
        dict(
            experiment=experiment_hash,
            at=setup["signal_at"],
            side=setup["candidate"].side,
            kind=kind,
        )
    )
    simulation = simulator(units)
    simulation.submit(request_for(setup, sample_id))
    sessions = SessionEngine(SESSIONS)
    for bar in following:
        simulation.advance(
            bar,
            data_valid=True,
            active_sessions=sessions.identify(bar.timestamp).active_sessions,
        )
        if not simulation.busy:
            break
    closed = next((e for e in simulation.events if e["status"] == "closed"), None)
    if closed is None:
        reasons = [
            reason
            for event in simulation.events
            for reason in event.get("risk", {}).get("reasons", [])
        ]
        return None, reasons
    candidate = asdict(setup["candidate"])
    candidate["expires_at"] = candidate["expires_at"].isoformat()
    sample = dict(
        sample_id=sample_id,
        run_id=run_id,
        features=features,
        forecast_cache_id=cache_id,
        signal_at=setup["signal_at"],
        entry_at=closed["entry_at"],
        exit_at=closed["observed_at"],
        net_pnl=closed["financial_result"]["net_pnl"],
        result_in_r=closed["financial_result"]["result_in_r"],
        snapshot=setup["snapshot"],
        candidate=candidate,
        execution=closed,
        label_scope="counterfactual_candidate_not_portfolio",
        dependence="overlapping_labels_not_independent",
        spec_hash=SPEC_HASH,
        strategy_id=STRATEGY_ID if kind == "technical" else "timestral_fixed_baseline",
        strategy_version=VERSION,
        production_eligible=setup["production_eligible"],
        kind=kind,
    )
    memory.record_project_data(
        "agent_training_sample" if kind == "technical" else "agent_benchmark_sample",
        sample_id,
        sample,
    )
    return sample, []


def build_samples(
    memory, rows, *, baseline, lot, contract, forecast_config, adapter, progress, check
):
    candles = [
        Candle(
            utc(r["timestamp"]),
            *(r[k] for k in ("open", "high", "low", "close")),
            r.get("volume", 0),
            r.get("spread_pips"),
        )
        for r in rows
    ]
    if not candles or any(
        b.timestamp <= a.timestamp for a, b in zip(candles, candles[1:])
    ):
        raise ValueError("Dataset vazio, duplicado ou fora de ordem.")
    run_id = str(uuid4())
    first = utc(baseline["as_of"]) - timedelta(days=baseline.get("training_days", 30))
    eligible = [b for b in candles if b.timestamp >= first]
    if len(eligible) < 100:
        raise ValueError("Histórico M5 insuficiente para congelar o experimento.")
    boundaries = [
        eligible[int(f * len(eligible))].timestamp.isoformat() for f in (0.6, 0.8)
    ]
    manifest = dict(
        run_id=run_id,
        strategy=SPEC,
        protocol=PROTOCOL,
        baseline_id=baseline["baseline_id"],
        dataset_hash=fingerprint([b.as_dict() for b in candles]),
        lot=lot,
        contract=contract,
        first_label_at=first.isoformat(),
        warmup_days=30,
        training_days=baseline.get("training_days", 30),
        as_of=baseline["as_of"],
        boundaries=boundaries,
        data_revision_known_by=baseline.get("_recorded_at"),
        clock_id=baseline["clock_id"],
        model_configuration=forecast_config.fingerprint,
        purpose="retrospective_research_paper_only",
        live_orders=False,
        prior_global_holdout_independence_claimed=False,
        source_tree_sha256=fingerprint(
            {
                p.name: p.read_text(encoding="utf-8")
                for p in sorted(Path(__file__).parent.glob("agent_*.py"))
            }
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    root = Path(__file__).resolve().parents[2]
    try:
        manifest["code_version"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
        manifest["dirty_worktree"] = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        manifest["code_version"] = "unknown"
        manifest["dirty_worktree"] = True
    manifest["experiment_hash"] = fingerprint(manifest)
    memory.record_project_data("agent_training_manifest", run_id, manifest)
    session = intelligence_session()
    counts = Counter()
    candidates = {}
    benchmarks = {}
    contexts = {}
    for index, bar in enumerate(candles):
        if index % 48 == 0:
            check()
            progress(
                state="PREPARING_EXPERIENCES",
                stage="training",
                message=f"Analisando o histórico: {index}/{len(candles)} candles, {len(candidates)} hipóteses de pesquisa.",
                training=dict(
                    status="preparing_examples",
                    samples=None,
                    run_id=run_id,
                    processed_bars=index,
                    total_bars=len(candles),
                    candidates=len(candidates),
                    counts=dict(counts),
                ),
            )
        snapshot = session.update(
            [rows[index]],
            spread_pips=bar.spread_pips,
            observed_at=bar.timestamp + timedelta(seconds=300),
        )
        if bar.timestamp < first:
            counts["warmup"] += 1
            continue
        setup, reason = propose_pullback(
            snapshot,
            session.history,
            daily_history=session.aggregator.history["D1"],
            research=True,
        )
        benchmark = (
            bar.timestamp.minute == 0
            and len(session.history) >= 64
            and snapshot.session
            and not snapshot.invalidating_evidence
            and bar.spread_pips is not None
            and bar.spread_pips <= 2
        )
        if reason:
            counts[reason] += 1
        if setup is None and not benchmark:
            continue
        following = candles[index + 1 : index + 13]
        if len(following) != 12 or any(
            (c.timestamp - bar.timestamp).total_seconds() != (i + 1) * 300
            for i, c in enumerate(following)
        ):
            counts["future_window_unresolved"] += 1
            continue
        try:
            context = prepare(
                candles[max(0, index - forecast_config.context + 1) : index + 1],
                bar.timestamp + timedelta(seconds=300),
                forecast_config,
            )
        except ValueError:
            counts["forecast_context_incomplete"] += 1
            continue
        contexts[index] = context
        if setup:
            candidates[index] = setup
        if benchmark:
            benchmarks[index] = (snapshot.as_dict(), tuple(session.history[-15:]))
    predictions = forecast_contexts(
        memory, contexts, forecast_config, adapter, progress=progress, check=check
    )
    samples = []
    benchmark_samples = []
    units = float(lot) * contract["contract_size"]
    for number, index in enumerate(sorted(contexts)):
        if number % 24 == 0:
            check()
            progress(
                state="REPLAYING",
                stage="training",
                message=f"Simulando entradas com custos: {number}/{len(contexts)} instantes, {len(samples)} experiências encerradas.",
                training=dict(
                    status="replaying",
                    samples=len(samples),
                    run_id=run_id,
                    counts=dict(counts),
                ),
            )
        cache_id, output = predictions[index]
        following = candles[index + 1 : index + 13]
        setup = candidates.get(index)
        pairs = []
        if setup:
            pairs.append((setup, "technical", attach_forecast(setup, output)))
        if index in benchmarks:
            snapshot, history = benchmarks[index]
            benchmark = benchmark_setup(snapshot, history, output)
            if benchmark:
                pairs.append((benchmark, "timestral", benchmark["features"]))
        for proposal, kind, features in pairs:
            sample, reasons = label(
                memory,
                proposal,
                following,
                run_id=run_id,
                experiment_hash=manifest["experiment_hash"],
                kind=kind,
                features=features,
                cache_id=cache_id,
                units=units,
            )
            if sample:
                (samples if kind == "technical" else benchmark_samples).append(sample)
                counts[kind + ":closed_candidate"] += 1
                if kind == "technical" and sample["production_eligible"]:
                    counts["technical:production_eligible"] += 1
            else:
                counts[kind + ":rejected_or_unresolved"] += 1
                for reason in reasons:
                    counts[kind + ":risk:" + reason] += 1
    partitions = partition_samples(samples, *boundaries)
    benchmark_partitions = partition_samples(benchmark_samples, *boundaries)
    report = dict(
        run_id=run_id,
        manifest=manifest,
        counts=dict(counts),
        partitions={k: len(v) for k, v in partitions.items()},
        benchmark_partitions={k: len(v) for k, v in benchmark_partitions.items()},
        sample_ids=[s["sample_id"] for s in samples],
        benchmark_sample_ids=[s["sample_id"] for s in benchmark_samples],
        status="dataset_prepared",
    )
    memory.record_project_data("agent_training_dataset", run_id, report)
    partitions.update({"benchmark_" + k: v for k, v in benchmark_partitions.items()})
    return report, partitions, candles
