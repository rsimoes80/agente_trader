"""Temporal learning and portfolio comparisons with final-period access gates."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from .agent_model import PROTOCOL, fingerprint, fit_model, predict, probability_metrics
from .agent_research import SESSIONS, simulator
from .domain import Candidate
from .execution_simulator import EntryRequest
from .historical.core import utc
from .sessions import SessionEngine


def portfolio(
    samples, candles, *, units, model=None, threshold=None, timestral_only=False
):
    simulation = simulator(units)
    sessions = SessionEngine(SESSIONS)
    samples = [
        s
        for s in samples
        if s.get("production_eligible", False)
        and (not timestral_only or s.get("strategy_id") == "timestral_fixed_baseline")
    ]
    signals = {s["entry_at"]: s for s in samples}
    if not samples:
        return dict(
            closed_trades=0,
            net_pnl=0,
            expectancy=None,
            profit_factor=None,
            max_close_equity_drawdown_pct=0,
            censored_trades=0,
            exposure_bars=0,
            risk_rejections=0,
            model_rejections=0,
            events=[],
        )
    first = min(s["entry_at"] for s in samples)
    last = max(s["exit_at"] for s in samples)
    exposure = 0
    rejected = 0
    for bar in candles:
        if bar.timestamp < utc(first) or bar.timestamp >= utc(last):
            continue
        sample = signals.get(bar.timestamp.isoformat())
        if sample and not simulation.busy:
            use = (
                (sample["features"]["forecast_3_atr"] > 0)
                if timestral_only
                else (model is None or predict(model, sample["features"]) >= threshold)
            )
            if use:
                data = sample["candidate"]
                candidate = Candidate(
                    data["side"],
                    data["entry"],
                    data["stop"],
                    data["target"],
                    utc(data["expires_at"]),
                    tuple(data["evidence"]),
                )
                simulation.submit(
                    EntryRequest(
                        sample["sample_id"],
                        sample["snapshot"]["snapshot_id"],
                        sample["sample_id"] + ":hypothesis",
                        candidate,
                        utc(sample["signal_at"]),
                        sample["snapshot"]["session"][0],
                        sample["snapshot"]["regime"],
                        sample["snapshot"],
                    )
                )
            else:
                rejected += 1
        if simulation.busy:
            exposure += 1
        simulation.advance(
            bar,
            data_valid=True,
            active_sessions=sessions.identify(bar.timestamp).active_sessions,
        )
    summary = simulation.summary()
    closed = [e for e in simulation.events if e["status"] == "closed"]
    gross_profit = sum(max(0, e["financial_result"]["net_pnl"]) for e in closed)
    gross_loss = -sum(min(0, e["financial_result"]["net_pnl"]) for e in closed)
    summary.update(
        expectancy=summary["net_pnl"] / len(closed)
        if closed and summary["net_pnl"] is not None
        else None,
        profit_factor=gross_profit / gross_loss if gross_loss else None,
        no_losses_observed=not gross_loss and bool(closed),
        exposure_bars=exposure,
        model_rejections=rejected,
        unresolved_position=simulation.position is not None,
        events=simulation.events,
    )
    return summary


def economic_gate(result, minimum_trades):
    return (
        result["closed_trades"] >= minimum_trades
        and result["net_pnl"] is not None
        and result["net_pnl"] > 0
        and result["expectancy"] > 0
        and (
            result["profit_factor"] is not None
            and result["profit_factor"] >= PROTOCOL["minimum_profit_factor"]
            or result.get("no_losses_observed", False)
        )
        and result["max_close_equity_drawdown_pct"] <= PROTOCOL["maximum_drawdown_pct"]
        and not result.get("account_locked", False)
        and not result["censored_trades"]
        and not result.get("unresolved_position", False)
    )


def without_events(result):
    return {k: v for k, v in result.items() if k != "events"}


def validate(memory, dataset, partitions, candles, *, lot, contract, progress, check):
    run_id = dataset["run_id"]
    units = float(lot) * contract["contract_size"]
    report = dict(
        run_id=run_id,
        status="insufficient_samples",
        samples=sum(len(partitions[k]) for k in ("development", "validation", "final")),
        counts=dataset["counts"],
        partitions=dataset["partitions"],
        protocol=PROTOCOL,
        active_version=None,
        final_accessed=False,
        paper_approved=False,
        live_orders=False,
        lot=lot,
        contract=contract,
        clock_id=dataset["manifest"]["clock_id"],
        spec_hash=fingerprint(dataset["manifest"]["strategy"]),
        model_configuration=dataset["manifest"]["model_configuration"],
        created_at=datetime.now(timezone.utc).isoformat(),
        training_period=dict(
            start=dataset["manifest"]["first_label_at"],
            end=dataset["manifest"]["as_of"],
            days=dataset["manifest"]["training_days"],
            warmup_days=30,
        ),
    )

    def finish(reason):
        report["reason"] = reason
        report["report_id"] = fingerprint(report)
        memory.record_project_data("agent_training_report", report["report_id"], report)
        return report

    development = partitions["development"]
    validation = partitions["validation"]
    if (
        len(development) < PROTOCOL["minimum_development"]
        or len(validation) < PROTOCOL["minimum_validation"]
    ):
        return finish("INSUFFICIENT_DEVELOPMENT_OR_VALIDATION_SAMPLES")
    check()
    progress(
        state="TRAINING",
        stage="training",
        message="Treinando o filtro de decisão e calibrando no desenvolvimento; validação e teste final não participam do ajuste.",
        training={**report, "status": "running"},
    )
    try:
        model = fit_model(development)
    except ValueError as exc:
        return finish(str(exc))
    memory.record_project_data("agent_model_candidate", model["model_id"], model)
    report["candidate_version"] = model["model_id"]
    # Fixed expanding windows, entirely within development. Labels crossing a
    # boundary are purged before fitting each fold.
    folds = []
    for fraction in (0.5, 0.65, 0.8):
        check()
        cut = int(fraction * len(development))
        end = min(len(development), cut + max(20, int(0.15 * len(development))))
        boundary = development[cut]["entry_at"]
        train = [s for s in development[:cut] if s["exit_at"] < boundary]
        later = development[cut:end]
        try:
            fold_model = fit_model(train)
        except ValueError:
            continue
        folds.append(
            dict(
                training_samples=len(train),
                evaluation_samples=len(later),
                metrics=probability_metrics(fold_model, later),
            )
        )
    report["walk_forward"] = folds
    if len(folds) < 2:
        return finish("INSUFFICIENT_WALK_FORWARD_SAMPLES")
    progress(
        state="VALIDATING",
        stage="validation",
        message="Comparando estratégia técnica, filtro Timestral e modelo conjunto no período de validação.",
        training={**report, "status": "validating"},
    )
    technical = portfolio(validation, candles, units=units)
    forecast = portfolio(
        partitions["benchmark_validation"], candles, units=units, timestral_only=True
    )
    candidates = []
    for threshold in PROTOCOL["probability_thresholds"]:
        check()
        result = portfolio(
            validation, candles, units=units, model=model, threshold=threshold
        )
        candidates.append((threshold, result))
    probability = probability_metrics(model, validation)
    report["validation"] = dict(
        probability=probability,
        technical=without_events(technical),
        timestral=without_events(forecast),
        thresholds=[dict(threshold=t, result=without_events(r)) for t, r in candidates],
    )
    survivors = [
        (t, r)
        for t, r in candidates
        if economic_gate(r, PROTOCOL["minimum_trades_validation"])
        and r["net_pnl"] > max(technical["net_pnl"] or 0, forecast["net_pnl"] or 0)
    ]
    if (
        not survivors
        or probability["brier_improvement"] < PROTOCOL["required_brier_improvement"]
    ):
        report["status"] = "rejected"
        return finish("NO_VALIDATED_INCREMENTAL_ADVANTAGE")
    threshold, chosen = max(survivors, key=lambda pair: pair[1]["net_pnl"])
    # Freeze the selected threshold before opening the final partition.
    selection = dict(
        run_id=run_id,
        model_id=model["model_id"],
        threshold=threshold,
        protocol=PROTOCOL,
        validation_hash=fingerprint(report["validation"]),
    )
    memory.record_project_data("agent_frozen_selection", run_id, selection)
    report["threshold"] = threshold
    if len(partitions["final"]) < PROTOCOL["minimum_final"]:
        return finish("INSUFFICIENT_FINAL_SAMPLES")
    check()
    report["final_accessed"] = True
    final = partitions["final"]
    final_technical = portfolio(final, candles, units=units)
    final_forecast = portfolio(
        partitions["benchmark_final"], candles, units=units, timestral_only=True
    )
    combined = portfolio(final, candles, units=units, model=model, threshold=threshold)
    final_prob = probability_metrics(model, final)
    report["final"] = dict(
        technical=without_events(final_technical),
        timestral=without_events(final_forecast),
        combined=without_events(combined),
        probability=final_prob,
    )
    for strategy, result in (
        ("technical", final_technical),
        ("timestral", final_forecast),
        ("combined", combined),
    ):
        memory.record_project_data(
            "agent_portfolio_evaluation",
            str(uuid4()),
            dict(run_id=run_id, phase="final", strategy=strategy, **result),
        )
    if (
        economic_gate(combined, PROTOCOL["minimum_trades_final"])
        and combined["net_pnl"]
        > max(final_technical["net_pnl"] or 0, final_forecast["net_pnl"] or 0)
        and final_prob["brier_improvement"] >= PROTOCOL["required_brier_improvement"]
    ):
        report["status"] = "validated_pending_approval"
        return finish("PAPER_VERSION_REQUIRES_EXPLICIT_APPROVAL")
    report["status"] = "rejected"
    return finish("FINAL_EVALUATION_REJECTED")
