"""Causal price definitions; engineering adaptations, not literal book algorithms."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean


def utc(value):
    t = datetime.fromisoformat(value) if isinstance(value, str) else value
    if t.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return t.astimezone(timezone.utc)


def closed_at(row):
    return utc(row['timestamp']) + timedelta(seconds=300)


def add_pivots(bars, pivots, window):
    """Strict extrema, available at the close of the last right-hand bar."""
    if len(bars) < 2 * window + 1:
        return
    i = len(bars) - 1 - window
    centre = bars[i]
    others = bars[i-window:i] + bars[i+1:i+window+1]
    for kind, field, qualifies in [('high', 'high', all(centre['high'] > b['high'] for b in others)),
                                    ('low', 'low', all(centre['low'] < b['low'] for b in others))]:
        if qualifies:
            pivots.append(dict(index=i, kind=kind, price=centre[field], timestamp=centre['timestamp'],
                               confirmed_at=bars[-1]['closed_at']))


class PriceContext:
    def __init__(self, window):
        self.window = window
        self.bars, self.pivots, self.hourly, self.hourly_pivots = [], [], [], []

    def add(self, row):
        if self.bars and utc(row['timestamp']) - utc(self.bars[-1]['timestamp']) != timedelta(minutes=5):
            raise ValueError('CONTEXT_REQUIRES_CONTIGUOUS_M5')
        self.bars.append({**row, 'closed_at': closed_at(row).isoformat()})
        add_pivots(self.bars, self.pivots, self.window)
        tail = self.bars[-12:]
        if (len(tail) == 12 and int(closed_at(row).timestamp()) % 3600 == 0
                and int(utc(tail[0]['timestamp']).timestamp()) % 3600 == 0):
            self.hourly.append(dict(timestamp=tail[0]['timestamp'], closed_at=closed_at(row).isoformat(),
                open=tail[0]['open'], high=max(b['high'] for b in tail),
                low=min(b['low'] for b in tail), close=tail[-1]['close']))
            add_pivots(self.hourly, self.hourly_pivots, self.window)

    @property
    def h1_bullish(self):
        highs = [p for p in self.hourly_pivots if p['kind'] == 'high']
        lows = [p for p in self.hourly_pivots if p['kind'] == 'low']
        return (len(highs) >= 2 and len(lows) >= 2
                and highs[-1]['price'] > highs[-2]['price']
                and lows[-1]['price'] > lows[-2]['price'])

    def trace(self):
        return dict(at=self.bars[-1]['closed_at'], bars=len(self.bars),
                    h1_bullish=self.h1_bullish,
                    m5_confirmed_pivots=[dict(p) for p in self.pivots],
                    h1_confirmed_pivots=[dict(p) for p in self.hourly_pivots])


def candidate(context, protocol):
    bars = context.bars
    if len(bars) < protocol['warmup_contiguous_m5']:
        return None, 'WARMUP'
    if not context.h1_bullish:
        return None, 'H1_NOT_BULLISH'
    highs = [p for p in context.pivots if p['kind'] == 'high']
    if len(highs) < 2:
        return None, 'M5_HIGH_HISTORY'
    b, prev_high = highs[-1], highs[-2]
    lows = [p for p in context.pivots if p['kind'] == 'low' and p['index'] < b['index']]
    if len(lows) < 2:
        return None, 'M5_LOW_HISTORY'
    a, prev_low = lows[-1], lows[-2]
    if b['price'] <= prev_high['price'] or a['price'] <= prev_low['price'] or b['price'] <= a['price']:
        return None, 'M5_STRUCTURE_NOT_ASCENDING'
    correction = bars[b['index']+1:]
    impulse = bars[a['index']+1:b['index']+1]
    if not correction or not impulse:
        return None, 'LEG_UNDEFINED'
    c = min(correction, key=lambda row: row['low'])  # first minimum wins ties
    if not a['price'] < c['low'] < b['price']:
        return None, 'PROTECTED_LOW_OR_NO_CORRECTION'
    depth = (b['price'] - c['low']) / (b['price'] - a['price'])
    if not 0 < depth < 2/3:
        return None, 'DEPTH'
    impulse_seconds = (utc(b['timestamp']) - utc(a['timestamp'])).total_seconds()
    correction_seconds = (utc(c['timestamp']) - utc(b['timestamp'])).total_seconds()
    if impulse_seconds <= 0 or correction_seconds <= 0:
        return None, 'LEG_DURATION'
    if ((b['price'] - c['low']) / correction_seconds >= (b['price'] - a['price']) / impulse_seconds
            or mean(abs(r['close']-r['open']) for r in correction)
            >= mean(abs(r['close']-r['open']) for r in impulse)):
        return None, 'SPEED_OR_BODY'
    current, prior = bars[-1], bars[:-1]
    if len(prior) < 21:
        return None, 'REGION_HISTORY'
    averages = [mean(r['close'] for r in prior[-period:]) for period in (9, 17, 21)]
    region = [min(averages), max(averages)]
    if current['low'] > region[1] or current['high'] < region[0]:
        return None, 'NO_REGION_CONTACT'
    if current['close'] <= current['open']:
        return None, 'CANDLE_NOT_UP'
    spread = current.get('spread_pips')
    if spread is None:
        return None, 'SPREAD_UNAVAILABLE'
    tick, pip = protocol['tick_size'], protocol['pip_size']
    trigger, stop, target = current['high'] + tick, c['low'] - tick, b['price']
    entry_reference = trigger + spread * pip + protocol['costs']['slippage_pips_per_market_side'] * pip
    if not stop < entry_reference < target or target-entry_reference < 2*(entry_reference-stop):
        return None, 'GROSS_RR_BELOW_2'
    return dict(side='long', signal_at=current['closed_at'],
        expires_at=(utc(current['closed_at'])+timedelta(seconds=300*protocol['entry_ttl_bars'])).isoformat(),
        trigger=trigger, stop=stop, target=target, protected_low=a['price'],
        leg_id=a['timestamp']+'/'+b['timestamp'], region=region,
        impulse_a=dict(a), impulse_b=dict(b), correction_min_at=c['timestamp'],
        correction_min=c['low'], depth=depth, confirmation_open_at=current['timestamp']), None


def prefix_trace(rows, cutoff, window=2):
    """Testing/inspection projection: later bars cannot amend prior observations."""
    context = PriceContext(window)
    result = []
    previous = None
    for row in rows:
        if closed_at(row) > utc(cutoff):
            continue
        if previous is not None and utc(row['timestamp'])-previous != timedelta(minutes=5):
            context = PriceContext(window)
        context.add(row)
        result.append(context.trace())
        previous = utc(row['timestamp'])
    return result
