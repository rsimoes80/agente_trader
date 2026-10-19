"""Strict, offline CSV ingestion. Timestamps denote candle opens in UTC."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .domain import Candle
from .market_data import validate_candles


TIMEFRAMES = {"M1": 60, "M5": 300, "M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}


@dataclass(frozen=True)
class ReplayDataset:
    candles: tuple[Candle, ...]
    sha256: str
    source: str
    reference: str


def load_csv(path: Path, *, source: str) -> ReplayDataset:
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or not {"timestamp", "open", "high", "low", "close"} <= set(reader.fieldnames):
        raise ValueError("CSV precisa de timestamp,open,high,low,close; volume e spread_pips sao opcionais.")
    rows = []
    for row in reader:
        row = {key: value for key, value in row.items() if value not in (None, "")}
        rows.append(row)
    candles, quality = validate_candles(rows)
    if not quality.valid:
        raise ValueError("Dataset rejeitado: " + "; ".join(quality.errors))
    if any(min(c.open, c.high, c.low, c.close) <= 0 for c in candles):
        raise ValueError("EUR/USD exige precos positivos.")
    digest = hashlib.sha256(raw).hexdigest()
    return ReplayDataset(candles, digest, source, f"sha256:{digest}")


def market_open(stamp) -> bool:
    """FX weekly closure convention, NOT a broker holiday calendar."""
    local = stamp.astimezone(ZoneInfo("America/New_York"))
    day = local.weekday()
    return not (day == 5 or (day == 4 and local.hour >= 17) or (day == 6 and local.hour < 17))


def unexpected_gap(previous: Candle, current: Candle, seconds: int) -> bool:
    difference = (current.timestamp - previous.timestamp).total_seconds()
    if difference <= 0 or difference % seconds:
        return True
    stamp = previous.timestamp + timedelta(seconds=seconds)
    while stamp < current.timestamp:
        if market_open(stamp):
            return True
        stamp += timedelta(seconds=seconds)
    return False
