import copy
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
import unittest

from aurelia_fx.agent_forecast_view import forecast_view
from aurelia_fx.agent_research import cached_forecast, intelligence_session, request_for, simulator
from aurelia_fx.agent_strategy import propose_pullback
from aurelia_fx.continual_learning import context, decode_sim, encode_sim, check_scope
from aurelia_fx.domain import Candle, Candidate
from aurelia_fx.instrument_research import InstrumentResearchProfile, ResearchCosts, ResearchSession, WeeklySchedule
from aurelia_fx.instruments import InstrumentContract


def profile(symbol='XAUUSD'):
    # Synthetic hours/pricing, not a production broker schedule or tariff.
    contract = InstrumentContract(symbol, 'fixture', 'fixture-broker', 'fixture-demo',
                                  'USD', 'USD', 2, .01, .01, 100., .01, 10., .01, 1, 4, 4)
    return InstrumentResearchProfile(contract, 'USD', .01, 40.,
        WeeklySchedule('fixture-v1', 'America/New_York',
                       tuple((d*1440+8*60, d*1440+17*60) for d in range(5)), 'synthetic fixture'),
        100., ResearchCosts(3., .02, 'synthetic research assumption'),
        sessions=(ResearchSession('london', 'Europe/London', 8*60, 17*60),))


