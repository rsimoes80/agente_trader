"""The independent observer cannot reach terminal execution operations."""
from unittest.mock import patch
import pytest
from aurelia_fx.live_observation import ReadOnlyBridgeClient


@pytest.mark.parametrize('operation',['open','sdk.order_send','sdk.order_check','sdk.account_info','clock','login'])
def test_observer_rejects_execution_before_any_network_call(operation):
    with patch('aurelia_fx.bridge_transport.BridgeClient.call') as call:
        client=ReadOnlyBridgeClient('http://127.0.0.1:1','fixture')
        with pytest.raises(ValueError,match='READ_ONLY'):client.call(operation,{})
        call.assert_not_called()


def test_observer_market_query_uses_normal_transport():
    with patch('aurelia_fx.bridge_transport.BridgeClient.call',return_value={'candles':[]}) as call:
        client=ReadOnlyBridgeClient('http://127.0.0.1:1','fixture')
        assert client.call('fetch_history','EURUSD','M5',100)=={'candles':[]}
        call.assert_called_once_with('fetch_history','EURUSD','M5',100)


def test_observer_status_marks_stale_receipt_and_never_reports_order_authority():
    from contextlib import contextmanager
    from datetime import datetime,timedelta,timezone
    from types import SimpleNamespace as NS
    import json
    from aurelia_fx.live_observation import observation_status
    now=datetime(2026,10,28,14,tzinfo=timezone.utc)
    @contextmanager
    def connection():
        row={'payload_json':json.dumps({'status':'OBSERVING','orders_enabled':True}),
             'recorded_at':now-timedelta(minutes=3)}
        yield NS(execute=lambda *args:NS(fetchone=lambda:row))
    result=observation_status(NS(pool=NS(connection=connection)),now=now)
    assert result['status']=='STALE'
    assert result['orders_enabled'] is False
    assert result['heartbeat_age_seconds']==180
