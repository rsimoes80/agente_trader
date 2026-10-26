"""Forecast display contract bound to its exact input and source clock."""

import math
from datetime import timedelta

from .historical.core import utc


def forecast_view(output, context, *, clock_id, configuration, generated_at, symbol='EURUSD', profile_id=None):
    from .instruments import symbol_name
    symbol_name(symbol)
    quantiles = output["quantiles"]
    if len(quantiles) != 12 or any(
        len(row) != 3
        or not all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in row)
        or not row[0] <= row[1] <= row[2]
        for row in quantiles
    ):
        raise ValueError("Quantis Timestral inválidos para exibição.")
    # The final input is a closed M5 candle; each prediction targets the close
    # of the next candle, not its opening timestamp.
    reference = context[-1].timestamp + timedelta(minutes=5)
    return dict(
        symbol=symbol, profile_id=profile_id, timeframe="M5", clock_id=clock_id,
        configuration=configuration, reference_at=reference.isoformat(),
        generated_at=utc(generated_at).isoformat(),
        valid_until=(reference + timedelta(minutes=5)).isoformat(),
        reference_price=context[-1].close,
        interval="Q10–Q90 nominal; cobertura não garantida",
        points=[dict(at=(reference + timedelta(minutes=5 * (i + 1))).isoformat(),
                     low=row[0], median=row[1], high=row[2])
                for i, row in enumerate(quantiles)],
    )
