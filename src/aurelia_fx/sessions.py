"""Configurable, DST-aware session identification using UTC inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class SessionWindow:
    name: str
    timezone_name: str
    opens: time
    closes: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)

    def __post_init__(self) -> None:
        try:
            ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError:
            raise ValueError(f"Timezone desconhecido: {self.timezone_name}.") from None
        if not self.name or not self.weekdays or any(day not in range(7) for day in self.weekdays):
            raise ValueError("Sessão precisa de nome e dias da semana válidos.")


@dataclass(frozen=True, slots=True)
class SessionContext:
    timestamp_utc: datetime
    active_sessions: tuple[str, ...]
    local_dates: tuple[tuple[str, str], ...]


class SessionEngine:
    def __init__(self, windows: tuple[SessionWindow, ...] | list[SessionWindow]):
        self.windows = tuple(windows)

    def identify(self, timestamp: datetime) -> SessionContext:
        if timestamp.tzinfo is None:
            raise ValueError("SessionEngine exige timestamp com timezone.")
        stamp = timestamp.astimezone(timezone.utc)
        active: list[str] = []
        local_dates: list[tuple[str, str]] = []
        for window in self.windows:
            local = stamp.astimezone(ZoneInfo(window.timezone_name))
            clock = local.timetz().replace(tzinfo=None)
            start, end = window.opens, window.closes
            if start == end:
                in_window = local.weekday() in window.weekdays
            elif start < end:
                in_window = local.weekday() in window.weekdays and start <= clock < end
            else:
                starts_today = local.weekday() in window.weekdays and clock >= start
                previous_day = (local.weekday() - 1) % 7
                ends_today = previous_day in window.weekdays and clock < end
                in_window = starts_today or ends_today
            if in_window:
                active.append(window.name)
                local_dates.append((window.name, local.date().isoformat()))
        return SessionContext(stamp, tuple(active), tuple(local_dates))
