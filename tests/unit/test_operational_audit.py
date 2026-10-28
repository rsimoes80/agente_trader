"""The operational audit must not inspect reserved/future candles."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch
import hashlib
import pytest

from aurelia_fx.operational_audit import scan, verify_partition
from aurelia_fx.domain import Candle
from aurelia_fx.replay import encode


def row(at):
    return dict(timestamp=at.isoformat(),open=1.1,high=1.101,low=1.099,close=1.1,volume=100,spread_pips=1)


class Session:
    def __init__(self):
        self.last=None;self.history=[];self.calls=[]
        self.aggregator=NS(history={'D1':list(range(20))})
    def update(self,rows,*,spread_pips,observed_at,warmup_only):
        r=rows[0];self.calls.append((r['timestamp'],observed_at,warmup_only))
        self.last=NS(timestamp=datetime.fromisoformat(r['timestamp']))
        self.history.append(self.last)
        return NS(regime='UNKNOWN',session=(),invalidating_evidence=(),
                  as_dict=lambda:dict(regime_state={},macro_trend={},context_trend={}))


def test_warmup_is_past_only_and_holdout_is_never_processed():
    a=datetime(2026,1,5,8,tzinfo=timezone.utc)
    rows=[row(a+timedelta(minutes=5*i)) for i in range(6)]
    # Invalid future data would fail parsing/validation if the audit inspected it.
    rows[4]['open']=-100
    session=Session()
    with patch('aurelia_fx.operational_audit.intelligence_session',return_value=session), patch('aurelia_fx.operational_audit.propose_pullback',return_value=(None,'BLOCKED')) as propose:
        result=scan(rows,start=a+timedelta(minutes=10),end=a+timedelta(minutes=20))
    assert result['warmup_bars']==2
    assert result['evaluated_bars']==2
    assert result['reasons']=={'BLOCKED':2}
    assert [c[2] for c in session.calls]==[True,True,False,False]
    assert len(session.calls)==4
    assert propose.call_count==2
    assert all(c[1]==datetime.fromisoformat(c[0])+timedelta(minutes=5) for c in session.calls)


def test_audit_never_relaxes_production_gates():
    a=datetime(2026,1,5,8,tzinfo=timezone.utc)
    session=Session()
    with patch('aurelia_fx.operational_audit.intelligence_session',return_value=session), patch('aurelia_fx.operational_audit.propose_pullback',return_value=(None,'TREND_REGIME_REQUIRED')) as propose:
        result=scan([row(a)],start=a,end=a+timedelta(minutes=5))
    assert result['samples']==[]
    assert propose.call_args.kwargs=={'daily_history':list(range(20))}
    assert not result['cumulative_funnel']


def test_original_partition_rejects_revised_prices_even_when_count_is_equal():
    a=datetime(2026,1,5,8,tzinfo=timezone.utc)
    rows=[row(a)]
    candle=Candle(a,1.1,1.101,1.099,1.1,100,1)
    digest=hashlib.sha256((encode(candle.as_dict())+'\n').encode()).hexdigest()
    partition=dict(first_open=a.isoformat(),last_open=a.isoformat(),bars=1,sha256=digest)
    assert verify_partition(rows,partition)==digest
    rows[0]['high']=1.102
    with pytest.raises(ValueError,match='revisão'):
        verify_partition(rows,partition)
