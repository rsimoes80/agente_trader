import copy
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import math
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch

from aurelia_fx.account_pricing import AccountPricing,AccountPricingRepository
from aurelia_fx.agent_live import forced_exit,profile_config
from aurelia_fx.agent_research import simulation_window
from aurelia_fx.forecasting.config import TimestralConfig
from aurelia_fx.historical.core import summarize,readiness,VERSION,percentile
from aurelia_fx.historical.repository import HistoricalRepository
from aurelia_fx.runtime_profiles import calendar_for,calibrate,RuntimeProfileRepository
from .test_instrument_research import profile


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.contract=replace(profile().contract,broker='TF Global Markets (Aust) Pty Ltd',server='ThinkMarkets-Demo')
        self.pricing=AccountPricing('fixture-account',self.contract.broker,self.contract.server,'USD','Standard',
            (self.contract.key,),'2026-10-26T00:00:00+00:00')
        self.start=datetime(2026,9,27,tzinfo=timezone.utc);self.end=self.start+timedelta(days=30)
        self.calendar=calendar_for(self.contract)
        self.rows=[];stamp=self.start;i=0
        while stamp+timedelta(minutes=5)<=self.end:
            if self.calendar.slot_tradable(stamp):
                distance=1+i%9*.1
                self.rows.append(dict(timestamp=stamp.isoformat(),symbol='XAUUSD',open=4000.,close=4000.,
                    high=4000.+distance,low=4000.-distance,volume=100.,spread_pips=10.+i%12))
                i+=1
            stamp+=timedelta(minutes=5)
        self.baseline=dict(symbol='XAUUSD',days=30,start=self.start.isoformat(),as_of=self.end.isoformat(),
            baseline_id='fixture-baseline',clock_id='fixture-clock',price_unit=.01,
            timeframes={'M5':dict(dataset_sha256='fixture-hash')})
        self.economics=dict(source='MT5.order_calc_profit',price_value_per_lot_buy=100.,price_value_per_lot_sell=100.)

    def calibrate(self,rows=None,**kw):
        return calibrate(self.contract,self.pricing,self.baseline,rows or self.rows,economics=kw.get('economics',self.economics))

    def test_extra_context_fetches_only_own_m5_and_preserves_main_baseline(self):
        from aurelia_fx.historical.collector import collect_warmup
        p,_=self.calibrate()
        repo=SimpleNamespace(symbol=p.symbol,profile=p,memory=Mock(),ingest=Mock(return_value=12),
            candles=Mock(return_value=self.rows),record_type=lambda kind:kind+':gold-profile')
        fetch=Mock(return_value=dict(symbol=p.symbol,timeframe='M5',pip_size=.01,candles=self.rows))
        with patch('aurelia_fx.historical.collector.validate_source_clock',return_value=dict(clock_id='clock')):
            result=collect_warmup(repo,fetch,clock_id='clock',days=60,now=self.end)
        self.assertEqual(fetch.call_args.args[:2],('XAUUSD','M5'))
        self.assertEqual(result['profile_id'],p.fingerprint)
        self.assertEqual(repo.memory.record_project_data.call_args.args[0],'historical_warmup:gold-profile')
        self.assertEqual(repo.candles.call_args.kwargs['timeframe'],'M5')
        fetch.return_value['symbol']='EURUSD'
        repo.ingest.reset_mock()
        with patch('aurelia_fx.historical.collector.validate_source_clock',return_value=dict(clock_id='clock')):
            with self.assertRaisesRegex(ValueError,'INSTRUMENT_MISMATCH'):
                collect_warmup(repo,fetch,clock_id='clock',days=60,now=self.end)
        repo.ingest.assert_not_called()

    def test_gold_daily_pause_is_not_a_collection_failure(self):
        from aurelia_fx.learning_evolution import collection_health
        p,_=self.calibrate()
        pause=datetime(2026,10,26,21,30,tzinfo=timezone.utc)
        state=dict(desired='running',state='WAITING_QUOTE',research_profile=p.as_dict())
        self.assertEqual(collection_health(state,dict(available=True),pause)['status'],'MARKET_CLOSED')
        self.assertEqual(collection_health(state,dict(available=True),pause+timedelta(hours=1))['status'],'ERROR')

    def test_profile_uses_native_value_standard_commission_and_only_first_twenty_days(self):
        p,e=self.calibrate()
        self.assertEqual(p.costs.commission_per_lot_side,0.)
        self.assertEqual(p.costs.slippage_price,.02)
        self.assertEqual(p.value_per_price_per_lot,100.)
        past=[r['spread_pips'] for r in self.rows if datetime.fromisoformat(r['timestamp'])+timedelta(minutes=5)<=self.start+timedelta(days=20)]
        self.assertAlmostEqual(p.max_spread_units,2*percentile(past,.95))
        self.assertEqual(e['calibration_bars'],len(past))
        changed=copy.deepcopy(self.rows)
        for r in changed:
            if datetime.fromisoformat(r['timestamp'])>=self.start+timedelta(days=20):
                r['spread_pips']=10000.;r['high']=10000.
        other,_=self.calibrate(changed)
        self.assertEqual(p.fingerprint,other.fingerprint)

    def test_calendar_does_not_silently_treat_gold_247_as_weekday_gold(self):
        with self.assertRaisesRegex(ValueError,'MARKET_CALENDAR_REQUIRED'):
            calendar_for(replace(self.contract,symbol='XAUUSD247'))
        with self.assertRaisesRegex(ValueError,'MARKET_CALENDAR_REQUIRED'):
            calendar_for(replace(self.contract,broker='Unknown'))

    def test_missing_native_probe_is_not_replaced_by_contract_size(self):
        with self.assertRaisesRegex(ValueError,'NATIVE_FINANCIAL_PROBE_REQUIRED'):self.calibrate(economics=None)
        with self.assertRaisesRegex(ValueError,'NATIVE_FINANCIAL_PROBE_REQUIRED'):
            self.calibrate(economics={**self.economics,'price_value_per_lot_sell':90.})

    def test_gold_calendar_coverage_uses_twenty_three_hours(self):
        p,_=self.calibrate();start=datetime(2026,10,19,tzinfo=timezone.utc);end=start+timedelta(days=1)
        rows=[r for r in self.rows if start<=datetime.fromisoformat(r['timestamp'])<end]
        new=summarize(rows,'M5',start=start,as_of=end,days=1,pip_size=.01,profile=p)
        old=summarize(rows,'M5',start=start,as_of=end,days=1,pip_size=.01)
        self.assertEqual(new['expected_bars'],276)
        self.assertEqual(new['coverage'],1.)
        self.assertEqual(old['expected_bars'],288)
        self.assertEqual(new['calendar'],p.calendar.version)

    def test_simulation_and_live_exit_before_daily_break(self):
        p,_=self.calibrate();closing=datetime(2026,10,19,20,55,tzinfo=timezone.utc)
        bar=type('Bar',(),dict(timestamp=closing-timedelta(minutes=5)))()
        active,reason=simulation_window(p,bar,('new_york',))
        self.assertEqual(active,('new_york',));self.assertEqual(reason,'CALENDAR_CLOSE')
        active,_=simulation_window(p,type('Bar',(),dict(timestamp=closing))(),('new_york',))
        self.assertEqual(active,())
        self.assertEqual(forced_exit(dict(desired='running'),dict(at=closing.isoformat()),p),'CALENDAR_CLOSE')
        self.assertEqual(forced_exit(dict(desired='stopped'),dict(at=closing.isoformat()),p),'OPERATOR_STOP')

    def test_global_euro_finetuned_weights_are_not_given_to_gold(self):
        p,_=self.calibrate()
        cfg=TimestralConfig(local_release='fixture',local_artifact_sha256='a'*64)
        gold=profile_config(cfg,p)
        self.assertFalse(gold.local_release)
        self.assertEqual(gold.model,cfg.model)
        self.assertEqual(profile_config(cfg,None),cfg)


