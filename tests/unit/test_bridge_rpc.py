"""Exercise the remote terminal boundary without sending broker orders."""
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from aurelia_fx.bridge_rpc import dispatch
from aurelia_fx.bridge_transport import encode, decode, BridgeClient
from aurelia_fx.demo_terminal import account_identity


def terminal():
    account = SimpleNamespace(login=1, server='Demo', company='Broker', trade_mode=0,
                              trade_allowed=True, trade_expert=True)
    info = SimpleNamespace(path='C:/MT5', trade_allowed=True, tradeapi_disabled=False)
    sdk = SimpleNamespace(ACCOUNT_TRADE_MODE_DEMO=0, TRADE_ACTION_DEAL=1,
        account_info=lambda: account, terminal_info=lambda: info,
        order_send=Mock(return_value=None), shutdown=Mock())
    provider = SimpleNamespace(_LOCK=Lock(), _open_terminal=lambda: {'connected': True}, mt5=sdk)
    return provider, account, info


def send_payload(account, info):
    return dict(operation='sdk.order_send', account_id=account_identity(account, info),
        args=[dict(magic=70616041, action=1, comment='AFX:unique', symbol='EURUSD', volume=.01)])


def test_serialization_preserves_sdk_records_and_datetimes():
    Row = namedtuple('Row', 'ticket at')
    value = decode(encode([Row(123, datetime(2026, 1, 1, tzinfo=timezone.utc))]))
    assert value[0].ticket == 123
    assert value[0].at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_account_change_and_real_account_never_send(tmp_path):
    provider, account, info = terminal()
    payload = send_payload(account, info)
    account.login = 2
    with pytest.raises(ValueError, match='mudou'):
        dispatch(provider, payload, tmp_path/'journal.sqlite3')
    payload = send_payload(account, info)
    account.trade_mode = 2
    with pytest.raises(ValueError, match='DEMO'):
        dispatch(provider, payload, tmp_path/'journal.sqlite3')
    provider.mt5.order_send.assert_not_called()


def test_uncertain_send_is_durable_and_never_repeated(tmp_path):
    provider, account, info = terminal()
    payload = send_payload(account, info)
    dispatch(provider, payload, tmp_path/'journal.sqlite3')
    with pytest.raises(ValueError, match='registrado'):
        dispatch(provider, payload, tmp_path/'journal.sqlite3')
    provider.mt5.order_send.assert_called_once()
    provider.mt5.shutdown.assert_called()


def test_disabled_terminal_and_unknown_method_rejected(tmp_path):
    provider, account, info = terminal()
    info.trade_allowed = False
    with pytest.raises(ValueError, match='indisponível'):
        dispatch(provider, send_payload(account, info), tmp_path/'journal.sqlite3')
    with pytest.raises(ValueError, match='permitida'):
        dispatch(provider, {'operation': 'sdk.login'}, tmp_path/'journal.sqlite3')
    provider.mt5.order_send.assert_not_called()


def test_client_does_not_retry_uncertain_send(monkeypatch):
    from urllib.error import URLError
    call = Mock(side_effect=URLError('connection lost'))
    monkeypatch.setattr('aurelia_fx.bridge_transport.urlopen', call)
    client = BridgeClient('http://127.0.0.1:1', 'test-token')
    with pytest.raises(RuntimeError, match='reconciliar'):
        client.call('sdk.order_send', {})
    call.assert_called_once()
