"""Pure causal data and evaluation contracts; no ML or database dependencies."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

from ..domain import Candle


def utc(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("Timestamp Timestral exige timezone UTC.")
    return stamp.astimezone(timezone.utc)


def prepare(rows, as_of, config):
    as_of = utc(as_of)
    candles = []
    previous = None
    for row in rows:
        stamp = utc(row.timestamp if isinstance(row, Candle) else row["timestamp"])
        if previous is not None and stamp <= previous:
            raise ValueError("Candles duplicados ou fora de ordem.")
        previous = stamp
        if stamp.timestamp() % 300:
            raise ValueError("Candle desalinhado de M5.")
        if stamp + timedelta(seconds=300) > as_of:
            continue  # Incomplete and future candles never enter model inputs.
        candle = (
            row
            if isinstance(row, Candle)
            else Candle(
                stamp,
                *(float(row[k]) for k in ("open", "high", "low", "close")),
                float(row.get("volume", 0)),
                row.get("spread_pips"),
            )
        )
        if min(candle.open, candle.high, candle.low, candle.close) <= 0:
            raise ValueError("Preço ausente ou inválido.")
        if candles and stamp - candles[-1].timestamp != timedelta(seconds=300):
            candles.clear()  # New contiguous context after holidays/weekends/feed gaps.
        candles.append(candle)
    candles = candles[-config.context :]
    if len(candles) < config.min_context:
        raise ValueError("Dados insuficientes: contexto M5 fechado e contíguo.")
    return candles


def direction(value):
    return "UP" if value > 1e-10 else "DOWN" if value < -1e-10 else "FLAT"


def build_predictions(candles, output, config, *, scope, source_id, regime, as_of):
    levels = output["levels"]
    values = output["quantiles"]
    if levels != [0.1, 0.5, 0.9] or len(values) != 12:
        raise ValueError("Formato de previsão Timestral inválido.")
    if any(
        len(v) != 3
        or not all(math.isfinite(x) and x > 0 for x in v)
        or list(v) != sorted(v)
        for v in values
    ):
        raise ValueError("Quantis inválidos ou cruzados.")
    last = candles[-1]
    model_key = hashlib.sha256(
        json.dumps(
            {
                k: output[k]
                for k in ("model", "revision", "artifact_sha256", "sdk_revision")
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    digest = hashlib.sha256(
        json.dumps([c.as_dict() for c in candles], sort_keys=True).encode()
    ).hexdigest()
    drift = (last.close - candles[0].close) / (len(candles) - 1)
    result = []
    for horizon in config.horizons:
        low, median, high = values[horizon - 1]
        key = dict(
            scope=scope,
            source_id=source_id,
            symbol="EURUSD",
            timeframe="M5",
            reference_time=last.timestamp.isoformat(),
            horizon=horizon,
            model_key=model_key,
            config_hash=config.fingerprint,
        )
        prediction_id = hashlib.sha256(
            json.dumps(key, sort_keys=True).encode()
        ).hexdigest()
        result.append(
            dict(
                **key,
                prediction_id=prediction_id,
                as_of=utc(as_of).isoformat(),
                target_time=(
                    last.timestamp + timedelta(seconds=300 * horizon)
                ).isoformat(),
                base_price=last.close,
                median=median,
                quantiles={"0.1": low, "0.5": median, "0.9": high},
                expected_return=median / last.close - 1,
                direction=direction(median / last.close - 1),
                uncertainty=high - low,
                nominal_coverage=0.8,
                latency_ms=output["latency_ms"],
                regime=regime,
                context_bars=len(candles),
                input_sha256=digest,
                baseline_persistence=last.close,
                baseline_drift=last.close + horizon * drift,
                model=output["model"],
                revision=output["revision"],
                artifact_sha256=output["artifact_sha256"],
                sdk_revision=output["sdk_revision"],
                device=output["device"],
                status="ok",
                error=None,
            )
        )
    return result


def evaluate(prediction, candle, *, observed_at):
    stamp = utc(candle.timestamp if isinstance(candle, Candle) else candle["timestamp"])
    now = utc(observed_at)
    if stamp != utc(prediction["target_time"]) or stamp + timedelta(seconds=300) > now:
        raise ValueError("Resultado ainda não fechado ou horizonte incorreto.")
    price = candle.close if isinstance(candle, Candle) else float(candle["close"])
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Preço observado inválido.")
    actual_return = price / prediction["base_price"] - 1
    quantiles = prediction["quantiles"]
    pinball = {
        q: max(float(q) * (price - v), (float(q) - 1) * (price - v))
        for q, v in quantiles.items()
    }
    return dict(
        evaluation_id=prediction["prediction_id"],
        prediction_id=prediction["prediction_id"],
        observed_time=stamp.isoformat(),
        observed_at=now.isoformat(),
        actual_price=price,
        absolute_error=abs(price - prediction["median"]),
        return_error=actual_return - prediction["expected_return"],
        directional_hit=direction(actual_return) == prediction["direction"],
        interval_covered=quantiles["0.1"] <= price <= quantiles["0.9"],
        pinball=pinball,
        baseline_persistence_error=abs(price - prediction["baseline_persistence"]),
        baseline_drift_error=abs(price - prediction["baseline_drift"]),
    )
