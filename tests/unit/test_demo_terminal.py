"""Terminal boundary tests: no broker connection or order submission."""
import unittest
from types import SimpleNamespace as NS
from datetime import datetime, timezone
from aurelia_fx.demo_terminal import DemoTerminal
from aurelia_fx.demo_gateway import filling, price_level


class TerminalBoundaryTests(unittest.TestCase):
    def provider(self):
        account=NS(login=123,server='test-demo',company='test',trade_mode=0,
                   currency='USD',trade_allowed=True,trade_expert=True)
        terminal=NS(path='test-terminal',connected=True,trade_allowed=True,tradeapi_disabled=False)
        info=NS(currency_base='EUR',currency_profit='USD')
        sdk=NS(ACCOUNT_TRADE_MODE_DEMO=0,account_info=lambda:account,
               terminal_info=lambda:terminal,symbol_info=lambda _:info,
               positions_get=lambda:(),orders_get=lambda:(),
               symbol_info_tick=lambda _:NS(time=123,bid=1.1,ask=1.1001))
        clock=NS(resolve=lambda *args:dict(clock_id='clock',verified_current=True,
                    tick_utc=datetime.now(timezone.utc).isoformat()))
        return NS(mt5=sdk,_resolve_symbol=lambda _:'EURUSD',_CLOCK=clock),account,terminal

    def test_real_account_and_account_switch_are_rejected(self):
        provider,account,_=self.provider()
        boundary=DemoTerminal(provider)
        account.login=124
        with self.assertRaises(ValueError):boundary.check_account(sending=True)
        account.trade_mode=2
        with self.assertRaises(ValueError):DemoTerminal(provider)

    def test_algo_off_prevents_send_but_not_reconciliation(self):
        provider,_,terminal=self.provider()
        boundary=DemoTerminal(provider)
        terminal.trade_allowed=False
        boundary.check_account()
        with self.assertRaises(RuntimeError):boundary.check_account(sending=True)
        self.assertEqual(boundary.positions(),[])

    def test_failed_position_query_is_not_an_empty_account(self):
        provider,_,_=self.provider()
        boundary=DemoTerminal(provider)
        provider.mt5.positions_get=lambda:None
        with self.assertRaises(RuntimeError):boundary.positions()

    def test_clock_change_stale_quote_and_invalid_prices_block(self):
        provider,_,_=self.provider()
        boundary=DemoTerminal(provider,clock_id='clock')
        self.assertGreater(boundary.quote()['ask'],0)
        provider._CLOCK.resolve=lambda *args:dict(clock_id='other',verified_current=True,
                                                 tick_utc=datetime.now(timezone.utc).isoformat())
        with self.assertRaises(ValueError):boundary.quote()
        provider._CLOCK.resolve=lambda *args:dict(clock_id='clock',verified_current=False,
                                                 tick_utc=datetime.now(timezone.utc).isoformat())
        with self.assertRaises(RuntimeError):boundary.quote()

    def test_broker_filling_flags_are_not_order_filling_enums(self):
        sdk=NS(ORDER_FILLING_FOK=0,ORDER_FILLING_IOC=1,ORDER_FILLING_RETURN=2,
               SYMBOL_TRADE_EXECUTION_MARKET=2)
        self.assertEqual(filling(sdk,NS(filling_mode=1,trade_exemode=2)),0)
        self.assertEqual(filling(sdk,NS(filling_mode=2,trade_exemode=2)),1)
        with self.assertRaises(ValueError):filling(sdk,NS(filling_mode=0,trade_exemode=2))
        self.assertEqual(price_level(1.100019,.00001,up=False),1.10001)
        self.assertEqual(price_level(1.100019,.00001,up=True),1.10002)