class InstrumentResearchTests(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.at = datetime(2026, 10, 19, 13, tzinfo=timezone.utc)

    def test_frozen_identity_changes_with_asset_broker_calendar_costs_or_units(self):
        p = self.profile
        variants = [profile('XAUUSD247'), replace(p, contract=replace(p.contract, server='other')),
                    replace(p, price_unit=.1), replace(p, costs=replace(p.costs, commission_per_lot_side=4)),
                    replace(p, calendar=replace(p.calendar, version='fixture-v2'))]
        self.assertEqual(p.fingerprint, copy.deepcopy(p).fingerprint)
        for other in variants:
            self.assertNotEqual(p.fingerprint, other.fingerprint)
            self.assertNotEqual(p.learning_namespace, other.learning_namespace)

    def test_missing_costs_never_become_free_trading(self):
        with self.assertRaisesRegex(ValueError, 'COSTS_REQUIRED'):
            simulator('.01', profile=replace(self.profile, costs=None))
        self.assertGreater(self.profile.execution_config('.01').commission_per_million_side, 0)

    def test_profile_roundtrip_is_versioned_and_tampering_is_rejected(self):
        serialized=json.loads(json.dumps(self.profile.as_dict()))
        self.assertEqual(InstrumentResearchProfile.from_dict(serialized),self.profile)
        serialized['costs']['commission_per_lot_side']=0
        with self.assertRaisesRegex(ValueError,'RESEARCH_PROFILE_INTEGRITY_ERROR'):
            InstrumentResearchProfile.from_dict(serialized)

    def test_native_probe_does_not_authorize_historical_currency_conversion(self):
        for p in (replace(self.profile, account_currency='EUR'),
                  replace(self.profile, contract=replace(self.profile.contract, calculation_mode=1)),
                  replace(self.profile, value_per_price_per_lot=99)):
            with self.assertRaisesRegex(ValueError, 'HISTORICAL_INSTRUMENT_VALUATION_REQUIRED'):
                p.execution_config('.01')
        with self.assertRaisesRegex(ValueError, 'NATIVE_PRICE_VALUE_REQUIRED'):
            replace(self.profile, value_per_price_per_lot=None).execution_config('.01')
        with self.assertRaises(ValueError):
            self.profile.execution_config('.015')

    def setup(self, side='long'):
        return dict(candidate=Candidate(side, 4000., 3990. if side=='long' else 4010.,
                    4030. if side=='long' else 3970., self.at+timedelta(hours=1), ('fixture',)),
                    signal_at=self.at.isoformat(), snapshot=dict(snapshot_id='fixture',
                    symbol=self.profile.symbol, profile_id=self.profile.fingerprint,
                    session=['london'], regime='TREND'))

    def bar(self, i=0, **values):
        return Candle(self.at+timedelta(minutes=5*i),
                      *[values.get(k, v) for k, v in dict(open=4000., high=4001., low=3999., close=4000.).items()],
                      100., 20.)

    def test_gold_lot_and_costs_have_correct_dollar_magnitude_both_sides(self):
        for side in ('long', 'short'):
            sim=simulator('.01', profile=self.profile)
            sim.submit(request_for(self.setup(side), side))
            fill=sim.advance(self.bar(), data_valid=True, active_sessions=('london',))[0]
            self.assertEqual(fill['status'], 'filled')
            self.assertEqual(fill['units'], .01)
            self.assertEqual(fill['instrument']['quantity_unit'], 'lots')
            self.assertAlmostEqual(fill['initial_risk'], 10.30 if side=='long' else 10.10)
            result=sim.advance(self.bar(1, high=4031. if side=='long' else 4001.,
                              low=3999. if side=='long' else 3969.),
                              data_valid=True, active_sessions=('london',))[-1]
            f=result['financial_result']
            self.assertAlmostEqual(f['commission'], .06)  # 2 * .01 lot * $3/lot
            self.assertAlmostEqual(f['net_pnl'], 29.72 if side=='long' else 29.92)
            self.assertEqual(result['instrument']['symbol'], 'XAUUSD')

    def test_checkpoint_restores_only_the_same_profile_and_lot(self):
        sim=simulator('.01', profile=self.profile)
        sim.submit(request_for(self.setup(), 'fixture'))
        sim.advance(self.bar(), data_valid=True, active_sessions=('london',))
        data=json.loads(json.dumps(encode_sim(sim)))
        restored=decode_sim(data, '.01', profile=self.profile)
        self.assertEqual(encode_sim(restored), data)
        for args in ({}, {'profile':profile('EURUSD')}, {'profile':replace(self.profile, costs=replace(self.profile.costs, slippage_price=.03))}):
            with self.assertRaisesRegex(ValueError, 'CHECKPOINT_INSTRUMENT_MISMATCH'):
                decode_sim(data, '.01', **args)
        with self.assertRaisesRegex(ValueError, 'CHECKPOINT_INSTRUMENT_MISMATCH'):
            decode_sim(data, '.02', profile=self.profile)

    def test_euro_request_cannot_enter_gold_simulator_or_legacy_learning_portfolio(self):
        setup=self.setup();setup['snapshot']['symbol']='EURUSD'
        with self.assertRaisesRegex(ValueError, 'SIMULATION_INSTRUMENT_MISMATCH'):
            simulator('.01', profile=self.profile).submit(request_for(setup, 'fixture'))
        with self.assertRaisesRegex(ValueError, 'LEARNING_PORTFOLIO_INSTRUMENT_MISMATCH'):
            check_scope({}, self.setup())

    def test_calendar_does_not_infer_a_closure_from_missing_candles(self):
        cal=self.profile.calendar
        self.assertTrue(cal.instant_open(self.at))
        prior=self.bar()
        self.assertTrue(cal.unexpected_gap(prior, self.bar(2), 300))
        friday=datetime(2026,10,23,20,55,tzinfo=timezone.utc)
        monday=datetime(2026,10,26,12,tzinfo=timezone.utc)
        self.assertFalse(cal.unexpected_gap(SimpleNamespace(timestamp=friday),SimpleNamespace(timestamp=monday),300))
        with self.assertRaises(ValueError):cal.instant_open(datetime(2026,10,19,13))

    def test_calendar_handles_summer_winter_and_partial_opening_slots(self):
        cal=self.profile.calendar
        self.assertTrue(cal.instant_open(datetime(2026,1,5,13,tzinfo=timezone.utc)))
        self.assertFalse(cal.instant_open(datetime(2026,1,5,12,tzinfo=timezone.utc)))
        opening=self.at-timedelta(hours=1)
        self.assertTrue(cal.slot_tradable(opening-timedelta(minutes=2),300))
        self.assertFalse(cal.slot_tradable(opening-timedelta(minutes=5),300))
        with self.assertRaises(ValueError):replace(cal,intervals=((10,20),(19,30)))
        mutable=[[0,60]];frozen=replace(cal,intervals=mutable);mutable[0][0]=100
        self.assertEqual(frozen.intervals, ((0,60),))

    def test_profile_intelligence_and_forecast_keep_the_requested_instrument(self):
        session=intelligence_session(profile=self.profile)
        self.assertEqual(session.symbol, 'XAUUSD')
        v=forecast_view(dict(quantiles=[[3999.,4000.,4001.]]*12),[self.bar()],
                        clock_id='fixture', configuration='fixture', generated_at=self.at,
                        symbol='XAUUSD', profile_id=self.profile.fingerprint)
        self.assertEqual(v['symbol'],'XAUUSD')
        self.assertEqual(v['profile_id'],self.profile.fingerprint)

    def test_strategy_rejects_wrong_asset_before_evaluating_a_signal(self):
        with self.assertRaisesRegex(ValueError, 'STRATEGY_INSTRUMENT_MISMATCH'):
            propose_pullback(SimpleNamespace(symbol='EURUSD'),[],profile=self.profile)

    def test_context_does_not_copy_euro_volatility_bands(self):
        setup={**self.setup(), 'atr':4., 'price_unit':.01,
               'learning_namespace':self.profile.learning_namespace}
        self.assertTrue(context(setup).endswith('vol:unclassified'))
        setup['volatility_bands_units']=(300,500)
        self.assertTrue(context(setup).endswith('vol:medium'))
        setup.pop('learning_namespace')
        with self.assertRaisesRegex(ValueError,'LEARNING_NAMESPACE_REQUIRED'):context(setup)

    def test_forecast_cache_does_not_reuse_another_instruments_identical_prices(self):
        class Connection:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,query,args):self.key=args[0];return self
            def fetchone(self):return rows.get(self.key)
        class Memory:
            pool=SimpleNamespace(connection=Connection)
            def record_project_data(self,kind,key,payload):rows[key]=dict(payload_json=json.dumps(payload))
        class Adapter:
            calls=0
            def forecast(self,values):self.calls+=1;return {'quantiles':[[3999.,4000.,4001.]]*12}
        rows={};memory=Memory();adapter=Adapter();cfg=SimpleNamespace(fingerprint='fixture')
        gold=cached_forecast(memory,[self.bar()],cfg,adapter,profile=self.profile)[0]
        euro=cached_forecast(memory,[self.bar()],cfg,adapter)[0]
        self.assertNotEqual(gold,euro)
        cached_forecast(memory,[self.bar()],cfg,adapter,profile=self.profile)
        self.assertEqual(adapter.calls,2)
        rows[gold]['payload_json']=json.dumps({'symbol':'EURUSD','output':{}})
        with self.assertRaisesRegex(ValueError,'FORECAST_INSTRUMENT_MISMATCH'):
            cached_forecast(memory,[self.bar()],cfg,adapter,profile=self.profile)


if __name__=='__main__':unittest.main()
