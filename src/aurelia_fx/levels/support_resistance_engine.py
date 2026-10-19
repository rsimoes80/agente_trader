"""Traceable swing zones; test counts never imply probabilities or strength."""

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from ..structure import analyze_structure
from ..trend import timeframe_seconds


@dataclass(frozen=True)
class PriceLevel:
    level_id: str
    symbol: str
    timeframe: str
    level_type: str
    lower_bound: float
    upper_bound: float
    origin: tuple[dict, ...]
    created_at_utc: str
    first_touch: str
    last_touch: str
    test_count: int
    breakout_status: str
    retest_status: str
    role: str
    parent_structure: str
    source_rule_ids: tuple[str, ...]
    status: str

    def as_dict(self):
        return asdict(self)


class SupportResistanceEngine:
    def __init__(self, *, tolerance: float, ttl_bars: int = 300, swing_window: int = 2):
        if tolerance <= 0 or ttl_bars < 1:
            raise ValueError("Zone tolerance and TTL must be positive.")
        self.tolerance, self.ttl_bars, self.swing_window = (
            tolerance,
            ttl_bars,
            swing_window,
        )

    def evaluate(self, histories, *, symbol: str, now: datetime):
        levels = []
        for tf, bars in histories.items():
            if (
                bars
                and bars[-1].timestamp + timedelta(seconds=timeframe_seconds(tf)) > now
            ):
                raise ValueError("Levels cannot use future or unfinished candles.")
            structure = analyze_structure(
                bars, self.swing_window, bar_seconds=timeframe_seconds(tf)
            )
            groups = []
            for swing in structure.swings:
                matching = next(
                    (
                        g
                        for g in groups
                        if abs(g["center"] - swing.price) <= self.tolerance
                    ),
                    None,
                )
                if matching:
                    matching["origins"].append(asdict(swing))
                else:
                    groups.append({"center": swing.price, "origins": [asdict(swing)]})
            for group in groups:
                origin = group["origins"][0]
                low, high = (
                    group["center"] - self.tolerance,
                    group["center"] + self.tolerance,
                )
                created = datetime.fromisoformat(origin["confirmed_at"])
                role = "resistance" if origin["kind"] == "high" else "support"
                tests = 1
                touched = False
                last_touch = origin["timestamp"]
                broken_at = None
                breakout, retest = "none", "none"
                for bar in bars:
                    if bar.timestamp < created:
                        continue
                    intersects = bar.low <= high and bar.high >= low
                    if intersects and not touched:
                        tests += 1
                        last_touch = bar.timestamp.isoformat()
                    touched = intersects
                    if role == "resistance" and bar.close > high:
                        role, breakout, broken_at = "support", "bullish", bar.timestamp
                    elif role == "support" and bar.close < low:
                        role, breakout, broken_at = (
                            "resistance",
                            "bearish",
                            bar.timestamp,
                        )
                    elif (
                        broken_at
                        and bar.timestamp > broken_at
                        and intersects
                        and (
                            (role == "support" and bar.close > high)
                            or (role == "resistance" and bar.close < low)
                        )
                    ):
                        retest = "observed"
                key = f"{symbol}:{tf}:{origin['kind']}:{origin['timestamp']}:{group['center']}"
                identity = hashlib.sha256(key.encode()).hexdigest()[:24]
                expired = (
                    now - created
                ).total_seconds() > self.ttl_bars * timeframe_seconds(tf)
                levels.append(
                    PriceLevel(
                        identity,
                        symbol,
                        tf,
                        "confirmed_swing_zone",
                        low,
                        high,
                        tuple(group["origins"]),
                        created.isoformat(),
                        origin["timestamp"],
                        last_touch,
                        tests,
                        breakout,
                        retest,
                        role,
                        structure.direction,
                        ("engineering.confirmed_swing_zone.v1",),
                        "expired" if expired else "active",
                    )
                )
        return tuple(levels)

    @staticmethod
    def context(
        levels,
        price: float,
        *,
        target: float | None = None,
        side: str | None = None,
        limit: int | None = None,
    ):
        entries = []
        for level in levels:
            if level.status != "active":
                continue
            distance = max(level.lower_bound - price, price - level.upper_bound, 0.0)
            obstacle = bool(
                target is not None
                and (
                    (
                        side == "long"
                        and level.role == "resistance"
                        and price < level.lower_bound < target
                    )
                    or (
                        side == "short"
                        and level.role == "support"
                        and target < level.upper_bound < price
                    )
                )
            )
            entries.append(
                {
                    **level.as_dict(),
                    "distance": distance,
                    "interferes_with_target": obstacle,
                }
            )
        entries = sorted(
            entries,
            key=lambda item: (item["distance"], item["timeframe"], item["level_id"]),
        )
        if limit is not None:
            selected = entries[:limit]
            for role, above in (("resistance", True), ("support", False)):
                nearest = next(
                    (
                        z
                        for z in entries
                        if z["role"] == role
                        and (
                            z["lower_bound"] > price
                            if above
                            else z["upper_bound"] < price
                        )
                    ),
                    None,
                )
                if nearest and nearest not in selected:
                    selected.append(nearest)
            entries = selected
        return tuple(entries)
