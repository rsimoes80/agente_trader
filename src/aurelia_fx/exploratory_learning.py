"""Prospective, costed research of technical candidates blocked by entry policy.

This namespace has no promotion, model selection or broker authority. It reuses
the existing simulator and objective hypothesis review, never production stats.
"""
from datetime import timedelta
from dataclasses import replace

from .agent_model import fingerprint
from .agent_research import request_for
from .broker_calendar import unexpected_broker_gap
from .entry_trend import entry_blocker
from .historical.core import utc
from . import hypothesis_review

VERSION = 'exploratory-pullback-v1'


def initialize(parent, at):
    return parent.setdefault('exploratory', dict(
        version=VERSION, units=parent['units'], registered_at=utc(at).isoformat(),
        last_bar=None, last_signal=None, candidates=0, submitted=0, busy=0,
        closed=0, censored=0, rejected=0, net_pnl=0., wins=0,
        policy_blocks={}, portfolio=None, forecast_errors=0))


def advance(parent, bar, at, active_sessions):
    from .continual_learning import decode_sim, encode_sim
    if bar.timestamp + timedelta(minutes=5) > utc(at):
        return
    state = initialize(parent, at)
    if bar.timestamp + timedelta(minutes=5) <= utc(state['registered_at']):
        return
    if state['last_bar'] and bar.timestamp <= utc(state['last_bar']):
        return
    valid = True
    if state['last_bar']:
        from .domain import Candle
        valid = not unexpected_broker_gap(
            Candle(utc(state['last_bar']), bar.open, bar.open, bar.open, bar.open), bar, 300)
    hypothesis_review.advance_portfolios(state, bar, valid, active_sessions)
    sim = decode_sim(state['portfolio'], state['units'])
    for event in sim.advance(bar, data_valid=valid, active_sessions=active_sessions):
        if event['status'] == 'closed':
            f = event['financial_result']
            result = dict(variant='baseline', context=event['intelligence_context']['learning_context'],
                entry_at=event['entry_at'], exit_at=event['observed_at'],
                net_pnl=f['net_pnl'], result_in_r=f['result_in_r'],
                scope='exploratory_shadow_not_broker', event_id=event['event_id'])
            hypothesis_review.review(state, event, result)
            state['closed'] += 1
            state['net_pnl'] += f['net_pnl']
            state['wins'] += int(f['net_pnl'] > 0)
        elif event['status'] == 'censored':
            state['censored'] += 1
        elif event['status'] == 'rejected':
            state['rejected'] += 1
    if not valid or sim.account_locked:
        review = hypothesis_review.state_for(state)
        review['reviews'] = []
        if review['proposal'] and review['proposal']['status'] == 'COLLECTING_FUTURE':
            review['proposal']['status'] = 'INVALIDATED_DATA_GAP'
    sim.events.clear()
    # Censored exposure never becomes a gain/loss. Resume a fresh research
    # account only after recording the invalidation; broker state is unrelated.
    state['portfolio'] = None if sim.account_locked else encode_sim(sim)
    state['last_bar'] = bar.timestamp.isoformat()
    hypothesis_review.evaluate(state, at)


def consider(parent, setup, features):
    from .continual_learning import context, decode_sim, encode_sim
    state = parent.get('exploratory')
    if not state or utc(setup['signal_at']) <= utc(state['registered_at']):
        return
    if state['last_signal'] and utc(setup['signal_at']) <= utc(state['last_signal']):
        return
    state['last_signal'] = setup['signal_at']
    state['candidates'] += 1
    block = entry_blocker(setup['snapshot'], setup['candidate'].side) or 'PRODUCTION_ELIGIBLE'
    state['policy_blocks'][block] = state['policy_blocks'].get(block, 0) + 1
    key = VERSION + '|' + context(setup)
    hypothesis_review.consider_portfolios(state, setup, features, key)
    sim = decode_sim(state['portfolio'], state['units'])
    if sim.busy or sim.account_locked:
        state['busy'] += 1
        return
    modified = {**setup, 'snapshot': {**setup['snapshot'],
        'learning_context': key, 'production_block': block}}
    if block != 'PRODUCTION_ELIGIBLE':
        modified['candidate'] = replace(setup['candidate'], evidence=tuple(
            fact for fact in setup['candidate'].evidence if fact != 'confirmed_trend_context'
        ) + ('technical_pattern_only_not_confirmed_entry',))
    modified['snapshot']['hypothesis_critique'] = hypothesis_review.critique(modified, features)
    sim.submit(request_for(modified, fingerprint(dict(
        scope=VERSION, registered_at=state['registered_at'], context=key, signal=setup['signal_at']))))
    state['submitted'] += 1
    state['portfolio'] = encode_sim(sim)


def observe(parent, snapshot, history, daily_history, *, at, ready, source, model, forecast):
    """Generate at most one causal technical candidate per fresh closed M5 bar.

    Forecast errors leave explicit missing evidence; they never become zero or
    fabricated directional confirmation. No inference happens without a trigger.
    """
    from .agent_strategy import propose_pullback, attach_forecast
    if not ready:
        return
    state = initialize(parent, at)
    setup, _ = propose_pullback(snapshot, history, daily_history=daily_history, research=True)
    if not setup or utc(setup['signal_at']) <= utc(state['registered_at']):
        return
    if state['last_signal'] and utc(setup['signal_at']) <= utc(state['last_signal']):
        return
    setup.update(learning_source=source, learning_model=model)
    features = setup['features']
    try:
        features = attach_forecast(setup, forecast())
    except (RuntimeError, ValueError, KeyError, OSError) as exc:
        state['forecast_errors'] += 1
        state['last_forecast_error'] = type(exc).__name__
    consider(parent, setup, features)


def summary(parent):
    state = parent.get('exploratory')
    if not state:
        return None
    return {**{k: state[k] for k in ('version', 'registered_at', 'candidates', 'submitted',
        'busy', 'closed', 'censored', 'rejected', 'net_pnl', 'wins', 'policy_blocks', 'forecast_errors')},
        'hypothesis_review': hypothesis_review.summary(state),
        'scope': 'exploratory_shadow_not_broker', 'automatic_activation': False}
