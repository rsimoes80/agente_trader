"""Mandatory entry policy; never applies to position exits or reconciliation."""

POLICY_ID = "trend-only-h4-h1-confirmed-v1"


def entry_blocker(snapshot, side=None):
    if not isinstance(snapshot, dict):
        return "TREND_CONTEXT_MISSING"
    if snapshot.get("regime") != "TREND":
        return "TREND_REGIME_REQUIRED"
    directions = []
    for role in ("macro_trend", "context_trend"):
        trend = snapshot.get(role) or {}
        direction = trend.get("direction")
        expected = {"bullish": "BULL_CONFIRMED", "bearish": "BEAR_CONFIRMED"}.get(direction)
        if not expected or trend.get("state") != expected:
            return "TREND_CONFIRMATION_REQUIRED"
        directions.append(direction)
    if directions[0] != directions[1]:
        return "TREND_TIMEFRAME_CONFLICT"
    allowed = "long" if directions[0] == "bullish" else "short"
    if side is not None and side != allowed:
        return "COUNTERTREND_ENTRY_BLOCKED"
    return None
