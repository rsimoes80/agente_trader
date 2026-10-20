"""Human review presentation and descriptive outcomes, without strategy changes."""

from datetime import timedelta

from .historical.core import utc

VERDICTS = {"agree", "disagree", "unsure"}
REASONS = {"regime", "trend", "levels", "confirmation", "data", "other"}


def period_seconds(timeframe):
    units = {"M": 60, "H": 3600, "D": 86400, "W": 604800}
    if timeframe[:1] not in units or not timeframe[1:].isdigit():
        raise ValueError("Período não suportado para acompanhamento.")
    return units[timeframe[0]] * int(timeframe[1:])


def describe_outcome(decision, candles, *, reference_close, now, bars=12):
    """Use only the next fixed window of closed bars, never label a trade."""
    seconds = period_seconds(decision["timeframe"])
    start = utc(decision["data_timestamp_utc"]) + timedelta(seconds=seconds)
    end = start + timedelta(seconds=seconds * bars)
    selected = {}
    conflict = False
    for candle in candles:
        stamp = utc(candle["timestamp"])
        if start <= stamp < end and stamp + timedelta(seconds=seconds) <= now:
            values = tuple(candle[k] for k in ("open", "high", "low", "close"))
            if stamp in selected and selected[stamp][0] != values:
                conflict = True
            selected[stamp] = (values, candle)
    expected = [start + timedelta(seconds=seconds * i) for i in range(bars)]
    complete = not conflict and all(t in selected for t in expected)
    rows = [selected[t][1] for t in sorted(selected)]
    result = dict(
        version="human-review-outcome-v1",
        horizon_bars=bars,
        starts_at=start.isoformat(),
        ends_at=end.isoformat(),
        closed_bars=len(rows),
        complete=complete,
        status="data_conflict"
        if conflict
        else "complete"
        if complete
        else "pending"
        if now < end
        else "incomplete",
        reference_close=reference_close,
        training_authorized=False,
        interpretation="Descriptive price behavior; not strategy accuracy or trade P&L.",
    )
    if complete and reference_close is not None:
        result.update(
            last_close=rows[-1]["close"],
            price_change=rows[-1]["close"] - reference_close,
            highest=max(c["high"] for c in rows),
            lowest=min(c["low"] for c in rows),
        )
    return result
