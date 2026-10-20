"""Validate the bridge UTC contract; never convert timestamps a second time."""

from datetime import datetime


class SourceClockUnavailable(RuntimeError):
    def __init__(self, status, message):
        self.status, self.public_message = status, message
        super().__init__(message)


def validate_source_clock(data, now):
    clock = data.get("source_clock", {})
    if (
        data.get("timestamp_semantics") != "utc_v1"
        or clock.get("contract") != "mt5-utc-v1"
        or clock.get("normalized_to") != "UTC"
        or not clock.get("clock_id")
    ):
        raise SourceClockUnavailable(
            "clock_contract_missing",
            "A ponte precisa ser atualizada: contrato de horário UTC ausente.",
        )
    if clock.get("verified_current") is not True:
        raise SourceClockUnavailable(
            "clock_waiting_for_live_tick",
            "Aguardando tick recente para validar o relógio da fonte. Nova tentativa automática.",
        )
    try:
        response = datetime.fromisoformat(clock["response_at_utc"])
        tick = datetime.fromisoformat(clock["tick_utc"])
        if response.tzinfo is None or tick.tzinfo is None:
            raise ValueError("naive")
        if abs((now - response).total_seconds()) > 60:
            raise SourceClockUnavailable(
                "host_clock_mismatch",
                "Os relógios UTC do Windows e Linux diferem, ou a resposta está atrasada. Verifique sincronização de hora.",
            )
        age = (now - tick).total_seconds()
        if not -5 <= age <= 60:
            raise SourceClockUnavailable(
                "stale_quote",
                "Tick atrasado ou futuro após conversão UTC. Aguardando atualização da fonte.",
            )
    except (KeyError, TypeError, ValueError):
        raise SourceClockUnavailable(
            "clock_contract_invalid", "Metadados de horário inválidos na ponte MT5."
        ) from None
    return dict(clock)
