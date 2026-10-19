"""Causal, timeframe-specific regime observations; never an execution permission."""

import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta

from ..replay_data import unexpected_gap
from ..trend import timeframe_seconds
from .models import (
    BreakoutObservation,
    MarketLocation,
    MarketRegimeState,
    RangeContext,
    RegimeConfig,
    RegimeTransition,
)
from .regime_transition_detector import RegimeTransitionDetector


def identity(*parts):
    return hashlib.sha256(":".join(map(str, parts)).encode()).hexdigest()[:24]


class MarketRegimeEngine:
    def __init__(self, config: RegimeConfig | None = None):
        self.config = config or RegimeConfig()
        self.config_hash = hashlib.sha256(
            json.dumps(asdict(self.config), sort_keys=True).encode()
        ).hexdigest()
        self._tracks = {}

    def reset(self):
        self._tracks.clear()

    def evaluate(
        self,
        candles,
        *,
        symbol,
        timeframe,
        now,
        snapshot_id,
        session=(),
        quality_valid=True,
    ):
        cfg = self.config
        seconds = timeframe_seconds(timeframe)
        stamp = now.isoformat()
        key = symbol, timeframe
        track = self._tracks.get(key)
        last = candles[-1] if candles else None
        missing = []
        if not quality_valid:
            missing.append("INVALID_MARKET_DATA")
        if len(candles) < cfg.window:
            missing.append("REGIME_HISTORY_INSUFFICIENT")
        if last and last.timestamp + timedelta(seconds=seconds) > now:
            missing.append("UNCLOSED_OR_FUTURE_CANDLE")
        if last and (now - last.timestamp).total_seconds() > seconds * (
            1 + cfg.maximum_age_periods
        ):
            missing.append("REGIME_DATA_STALE")
        if any(c.timestamp.timestamp() % seconds for c in candles):
            missing.append("TIMEFRAME_MISALIGNED")
        if any(
            b.timestamp <= a.timestamp or unexpected_gap(a, b, seconds)
            for a, b in zip(candles, candles[1:])
        ):
            missing.append("REGIME_HISTORY_GAP_OR_ORDER")
        if track and last and last.timestamp < track["last"]:
            raise ValueError("Cannot rewind a regime session")
        if missing:
            return MarketRegimeState(
                identity(symbol, timeframe, stamp, "unknown"),
                snapshot_id,
                stamp,
                symbol,
                timeframe,
                tuple(session),
                missing_data=tuple(missing),
                classification_status="INVALIDATED" if track else "INSUFFICIENT_DATA",
                detected_at=stamp,
                last_updated_at=stamp,
                expires_at=(now + timedelta(seconds=seconds)).isoformat(),
                regime_model_version=cfg.regime_model_version,
                regime_config_hash=self.config_hash,
                parameters=asdict(cfg),
            )
        signature = identity(last.timestamp, last.open, last.high, last.low, last.close)
        if track and last.timestamp == track["last"]:
            if signature != track["signature"]:
                raise ValueError("Closed candle changed within a regime session")
            return replace(
                track["state"],
                snapshot_id=snapshot_id,
                timestamp_utc=stamp,
                session=tuple(session),
            )
        bars = candles[-cfg.window :]
        displacement = bars[-1].close - bars[0].close
        travel = sum(abs(b.close - a.close) for a, b in zip(bars, bars[1:]))
        efficiency = abs(displacement) / travel if travel else 0.0
        overlaps = [
            max(0, min(a.high, b.high) - max(a.low, b.low))
            / max(a.high - a.low, b.high - b.low)
            if max(a.high - a.low, b.high - b.low) > 0
            else 1.0
            for a, b in zip(bars, bars[1:])
        ]
        overlap = sum(overlaps) / len(overlaps)
        signs = [
            1 if b.close > a.close else -1 if b.close < a.close else 0
            for a, b in zip(bars, bars[1:])
        ]
        alternation = sum(a * b < 0 for a, b in zip(signs, signs[1:])) / max(
            1, len(signs) - 1
        )
        direction = (
            "BULLISH"
            if displacement > 0
            else "BEARISH"
            if displacement < 0
            else "NEUTRAL"
        )
        extremes = sum(
            (b.high > a.high and b.low > a.low)
            if displacement > 0
            else (b.high < a.high and b.low < a.low)
            for a, b in zip(bars, bars[1:])
        ) / (len(bars) - 1)
        high, low = max(c.high for c in bars), min(c.low for c in bars)
        width = high - low
        band = width * cfg.boundary_band_fraction

        def episodes(flags):
            return sum(
                flag and (i == 0 or not flags[i - 1]) for i, flag in enumerate(flags)
            )

        tests = {
            "upper": episodes([b.high >= high - band for b in bars]),
            "lower": episodes([b.low <= low + band for b in bars]),
        }
        range_candidate = (
            width > 0
            and efficiency <= cfg.range_efficiency_max
            and overlap >= cfg.range_overlap_min
            and alternation >= cfg.range_alternation_min
            and min(tests.values()) >= cfg.boundary_tests_min
        )
        trend_candidate = (
            efficiency >= cfg.trend_efficiency_min
            and extremes >= cfg.trend_extreme_fraction_min
        )
        candidate = (
            "RANGE" if range_candidate else "TREND" if trend_candidate else "UNKNOWN"
        )
        if track is None:
            track = {
                "candidate": None,
                "count": 0,
                "range": None,
                "breakout": None,
                "transition": None,
                "state": None,
            }
        track["count"] = (
            track["count"] + 1
            if track["candidate"]
            == (candidate, direction if candidate == "TREND" else "NEUTRAL")
            else 1
        )
        track["candidate"] = candidate, direction if candidate == "TREND" else "NEUTRAL"
        previous = track["state"].regime if track["state"] else "UNKNOWN"
        regime, subtype, status = "UNKNOWN", "UNRESOLVED", "DEVELOPING"
        transition = track["transition"]
        context = track["range"]
        breakout = track["breakout"]
        feature_ids = tuple(
            identity(symbol, timeframe, last.timestamp, name)
            for name in (
                "progress",
                "overlap",
                "alternation",
                "extremes",
                "boundary_tests",
            )
        )
        if context:
            duration = context.range_duration + 1
            upper_touch = (
                last.high
                >= context.upper_boundary
                - context.range_width * cfg.boundary_band_fraction
            )
            lower_touch = (
                last.low
                <= context.lower_boundary
                + context.range_width * cfg.boundary_band_fraction
            )
            counts = dict(context.boundary_test_count)
            counts["upper"] += int(upper_touch and not track.get("upper_touch", False))
            counts["lower"] += int(lower_touch and not track.get("lower_touch", False))
            track["upper_touch"], track["lower_touch"] = upper_touch, lower_touch
            context = replace(
                context,
                range_duration=duration,
                boundary_test_count=counts,
                directional_progress=efficiency,
            )
            if duration >= cfg.range_lifetime_bars:
                context = None
                breakout = None
                track["count"] = 0
                subtype = "RANGE_EXPIRED"
            else:
                regime, subtype, status = (
                    "RANGE",
                    context.status,
                    "STABLE" if context.status == "ESTABLISHED" else "DEVELOPING",
                )
                if breakout and breakout.current_status in {"ATTEMPT", "DEVELOPING"}:
                    breakout = RegimeTransitionDetector.update_breakout(
                        breakout, context, last, now=now, config=cfg
                    )
                    if breakout.current_status in {
                        "FAILED",
                        "RETURNED_TO_RANGE",
                        "EXPIRED",
                    }:
                        context = replace(
                            context,
                            failed_breakouts=context.failed_breakouts
                            + int(breakout.current_status != "EXPIRED"),
                        )
                        transition = replace(
                            transition,
                            status="FAILED"
                            if breakout.current_status != "EXPIRED"
                            else "EXPIRED",
                        )
                        subtype = (
                            "ESTABLISHED"
                            if context.status == "ESTABLISHED"
                            else "DEVELOPING"
                        )
                    elif breakout.current_status == "CONFIRMED":
                        context = replace(
                            context,
                            accepted_breakouts=context.accepted_breakouts + 1,
                            status="EXIT_ACCEPTED",
                        )
                        regime, subtype, status = (
                            "TRANSITION",
                            "RANGE_TO_TREND",
                            "CHANGING",
                        )
                        transition = replace(
                            transition,
                            status="PARTIALLY_CONFIRMED",
                            confirming_evidence=feature_ids,
                        )
                    else:
                        subtype = "BREAKOUT_ATTEMPT"
                elif context.status == "EXIT_ACCEPTED":
                    still_outside = (
                        last.close > context.upper_boundary
                        if breakout.direction == "BULLISH"
                        else last.close < context.lower_boundary
                    )
                    if not still_outside:
                        breakout = replace(
                            breakout,
                            current_status="RETURNED_TO_RANGE",
                            return_inside_range=True,
                        )
                        transition = replace(transition, status="FAILED")
                        context = replace(
                            context,
                            status="ESTABLISHED",
                            failed_breakouts=context.failed_breakouts + 1,
                        )
                        regime, subtype, status = "RANGE", "ESTABLISHED", "STABLE"
                    elif (
                        trend_candidate
                        and direction == breakout.direction
                        and track["count"] >= cfg.confirmation_bars
                    ):
                        regime, subtype, status = (
                            "TREND",
                            "BULL" if direction == "BULLISH" else "BEAR",
                            "STABLE",
                        )
                        transition = replace(transition, status="CONFIRMED")
                        context = None
                    else:
                        regime, subtype, status = (
                            "TRANSITION",
                            "RANGE_TO_TREND",
                            "CHANGING",
                        )
                elif (
                    last.close
                    > context.upper_boundary
                    + context.range_width * cfg.breakout_buffer_fraction
                    or last.close
                    < context.lower_boundary
                    - context.range_width * cfg.breakout_buffer_fraction
                ):
                    up = last.close > context.upper_boundary
                    level = context.upper_boundary if up else context.lower_boundary
                    breakout = BreakoutObservation(
                        identity(context.range_id, stamp, "breakout"),
                        context.range_id,
                        "BULLISH" if up else "BEARISH",
                        level,
                        stamp,
                        abs(last.close - level),
                        "OUTSIDE_ABOVE" if up else "OUTSIDE_BELOW",
                        evidence_ids=feature_ids,
                        acceptance_bars=1,
                    )
                    context = replace(
                        context,
                        upper_break_attempts=context.upper_break_attempts + int(up),
                        lower_break_attempts=context.lower_break_attempts + int(not up),
                    )
                    transition = RegimeTransition(
                        identity(context.range_id, stamp, "transition"),
                        "RANGE",
                        "TREND",
                        stamp,
                        "RANGE_BREAKOUT_ATTEMPT",
                        confirmation_requirements=(
                            "subsequent_closed_bar_acceptance",
                            "follow_through",
                            "persistent_directional_progress",
                        ),
                        invalidation_requirements=(
                            "return_inside_frozen_range",
                            "expiry",
                        ),
                    )
                    subtype, status = "BREAKOUT_ATTEMPT", "PROVISIONAL"
                elif (
                    context.status == "DEVELOPING"
                    and range_candidate
                    and track["count"] >= cfg.confirmation_bars
                ):
                    context = replace(context, status="ESTABLISHED")
                    subtype, status = "ESTABLISHED", "STABLE"
        elif candidate == "RANGE":
            if previous == "TREND":
                regime, subtype, status = "TRANSITION", "TREND_TO_RANGE", "WEAKENING"
                transition = RegimeTransition(
                    identity(symbol, timeframe, stamp, "transition"),
                    "TREND",
                    "RANGE",
                    stamp,
                    "FAILED_TREND_CONTINUATION",
                    confirmation_requirements=("persistent_two_sided_balance",),
                    invalidation_requirements=("renewed_directional_progress",),
                )
            elif (
                previous == "TRANSITION"
                and transition
                and transition.candidate_regime == "RANGE"
                and track["count"] < cfg.confirmation_bars
            ):
                regime, subtype, status = "TRANSITION", "TREND_TO_RANGE", "CHANGING"
            else:
                regime, subtype, status = "RANGE", "DEVELOPING", "DEVELOPING"
                if track["count"] >= cfg.confirmation_bars:
                    subtype, status = "ESTABLISHED", "STABLE"
                    if transition:
                        transition = replace(transition, status="CONFIRMED")
                context = RangeContext(
                    identity(symbol, timeframe, stamp, "range"),
                    symbol,
                    timeframe,
                    stamp,
                    high,
                    low,
                    (high + low) / 2,
                    width,
                    boundary_test_count=tests,
                    directional_progress=efficiency,
                    evidence_ids=feature_ids,
                    status=subtype,
                )
        elif candidate == "TREND" and track["count"] >= cfg.confirmation_bars:
            old_direction = track["state"].direction if track["state"] else direction
            if previous == "TREND" and old_direction not in {
                direction,
                "NEUTRAL",
                "UNDEFINED",
            }:
                regime, subtype, status = "TRANSITION", "UNRESOLVED", "CHANGING"
            else:
                regime, subtype, status = (
                    "TREND",
                    "BULL" if direction == "BULLISH" else "BEAR",
                    "STABLE",
                )
        elif previous in {"TREND", "TRANSITION"}:
            regime, subtype, status = (
                "TRANSITION",
                "TREND_TO_RANGE" if candidate == "RANGE" else "UNRESOLVED",
                "WEAKENING",
            )
            if transition is None or transition.status in {
                "CONFIRMED",
                "FAILED",
                "EXPIRED",
            }:
                transition = RegimeTransition(
                    identity(symbol, timeframe, stamp, "transition"),
                    previous,
                    candidate,
                    stamp,
                    "FAILED_TREND_CONTINUATION",
                    confirmation_requirements=("persistent_classifiable_features",),
                    invalidation_requirements=("candidate_disappears",),
                )
        if transition and transition.status in {
            "SUSPECTED",
            "DEVELOPING",
            "PARTIALLY_CONFIRMED",
        }:
            if (
                now - datetime.fromisoformat(transition.started_at)
            ).total_seconds() >= seconds * cfg.breakout_lifetime_bars:
                transition = replace(transition, status="EXPIRED")
                if regime == "TRANSITION":
                    regime, subtype, status = "UNKNOWN", "UNRESOLVED", "DEVELOPING"
        detected = (
            track["state"].detected_at
            if track["state"] and previous == regime
            else stamp
        )
        previous_regime = (
            track["state"].previous_regime
            if track["state"] and previous == regime
            else previous
        )
        if context:
            location = self.range_location(context, last.close)
            context = replace(context, position_inside_range=location.relative_location)
        features = {
            "efficiency": efficiency,
            "mean_overlap": overlap,
            "alternation": alternation,
            "directional_extremes_fraction": extremes,
            "candidate": candidate,
            "candidate_observations": track["count"],
        }
        features["range_width_acceptable"] = (
            context.range_width >= cfg.minimum_range_width if context else None
        )
        features["observations"] = {
            eid: {
                "feature": name,
                "value": value,
                "dependency_group": "closed_bar_geometry",
            }
            for eid, name, value in zip(
                feature_ids,
                ("progress", "overlap", "alternation", "extremes", "boundary_tests"),
                (efficiency, overlap, alternation, extremes, tests),
            )
        }
        state = MarketRegimeState(
            identity(symbol, timeframe, detected, regime),
            snapshot_id,
            stamp,
            symbol,
            timeframe,
            tuple(session),
            regime,
            subtype,
            direction
            if regime == "TREND"
            else "NEUTRAL"
            if regime == "RANGE"
            else "UNDEFINED",
            previous_regime,
            transition.status if transition else "none",
            "established" if status == "STABLE" else "developing",
            "descriptive_stable" if status == "STABLE" else "uncertain",
            efficiency,
            overlap,
            breakout.current_status if breakout else "not_observed",
            breakout.follow_through if breakout else "not_observed",
            "balance"
            if regime == "RANGE"
            else "directional"
            if regime == "TREND"
            else "undetermined",
            asdict(context) if context else {},
            direction if trend_candidate else "not_established",
            feature_ids,
            classification_status=status,
            detected_at=detected,
            last_updated_at=stamp,
            expires_at=(
                last.timestamp
                + timedelta(seconds=seconds * (1 + cfg.maximum_age_periods))
            ).isoformat(),
            regime_model_version=cfg.regime_model_version,
            regime_config_hash=self.config_hash,
            transition=asdict(transition) if transition else {},
            breakout=asdict(breakout) if breakout else {},
            features=features,
            parameters=asdict(cfg),
        )
        track.update(
            last=last.timestamp,
            signature=signature,
            state=state,
            range=context,
            breakout=breakout,
            transition=transition,
        )
        self._tracks[key] = track
        return state

    def range_location(self, context, price):
        ratio = (price - context.lower_boundary) / context.range_width
        area = self.config.location_area_fraction
        location = (
            "OUTSIDE_ABOVE"
            if ratio > 1
            else "OUTSIDE_BELOW"
            if ratio < 0
            else "LOWER_AREA"
            if ratio <= area
            else "UPPER_AREA"
            if ratio >= 1 - area
            else "MIDDLE_AREA"
        )
        nearest = min(
            (context.lower_boundary, context.upper_boundary),
            key=lambda x: abs(x - price),
        )
        return MarketLocation(
            "RANGE",
            context.timeframe,
            location,
            nearest_range_boundary=nearest,
            distance_to_boundary=abs(nearest - price),
            location_quality="descriptive_unvalidated",
        )

    def location(self, state, price, levels=()):
        context = RangeContext(**state.range_state) if state.range_state else None
        base = (
            self.range_location(context, price)
            if context
            else MarketLocation(state.regime, state.timeframe)
        )
        centers = [
            (z["lower_bound"] + z["upper_bound"]) / 2
            for z in levels
            if z["timeframe"] == state.timeframe
        ]
        nearest = min(centers, key=lambda x: abs(x - price)) if centers else None
        supports = [x for x in centers if x <= price]
        resistances = [x for x in centers if x >= price]
        return replace(
            base,
            regime=state.regime,
            nearest_support=max(supports) if supports else None,
            nearest_resistance=min(resistances) if resistances else None,
            nearest_structural_level=nearest,
            distance_to_structural_level=abs(nearest - price)
            if nearest is not None
            else None,
        )
