"""Offline audit of strict operational proposals; never imports a broker adapter."""
from collections import Counter
from datetime import timedelta
import hashlib

from .agent_research import intelligence_session
from .agent_strategy import propose_pullback
from .broker_calendar import unexpected_broker_gap
from .historical.core import utc
from .domain import Candle


def verify_partition(rows, partition):
    """Reject revisions of prices, timestamps or counts from the original plan."""
    from .replay import encode
    first, last = utc(partition['first_open']), utc(partition['last_open'])
    candles = [Candle(utc(r['timestamp']), *(r[k] for k in ('open', 'high', 'low', 'close')),
                      r.get('volume', 0), r.get('spread_pips'))
               for r in rows if first <= utc(r['timestamp']) <= last]
    digest = hashlib.sha256(('\n'.join(encode(c.as_dict()) for c in candles) + '\n').encode()).hexdigest()
    if len(candles) != partition['bars'] or digest != partition['sha256']:
        raise ValueError('A revisão do histórico difere da partição original selada.')
    return digest


def scan(rows, *, start, end, progress=lambda **kw: None):
    """Use only past closed candles; earlier rows initialize the live warmup path."""
    start, end = utc(start), utc(end)
    session = intelligence_session()
    reasons, regimes, classifications, funnel = Counter(), Counter(), Counter(), Counter()
    samples, gaps, daily_counts = [], [], []
    warmup = evaluated = 0
    for index, row in enumerate(rows):
        stamp = utc(row['timestamp'])
        if stamp >= end:
            break
        before = session.last
        if before is not None:
            current = Candle(stamp, *(row[k] for k in ('open', 'high', 'low', 'close')),
                             row.get('volume', 0), row.get('spread_pips'))
            if unexpected_broker_gap(before, current, 300):
                gaps.append(dict(before=before.timestamp.isoformat(), after=stamp.isoformat()))
        snapshot = session.update([row], spread_pips=row.get('spread_pips'),
                                  observed_at=stamp + timedelta(minutes=5),
                                  warmup_only=stamp < start)
        if stamp < start:
            warmup += 1
        else:
            evaluated += 1
            daily = session.aggregator.history['D1']
            daily_counts.append(len(daily))
            setup, reason = propose_pullback(snapshot, session.history, daily_history=daily)
            data = snapshot.as_dict()
            regimes[snapshot.regime] += 1
            classification = (data.get('regime_state') or {}).get('features', {}).get('classification_reason')
            classifications[str(classification)] += 1
            checks = (
                ('m5_context', len(session.history) >= 64),
                ('daily_context', len(daily) >= 20),
                ('trend_regime', snapshot.regime == 'TREND'),
                ('confirmed_h4_h1', all(data.get(role, {}).get('state') ==
                     {'bullish': 'BULL_CONFIRMED', 'bearish': 'BEAR_CONFIRMED'}.get(data.get(role, {}).get('direction'), 'INVALID')
                     for role in ('macro_trend', 'context_trend'))),
                ('aligned_h4_h1', data.get('macro_trend', {}).get('direction') == data.get('context_trend', {}).get('direction')),
                ('authorized_session', bool(snapshot.session)),
                ('no_invalidating_evidence', not snapshot.invalidating_evidence),
                ('spread', row.get('spread_pips') is not None and 0 <= row['spread_pips'] <= 2),
            )
            for key, passed in checks:
                if not passed:
                    break
                funnel[key] += 1
            reasons[reason or 'PROPOSAL'] += 1
            if setup:
                candidate = setup['candidate']
                samples.append(dict(sample_id='operational:' + setup['signal_at'],
                    signal_at=setup['signal_at'], entry_at=setup['signal_at'], snapshot=setup['snapshot'],
                    candidate=dict(side=candidate.side, entry=candidate.entry, stop=candidate.stop,
                        target=candidate.target, expires_at=candidate.expires_at.isoformat(),
                        evidence=list(candidate.evidence))))
        if index % 500 == 0:
            progress(processed=index, warmup=warmup, evaluated=evaluated, proposals=len(samples),
                     daily_bars=len(session.aggregator.history['D1']))
    return dict(start=start.isoformat(), end=end.isoformat(), warmup_bars=warmup,
                evaluated_bars=evaluated, reasons=dict(reasons), regimes=dict(regimes),
                regime_classifications=dict(classifications), cumulative_funnel=dict(funnel),
                daily_context=dict(min=min(daily_counts) if daily_counts else None,
                                   max=max(daily_counts) if daily_counts else None),
                unexpected_gaps=gaps, samples=samples)
