"""Mandatory direction guard; configured once per worker, never for exits."""
import os

STRICT_POLICY_ID = "trend-only-h4-h1-confirmed-v1"
H1_POLICY_ID = "daytrade-h1-confirmed-v1"
CONTINUATION_POLICY_ID = "daytrade-h1-continuation-v1"
POLICIES = (STRICT_POLICY_ID, H1_POLICY_ID, CONTINUATION_POLICY_ID)
POLICY_ID = os.environ.get('AURELIA_ENTRY_POLICY', STRICT_POLICY_ID)
if POLICY_ID not in POLICIES:
    raise ValueError('Unknown AURELIA_ENTRY_POLICY; worker startup refused.')


def entry_blocker(snapshot, side=None, *, policy=POLICY_ID):
    if policy not in POLICIES:
        return "UNKNOWN_ENTRY_POLICY"
    if not isinstance(snapshot, dict):
        return "TREND_CONTEXT_MISSING"
    if policy == STRICT_POLICY_ID and snapshot.get("regime") != "TREND":
        return "TREND_REGIME_REQUIRED"
    directions = []
    roles = ("macro_trend", "context_trend") if policy == STRICT_POLICY_ID else ("context_trend",)
    for role in roles:
        trend = snapshot.get(role) or {}
        direction = trend.get("direction")
        expected = {"bullish": "BULL_CONFIRMED", "bearish": "BEAR_CONFIRMED"}.get(direction)
        if not expected or trend.get("state") != expected:
            return "TREND_CONFIRMATION_REQUIRED"
        directions.append(direction)
    if len(directions) == 2 and directions[0] != directions[1]:
        return "TREND_TIMEFRAME_CONFLICT"
    allowed = "long" if directions[0] == "bullish" else "short"
    if side is not None and side != allowed:
        return "COUNTERTREND_ENTRY_BLOCKED"
    return None
