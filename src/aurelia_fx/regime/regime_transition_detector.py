"""A frozen range breakout requires subsequent closed-bar acceptance."""

from dataclasses import replace


class RegimeTransitionDetector:
    @staticmethod
    def update_breakout(observation, context, candle, *, now, config):
        upper = observation.direction == "BULLISH"
        outside = (
            candle.close > context.upper_boundary
            if upper
            else candle.close < context.lower_boundary
        )
        level = context.upper_boundary if upper else context.lower_boundary
        returned = context.lower_boundary <= candle.close <= context.upper_boundary
        if returned or not outside:
            return replace(
                observation,
                current_status="RETURNED_TO_RANGE" if returned else "FAILED",
                return_inside_range=returned,
                follow_through="failed",
            )
        count = observation.acceptance_bars + 1
        progress = (
            candle.close > observation.displacement + level
            if upper
            else candle.close < level - observation.displacement
        )
        follow = "observed" if progress else observation.follow_through
        status = (
            "CONFIRMED"
            if count >= config.breakout_acceptance_bars and follow == "observed"
            else "DEVELOPING"
        )
        from datetime import datetime

        from ..trend import timeframe_seconds

        elapsed = (
            now - datetime.fromisoformat(observation.breakout_timestamp)
        ).total_seconds() / timeframe_seconds(context.timeframe)
        if elapsed >= config.breakout_lifetime_bars and status != "CONFIRMED":
            status = "EXPIRED"
        touched = candle.low <= level <= candle.high
        return replace(
            observation,
            acceptance_bars=count,
            follow_through=follow,
            retest_status="boundary_tested_outside_close"
            if touched
            else observation.retest_status,
            current_status=status,
        )
