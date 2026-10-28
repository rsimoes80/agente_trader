"""Deterministic daytrade session/market-close guards; no broker dependency."""
from datetime import time, timedelta
from .sessions import SessionEngine,SessionWindow
from .broker_calendar import instant_open
from .historical.core import utc

SESSIONS=(SessionWindow('london','Europe/London',time(8),time(17)),
          SessionWindow('new_york','America/New_York',time(8),time(17)))


def closing_reason(at, *, profile=None, buffer_minutes=5):
    if type(buffer_minutes) is not int or buffer_minutes<0:
        raise ValueError('Invalid daytrade closing buffer')
    at=utc(at);future=at+timedelta(minutes=buffer_minutes)
    if profile:
        if not profile.allows_entry(at) or not profile.allows_entry(future):
            return 'CALENDAR_CLOSE'
        sessions=SessionEngine(profile.session_windows())
    else:
        if not instant_open(at) or not instant_open(future):
            return 'MARKET_CLOSE'
        sessions=SessionEngine(SESSIONS)
    if not sessions.identify(at).active_sessions or not sessions.identify(future).active_sessions:
        return 'SESSION_CLOSE'
    return None
