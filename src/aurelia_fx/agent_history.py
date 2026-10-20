"""A larger research M5 archive without replacing the product's monthly baseline."""

from datetime import datetime, timedelta, timezone

from .agent_model import fingerprint
from .historical.core import closed_rows, summarize
from .source_clock import validate_source_clock


def collect_training_history(repository, fetch, *, days=60, expected_clock_id):
    if type(days) is not int or not 60 <= days <= 365:
        raise ValueError("A pesquisa requer de 60 a 365 dias, incluindo aquecimento.")
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    data = fetch(
        "EURUSD", "M5", min(100000, int(days * 86400 / 300) + 20), include_current=False
    )
    clock = validate_source_clock(data, now=datetime.now(timezone.utc))
    if (
        clock["clock_id"] != expected_clock_id
        or data.get("timeframe") != "M5"
        or data.get("symbol") not in {"EURUSD", "EUR/USD"}
    ):
        raise ValueError("A fonte mudou durante a captura para treinamento.")
    rows = closed_rows(data["candles"], "M5", start=start, as_of=now)
    repository.ingest(rows, clock=clock, timeframe="M5")
    frozen = repository.candles(
        clock_id=clock["clock_id"], timeframe="M5", start=start, as_of=now
    )
    measured = summarize(frozen, "M5", start=start, as_of=now, days=days)
    baseline = dict(
        version="agent-training-history-v1",
        source_clock=clock,
        clock_id=clock["clock_id"],
        days=days,
        training_days=days - 30,
        warmup_days=30,
        start=start.isoformat(),
        as_of=now.isoformat(),
        status="ready" if measured["ready"] else "insufficient_history",
        timeframes={"M5": measured},
        purpose="research_archive_separate_from_monthly_baseline",
    )
    baseline["baseline_id"] = fingerprint(baseline)
    repository.memory.record_project_data(
        "agent_training_history", baseline["baseline_id"], baseline
    )
    return baseline
