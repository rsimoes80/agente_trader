"""Classification sensitivity only; no tuning on validation or holdout, no promotion."""

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from statistics import median

from .domain import Candle
from .regime import MarketRegimeEngine, RegimeConfig
from .replay_data import unexpected_gap
from .trend import ClosedBarAggregator, HierarchyConfig, timeframe_seconds


def compare_regime_parameters(manifest, rows, variations):
    if not isinstance(variations, list) or not 1 <= len(variations) <= 3:
        raise ValueError("Informe de uma a três configurações candidatas.")
    allowed = {
        "window",
        "confirmation_bars",
        "range_efficiency_max",
        "trend_efficiency_min",
        "range_overlap_min",
    }
    base = manifest["config"]["regime_config"]
    candidates = [("baseline", RegimeConfig(**base))]
    for index, variation in enumerate(variations):
        if not isinstance(variation, dict) or not set(variation) <= allowed:
            raise ValueError("Parâmetro não habilitado para comparação.")
        config = RegimeConfig(**{**base, **variation})
        if not 6 <= config.window <= 80 or not 2 <= config.confirmation_bars <= 10:
            raise ValueError("Janela deve estar entre 6–80 e confirmação entre 2–10.")
        candidates.append((f"candidate_{index + 1}", config))
    hierarchy = HierarchyConfig(**manifest["config"]["hierarchy"])
    seconds = timeframe_seconds(hierarchy.execution_timeframe)
    candles = [
        Candle(
            datetime.fromisoformat(row["timestamp"]),
            *(row[k] for k in ("open", "high", "low", "close")),
            row.get("volume", 0),
            row.get("spread_pips"),
        )
        for row in rows
    ]
    output = []
    baseline = None
    for name, config in candidates:
        engine = MarketRegimeEngine(config)
        aggregator = ClosedBarAggregator(hierarchy)
        labels = []
        unique_updates = []
        last_context = None
        previous = None
        gap_count = 0
        for bar in candles:
            if previous and unexpected_gap(previous, bar, seconds):
                gap_count += 1
                engine.reset()
                aggregator.reset()
                last_context = None
                unique_updates.append(None)
            histories = aggregator.add(bar)
            history = histories.get(hierarchy.context_timeframe, ())
            state = engine.evaluate(
                history,
                symbol=manifest["config"]["symbol"],
                timeframe=hierarchy.context_timeframe,
                now=bar.timestamp + timedelta(seconds=seconds),
                snapshot_id="offline",
            )
            labels.append(state.regime)
            context_stamp = history[-1].timestamp if history else None
            if context_stamp is not None and context_stamp != last_context:
                unique_updates.append(state.regime)
                last_context = context_stamp
            previous = bar
        if baseline is None:
            baseline = labels
        counts = Counter(labels)
        durations = []
        last = None
        changes = 0
        for label in unique_updates:
            if label is None:
                last = None
                continue
            if label == last:
                durations[-1] += 1
            else:
                if last is not None:
                    changes += 1
                durations.append(1)
                last = label
        updates = sum(item is not None for item in unique_updates)
        output.append(
            {
                "variant": name,
                "config": asdict(config),
                "config_hash": engine.config_hash,
                "regime_counts": dict(counts),
                "observations": len(labels),
                "unknown_fraction": counts["UNKNOWN"] / len(labels) if labels else None,
                "context_updates": updates,
                "regime_changes": changes,
                "changes_per_100_context_updates": 100 * changes / updates
                if updates
                else None,
                "median_dwell_context_bars": median(durations) if durations else None,
                "agreement_with_baseline": sum(a == b for a, b in zip(labels, baseline))
                / len(labels)
                if labels
                else None,
                "gap_resets": gap_count,
            }
        )
    return {
        "scope": "classification_sensitivity_only",
        "partition": "development",
        "dataset_sha256": manifest["dataset_sha256"],
        "run_id": manifest["run_id"],
        "execution_timeframe": hierarchy.execution_timeframe,
        "regime_timeframe": hierarchy.context_timeframe,
        "variants": output,
        "holdout_accessed": False,
        "validation_accessed": False,
        "automatic_promotion": False,
        "profitability_evaluated": False,
        "interpretation": "Concordância não mede acurácia. Menos UNKNOWN não significa melhor classificação.",
    }
