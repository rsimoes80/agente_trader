"""Synthetic timestamps exercise session, Friday and maximum holding exits."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from aurelia_fx.daytrade import closing_reason
from aurelia_fx.agent_live import forced_exit
from aurelia_fx.agent_paper import PaperAccount
from aurelia_fx.entry_trend import POLICY_ID,STRICT_POLICY_ID
from . import test_agent_paper as fixtures


def utc(value):return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize('before,at,reason',[
 ('2026-10-28T20:54:59','2026-10-28T20:55:00','SESSION_CLOSE'),
 ('2026-10-30T20:49:59','2026-10-30T20:50:00','MARKET_CLOSE'),
 ('2026-11-18T21:54:59','2026-11-18T21:55:00','SESSION_CLOSE'),
 ('2026-11-20T21:49:59','2026-11-20T21:50:00','MARKET_CLOSE'),
])
def test_five_minute_buffer_including_dst_and_friday(before,at,reason):
    assert closing_reason(utc(before)) is None
    assert closing_reason(utc(at))==reason


def test_london_close_does_not_close_while_new_york_remains_open():
    assert closing_reason(utc('2026-10-28T16:55:00')) is None
    assert closing_reason(utc('2026-10-31T12:00:00'))=='MARKET_CLOSE'
    with pytest.raises(ValueError):closing_reason(utc('2026-10-28T12:00:00'),buffer_minutes=-1)


@pytest.mark.skipif(POLICY_ID==STRICT_POLICY_ID,reason='Configured daytrade policy required')
def test_live_exit_and_paper_position_close_on_session_boundary():
    fixture=fixtures.PaperAccountTests();fixture.setUp()
    start=utc('2026-10-28T20:54:30')
    setup={**fixture.setup,'snapshot':{**fixture.setup['snapshot'],'session':['new_york']}}
    setup['candidate']=replace(setup['candidate'],expires_at=start+timedelta(minutes=10))
    account=PaperAccount('synthetic-session-close','.01',fixture.contract,'fixture','clock')
    quote={'at':start.isoformat(),'bid':1.1,'ask':1.1001}
    assert account.open(setup,{},.8,quote,active_sessions=['new_york'])['approved']
    closing={**quote,'at':(start+timedelta(seconds=30)).isoformat()}
    assert forced_exit({'desired':'running'},closing,None)=='SESSION_CLOSE'
    account.mark(closing)
    assert account.data['position'] is None
    assert account.events[-1]['reason']=='SESSION_CLOSE'
    assert not account.open(setup,{},.8,closing,active_sessions=['new_york'])['approved']


@pytest.mark.skipif(POLICY_ID==STRICT_POLICY_ID,reason='Configured daytrade policy required')
def test_paper_maximum_one_hour_exit_is_independent_of_session_end():
    fixture=fixtures.PaperAccountTests();fixture.setUp()
    start=utc('2026-10-28T14:00:00')
    setup={**fixture.setup,'snapshot':{**fixture.setup['snapshot'],'session':['new_york']}}
    setup['candidate']=replace(setup['candidate'],expires_at=start+timedelta(minutes=10))
    account=PaperAccount('synthetic-time-close','.01',fixture.contract,'fixture','clock')
    quote={'at':start.isoformat(),'bid':1.1,'ask':1.1001}
    assert account.open(setup,{},.8,quote,active_sessions=['new_york'])['approved']
    account.mark({**quote,'at':(start+timedelta(hours=1)).isoformat()})
    assert account.data['position'] is None
    assert account.events[-1]['reason']=='TIME_LIMIT'


def test_new_daytrade_proposal_is_rejected_in_closing_buffer():
    from . import test_agent_strategy
    from aurelia_fx.agent_strategy import propose_pullback
    from aurelia_fx.entry_trend import H1_POLICY_ID
    s,history,daily=test_agent_strategy.AgentStrategyTests().context()
    target=utc('2026-10-28T20:50:00');shift=target-history[-1].timestamp
    history=[replace(b,timestamp=b.timestamp+shift) for b in history]
    s.context_trend={'direction':'bullish','state':'BULL_CONFIRMED'}
    s.as_dict=lambda:dict(regime='UNKNOWN',context_trend=s.context_trend)
    setup,reason=propose_pullback(s,history,daily_history=daily,entry_policy=H1_POLICY_ID)
    assert setup is None and reason=='SESSION_CLOSE'
