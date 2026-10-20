"""Explicit ThinkMarkets FX calendar, without inferring closures from gaps.

Source checked 2026-10-20:
https://support.thinkmarkets.com/hc/en-gb/articles/11613376227601-Market-hours
Server Monday 00:03 to Friday 23:55, GMT+3 summer / GMT+2 winter.
The existing validated NY-close clock profile maps that to NY Sunday 17:03
through Friday 16:55. A bar slot is expected if it contains tradable time.
Holidays are not inferred; unexplained missing slots remain invalid.
"""

from datetime import time, timedelta
from zoneinfo import ZoneInfo

VERSION = "thinkmarkets-forex-v1"


def instant_open(stamp):
    local = stamp.astimezone(ZoneInfo("America/New_York"))
    day = local.weekday()
    clock = local.time()
    return (
        day < 4
        or day == 4
        and clock < time(16, 55)
        or day == 6
        and clock >= time(17, 3)
    )


def slot_tradable(stamp, seconds=300):
    return instant_open(stamp) or instant_open(
        stamp + timedelta(seconds=seconds, microseconds=-1)
    )


def unexpected_broker_gap(previous, current, seconds):
    difference = (current.timestamp - previous.timestamp).total_seconds()
    if difference <= 0 or difference % seconds:
        return True
    stamp = previous.timestamp + timedelta(seconds=seconds)
    while stamp < current.timestamp:
        if slot_tradable(stamp, seconds):
            return True
        stamp += timedelta(seconds=seconds)
    return False