@unittest.skipUnless(os.environ.get('TIMESTRAL_TEST_POSTGRES')=='1','PostgreSQL opt-in')
class RuntimeProfileStorageTests(unittest.TestCase):
    def setUp(self):
        from .test_multi_instrument_learning import MultiInstrumentLearningStorageTests
        f=MultiInstrumentLearningStorageTests();f.setUp();self.addCleanup(f.doCleanups)
        self.memory=f.memory;self.c=f.c
        r=RuntimeProfileTests();r.setUp();self.r=r
        self.p,self.e=r.calibrate();AccountPricingRepository(self.memory).record(r.pricing)

    def test_runtime_profile_is_bound_to_its_account_and_exact_symbol(self):
        repo=RuntimeProfileRepository(self.memory);repo.record('fixture-account',self.p,self.e)
        self.assertEqual(repo.latest('fixture-account','XAUUSD'),self.p)
        self.assertIsNone(repo.latest('other','XAUUSD'))
        self.assertIsNone(repo.latest('fixture-account','XAUUSD247'))
        self.c.execute("UPDATE project_records SET payload_sha256='bad' WHERE record_type='instrument_runtime_profile'")
        with self.assertRaisesRegex(ValueError,'STORAGE_INTEGRITY_ERROR'):repo.latest('fixture-account','XAUUSD')

    def test_profile_baselines_are_separate_from_generic_asset_baselines(self):
        repo=HistoricalRepository(self.memory,'XAUUSD',profile=self.p)
        b={**self.r.baseline,'version':VERSION,'profile_id':self.p.fingerprint}
        repo.record_baseline(b)
        self.assertEqual(repo.latest()['profile_id'],self.p.fingerprint)
        self.assertIsNone(HistoricalRepository(self.memory,'XAUUSD').latest())
        with self.assertRaisesRegex(ValueError,'PROFILE_IDENTITY_MISMATCH'):
            repo.record_baseline({**b,'profile_id':'wrong'})
