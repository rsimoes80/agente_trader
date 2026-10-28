"""Phase guard must refuse native execution independently of paper order logic."""
import pytest
from unittest.mock import patch
from aurelia_fx.bridge_transport import bridge_client_type,BridgeClient
from aurelia_fx.live_observation import ReadOnlyBridgeClient
from aurelia_fx.operation_control import OperationControl


def test_read_only_mode_selects_transport_and_unknown_values_fail_closed():
    assert bridge_client_type('0') is BridgeClient
    assert bridge_client_type('1') is ReadOnlyBridgeClient
    for value in ('', 'true', '2', None):
        with pytest.raises(ValueError):bridge_client_type(value)


def test_paper_test_cannot_start_demo_before_touching_database():
    control=OperationControl.__new__(OperationControl)
    control.symbol='EURUSD'
    with patch.dict('os.environ',{'AURELIA_MT5_READ_ONLY':'1'}):
        with pytest.raises(ValueError,match='fase paper'):
            control.command({'action':'START','mode':'demo','lot':'.01'},'synthetic-command-1234',actor='test')
