import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from aurelia_fx.instruments import InstrumentContract,identity,inspect_contract,symbol_name


class InstrumentsTests(unittest.TestCase):
    def info(self,name='XAUUSD'):
        return SimpleNamespace(name=name,description='Gold',currency_profit='USD',currency_margin='USD',
            digits=2,point=.01,trade_tick_size=.01,trade_contract_size=100.,volume_min=.01,
            volume_max=10.,volume_step=.01,trade_stops_level=1,trade_calc_mode=4,trade_mode=4)

    def sdk(self):
        sdk=Mock();sdk.symbol_info.return_value=self.info();sdk.symbol_select.return_value=True
        sdk.symbol_info_tick.return_value=SimpleNamespace(bid=4020.,ask=4020.2)
        sdk.order_calc_profit.return_value=-.1
        return sdk

    def test_gold_and_gold_247_are_not_the_same_contract(self):
        a=InstrumentContract.from_mt5(self.info(),broker='b',server='s')
        b=InstrumentContract.from_mt5(self.info('XAUUSD247'),broker='b',server='s')
        self.assertNotEqual(a.key,b.key)
        self.assertNotEqual(identity('other','s','XAUUSD'),a.key)
        self.assertEqual(a.tick_size,.01)

    def test_gold_statistics_use_its_price_unit_not_the_euro_pip(self):
        from aurelia_fx.historical.core import describe
        result=describe([dict(high=4001.,low=3999.,volume=10,spread_pips=19)],pip_size=.01)
        self.assertEqual(result['mean_range_pips'],200)
        self.assertEqual(result['mean_spread_pips'],19)

    def test_native_financial_value_not_inferred_from_name_or_tick_value(self):
        sdk=self.sdk();r=inspect_contract(sdk,'XAUUSD',broker='b',server='s')
        self.assertEqual(r['status'],'CONTRACT_VERIFIED')
        self.assertEqual(r['economics']['price_value_per_lot_buy'],100.)
        self.assertIsNone(r['commission'])
        sdk.order_send.assert_not_called()

    def test_exact_symbol_only_no_silent_247_substitution(self):
        sdk=self.sdk();sdk.symbol_info.return_value=self.info('XAUUSD247')
        with self.assertRaises(ValueError):inspect_contract(sdk,'XAUUSD',broker='b',server='s')
        sdk.order_calc_profit.assert_not_called()

    def test_missing_quote_is_not_permission_to_trade(self):
        sdk=self.sdk();sdk.symbol_info_tick.return_value=None
        r=inspect_contract(sdk,'XAUUSD',broker='b',server='s')
        self.assertEqual(r['status'],'WAITING_QUOTE')
        self.assertIsNone(r['economics']);sdk.order_send.assert_not_called()

    def test_invalid_contract_or_profit_calculation_is_blocked(self):
        info=self.info();info.trade_contract_size=0
        with self.assertRaises(ValueError):InstrumentContract.from_mt5(info,broker='b',server='s')
        sdk=self.sdk();sdk.order_calc_profit.return_value=None
        self.assertEqual(inspect_contract(sdk,'XAUUSD',broker='b',server='s')['status'],'WAITING_NATIVE_RISK_CALCULATION')
        for name in ('',' XAUUSD','XAUUSD\n'):
            with self.assertRaises(ValueError):symbol_name(name)


if __name__=='__main__':unittest.main()
