"""One-way optional evidence service; cannot mutate strategy decisions."""

from dataclasses import asdict

from .core import build_predictions, prepare


class ForecastService:
    def __init__(self, config, repository, adapter):
        self.config, self.repository, self.adapter = config, repository, adapter

    def observe(self, rows, *, as_of, scope, source_id, regime="UNKNOWN", issue=True):
        if not self.config.enabled:
            return dict(status="disabled", predictions=[])
        try:
            candles = prepare(rows, as_of, self.config)
            evaluated = self.repository.evaluate_available(
                rows, scope=scope, source_id=source_id, observed_at=as_of
            )
            if not issue or self.repository.has_batch(
                scope, source_id, candles[-1].timestamp, self.config.fingerprint
            ):
                return dict(status="observing", predictions=[], evaluated=evaluated)
            output = self.adapter.forecast([c.close for c in candles])
            predictions = build_predictions(
                candles,
                output,
                self.config,
                scope=scope,
                source_id=source_id,
                regime=regime,
                as_of=as_of,
            )
            config = asdict(self.config)
            for key in ("python", "cache_dir"):
                config.pop(key)
            for prediction in predictions:
                prediction["configuration"] = config
            self.repository.save(predictions, config)
            return dict(
                status="observing", predictions=predictions, evaluated=evaluated
            )
        except Exception as exc:
            # Never call the decision engine or permit a forecast failure to stop it.
            return dict(
                status="insufficient_data"
                if isinstance(exc, (ValueError, TypeError, KeyError))
                else "unavailable",
                predictions=[],
                error_type=type(exc).__name__,
                message=str(exc)[:180],
            )
