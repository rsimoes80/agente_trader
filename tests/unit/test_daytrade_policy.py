"""Relax context gates without allowing countertrend or unconfirmed H1 entries."""
import copy
from itertools import product
import pytest
from aurelia_fx.entry_trend import entry_blocker,H1_POLICY_ID,CONTINUATION_POLICY_ID,STRICT_POLICY_ID
from aurelia_fx.agent_strategy import propose_pullback
from . import test_agent_strategy


def snapshot(direction='bullish'):
    return dict(regime='UNKNOWN',context_trend=dict(direction=direction,
        state='BULL_CONFIRMED' if direction=='bullish' else 'BEAR_CONFIRMED'),
        macro_trend=dict(direction='neutral',state='TRANSITION'))


@pytest.mark.parametrize('policy',[H1_POLICY_ID,CONTINUATION_POLICY_ID])
def test_direction_always_follows_confirmed_h1_regardless_of_regime_or_h4(policy):
    for direction,regime,h4 in product(('bullish','bearish'),('TREND','RANGE','TRANSITION','UNKNOWN'),('bullish','bearish','neutral')):
        s=snapshot(direction);s['regime']=regime;s['macro_trend']['direction']=h4
        allowed='long' if direction=='bullish' else 'short'
        assert entry_blocker(s,allowed,policy=policy) is None
        assert entry_blocker(s,'short' if allowed=='long' else 'long',policy=policy)=='COUNTERTREND_ENTRY_BLOCKED'
        for state in ('POTENTIAL_BULL','POTENTIAL_BEAR','BULL_WEAKENING','BEAR_WEAKENING','TRANSITION','UNKNOWN',None):
            altered=copy.deepcopy(s);altered['context_trend']['state']=state
            assert entry_blocker(altered,allowed,policy=policy)=='TREND_CONFIRMATION_REQUIRED'


def test_unknown_policy_fails_closed_and_original_remains_explicit():
    assert entry_blocker(snapshot(),'long',policy='anything')=='UNKNOWN_ENTRY_POLICY'
    assert entry_blocker(snapshot(),'long',policy=STRICT_POLICY_ID)=='TREND_REGIME_REQUIRED'


def test_continuation_can_trigger_without_breaking_previous_extreme():
    s,history,daily=test_agent_strategy.AgentStrategyTests().context()
    s.context_trend=dict(direction='bullish',state='BULL_CONFIRMED')
    s.as_dict=lambda: {**snapshot(),'session':['london'],'snapshot_id':'synthetic'}
    # Remains below the previous high but closes above prior close, EMA and its open.
    from dataclasses import replace
    history[-2]=replace(history[-2],high=1.102)
    assert propose_pullback(s,history,daily_history=daily,entry_policy=H1_POLICY_ID)[1]=='WAITING_PULLBACK_TRIGGER'
    setup,reason=propose_pullback(s,history,daily_history=daily,entry_policy=CONTINUATION_POLICY_ID)
    assert reason is None and setup['candidate'].side=='long'
    assert setup['policy_eligible']
    assert setup['production_eligible'] == (entry_blocker(s.as_dict(),setup['candidate'].side) is None)


def test_flexible_proposals_keep_data_and_cost_guards():
    s,history,daily=test_agent_strategy.AgentStrategyTests().context()
    s.context_trend=dict(direction='bullish',state='BULL_CONFIRMED')
    s.as_dict=lambda: {**snapshot(),'session':['london'],'snapshot_id':'synthetic'}
    s.invalidating_evidence=('data_invalid',)
    assert propose_pullback(s,history,daily_history=daily,entry_policy=CONTINUATION_POLICY_ID)[1]=='INVALIDATING_EVIDENCE'
    s.invalidating_evidence=()
    from dataclasses import replace
    history[-1]=replace(history[-1],spread_pips=3)
    assert propose_pullback(s,history,daily_history=daily,entry_policy=CONTINUATION_POLICY_ID)[1]=='SPREAD_UNAVAILABLE_OR_HIGH'
