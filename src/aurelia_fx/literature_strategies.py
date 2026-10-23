"""Four isolated research families. Never imported by the live decision path.

Books motivate concepts; all numerical definitions below are engineering hypotheses.
Only histories of closed candles are accepted. No global regime or H4 veto.
"""
from datetime import timedelta
from statistics import mean

from .domain import Candidate

FAMILIES = ('trend_pullback', 'breakout_retest', 'range_failure', 'reversal_shift')
PARAMETERS = dict(h1_fast=20, h1_slow=50, h1_slope_bars=3, atr=14,
    zone_bars=24, breakout_bars=20, retest_lifetime=6, tolerance_atr=.25,
    buffer_atr=.2, minimum_stop_atr=1., reward_r=3., holding_bars=24,
    range_efficiency_max=.25, range_width_atr_min=2., range_width_atr_max=8.)


def ema(values, period):
    if not values:
        raise ValueError('Empty EMA input')
    value = values[0]
    for price in values[1:]:
        value += 2 / (period + 1) * (price - value)
    return value


def bias(bars):
    if len(bars) < 60:
        return 0
    values = [b.close for b in bars[-150:]]
    fast, slow = ema(values, 20), ema(values, 50)
    slope = fast - ema(values[:-3], 20)
    return 1 if fast > slow and slope > 0 else -1 if fast < slow and slope < 0 else 0


def atr(bars):
    if len(bars) < 15:
        return None
    return mean(max(b.high-b.low, abs(b.high-a.close), abs(b.low-a.close))
                for a, b in zip(bars[-15:-1], bars[-14:]))


def efficiency(bars):
    path = sum(abs(b.close-a.close) for a, b in zip(bars, bars[1:]))
    return abs(bars[-1].close-bars[0].close) / path if path else 0.


def candidate(current, sign, structural_stop, scale, *, target=None):
    """Freeze quote-aware geometry now; actual next-open fills remain risk checked."""
    if sign not in (-1, 1) or not scale or scale <= 0 or current.spread_pips is None:
        return None
    entry = current.close
    stop = min(structural_stop, entry-scale) if sign == 1 else max(structural_stop, entry+scale)
    anticipated = entry + (current.spread_pips*.0001+.00002 if sign == 1 else -.00002)
    distance = sign * (anticipated-stop)
    if distance <= 0:
        return None
    target = target if target is not None else anticipated + sign*3*distance
    if sign*(target-anticipated) <= 0:
        return None
    signal = current.timestamp + timedelta(minutes=5)
    return Candidate('long' if sign == 1 else 'short', entry, stop, target,
        signal+timedelta(minutes=5), ('literature-family-research',))


def setups(histories):
    bars = list(histories.get('M5', []))
    h1 = list(histories.get('H1', []))
    m15 = list(histories.get('M15', []))
    if len(bars) < 64 or len(h1) < 60:
        return {}
    current, previous = bars[-1], bars[-2]
    known = current.timestamp+timedelta(minutes=5)
    for tf, seconds in (('M5', 300), ('M15', 900), ('H1', 3600), ('H4', 14400)):
        if any(b.timestamp+timedelta(seconds=seconds) > known for b in histories.get(tf, [])):
            raise ValueError('Research received unfinished/future context')
    if any((b.timestamp-a.timestamp).total_seconds() != 300 for a,b in zip(bars[-64:-1],bars[-63:])):
        return {}
    if current.spread_pips is None or not 0 <= current.spread_pips <= 2:
        return {}
    scale = atr(bars[:-1])
    if not scale or scale <= 0:
        return {}
    direction = bias(h1)
    output = {}

    def add(family, sign, stop, event, context, target=None):
        proposal = candidate(current, sign, stop, scale, target=target)
        if proposal:
            output[family] = dict(candidate=proposal, event=event, context=context,
                h1_bias=direction, h4_bias=bias(list(histories.get('H4', []))),
                against_h1=bool(direction and sign != direction), known_at=known.isoformat())

    if direction:
        sign = direction
        fast = ema([b.close for b in bars[-100:-1]], 20)
        current_fast = fast + 2/21*(current.close-fast)
        correction = any(sign*(b.close-b.open) < 0 for b in bars[-4:-1])
        touched = min(b.low for b in bars[-4:-1]) <= fast if sign == 1 else max(b.high for b in bars[-4:-1]) >= fast
        extreme = previous.high if sign == 1 else previous.low
        if (correction or touched) and sign*(current.close-extreme) > 0 and sign*(current.close-current_fast) > 0 and sign*(current.close-current.open) > 0:
            stop = min(b.low for b in bars[-5:])-.2*scale if sign == 1 else max(b.high for b in bars[-5:])+.2*scale
            add('trend_pullback', sign, stop, previous.timestamp.isoformat(), 'H1 trend; correction followed by closed resumption')

        # Breakout level is frozen from bars preceding that breakout, never the retest.
        for j in range(len(bars)-2, len(bars)-8, -1):
            anchor = bars[j-20:j]
            level = max(b.high for b in anchor) if sign == 1 else min(b.low for b in anchor)
            crossing = sign*(bars[j].close-level) > 0 and sign*(bars[j-1].close-level) <= 0
            tail = bars[j+1:]
            valid = all(sign*(b.close-level) >= -.25*scale for b in tail)
            touch = current.low <= level+.25*scale if sign == 1 else current.high >= level-.25*scale
            if crossing and valid and touch and sign*(current.close-level) > 0 and sign*(current.close-current.open) > 0 and sign*(current.close-extreme) > 0:
                stop = min(b.low for b in tail)-.2*scale if sign == 1 else max(b.high for b in tail)+.2*scale
                add('breakout_retest', sign, stop, bars[j].timestamp.isoformat(), 'H1 trend; prior breakout and subsequent retest')
                break

    zone = bars[-26:-2]
    low, high = min(b.low for b in zone), max(b.high for b in zone)
    width = (high-low)/scale
    ranging = efficiency(zone) <= .25 and 2 <= width <= 8
    for sign in (1, -1):
        sweep = previous.low < low and previous.close > low if sign == 1 else previous.high > high and previous.close < high
        extreme = previous.high if sign == 1 else previous.low
        resumed = sign*(current.close-extreme) > 0 and sign*(current.close-current.open) > 0
        stop = min(previous.low,current.low)-.2*scale if sign == 1 else max(previous.high,current.high)+.2*scale
        if ranging and sweep and resumed and low < current.close < high:
            target = high-.1*scale if sign == 1 else low+.1*scale
            add('range_failure', sign, stop, previous.timestamp.isoformat(), 'Low-efficiency range; failed edge breakout and return', target=target)
        micro = max(b.high for b in bars[-4:-1]) if sign == 1 else min(b.low for b in bars[-4:-1])
        m15_confirms = bool(m15 and sign*(m15[-1].close-m15[-1].open) > 0)
        if direction == -sign and sweep and resumed and sign*(current.close-micro) > 0 and m15_confirms:
            add('reversal_shift', sign, stop, previous.timestamp.isoformat(), 'Against prior H1 bias; failed extreme, M5 micro break and closed M15 response')
    return output
