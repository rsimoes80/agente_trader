"""Market-data normalization and integrity checks; no network or broker access."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .domain import Candle, DataQuality


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("timestamp precisa ser ISO-8601 com offset/timezone.")
    if result.tzinfo is None:
        raise ValueError("timestamp sem timezone não é aceito.")
    return result.astimezone(timezone.utc)


def normalize_candle(row: Mapping[str, Any]) -> Candle:
    stamp = _timestamp(row.get("timestamp", row.get("time")))
    values = {key: float(row[key]) for key in ("open", "high", "low", "close")}
    volume = float(row.get("volume", row.get("tick_volume", 0.0)))
    spread_raw = row.get("spread_pips")
    spread = None if spread_raw is None else float(spread_raw)
    if not all(math.isfinite(value) for value in (*values.values(), volume)):
        raise ValueError("OHLCV contém valor não finito.")
    if spread is not None and not math.isfinite(spread):
        raise ValueError("Spread contém valor não finito.")
    return Candle(timestamp=stamp, **values, volume=volume, spread_pips=spread)


def validate_candles(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    max_age_seconds: float | None = None,
    expected_timestamps: Sequence[datetime] | None = None,
    allow_gap: Callable[[datetime, datetime], bool] | None = None,
) -> tuple[tuple[Candle, ...], DataQuality]:
    """Normalize candles and report invalid ordering, gaps and stale data.

    Gap detection is calendar-aware only when the caller supplies the expected
    market-open timestamps. Without them, large time gaps are reported as a
    warning because weekends and market closures are legitimate in FX.
    """
    candles: list[Candle] = []
    errors: list[str] = []
    warnings: list[str] = []
    for index, row in enumerate(rows):
        try:
            candles.append(normalize_candle(row))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            errors.append(f"candle[{index}]: {exc}")
    stamps = [candle.timestamp for candle in candles]
    if len(set(stamps)) != len(stamps):
        errors.append("Candles duplicados no mesmo timestamp.")
    if any(later <= earlier for earlier, later in zip(stamps, stamps[1:])):
        errors.append("Candles fora de ordem cronológica.")
    if expected_timestamps is not None and stamps:
        expected = {_timestamp(stamp) for stamp in expected_timestamps}
        observed = set(stamps)
        missing = sorted(expected - observed)
        if missing:
            errors.append(f"{len(missing)} candle(s) esperado(s) ausente(s); primeiro gap: {missing[0].isoformat()}.")
    elif len(stamps) > 1:
        unusual = [
            (earlier, later) for earlier, later in zip(stamps, stamps[1:])
            if (later - earlier).total_seconds() > 3 * 86_400
            and not (allow_gap and allow_gap(earlier, later))
        ]
        if unusual:
            warnings.append(f"Há {len(unusual)} intervalo(s) longo(s); confirme fechamento de mercado/fonte de calendário.")
    latest = stamps[-1] if stamps else None
    if max_age_seconds is not None and latest is not None:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        age = (reference - latest).total_seconds()
        if age < -60:
            errors.append("Timestamp do último candle está mais de 60 s no futuro.")
        elif age > max_age_seconds:
            errors.append(f"Dados atrasados: candle mais recente tem {age:.0f} s; limite {max_age_seconds:.0f} s.")
    if not candles:
        errors.append("Nenhum candle válido disponível.")
    quality = DataQuality(valid=not errors, errors=tuple(errors), warnings=tuple(warnings), latest_timestamp=latest)
    return tuple(candles), quality
