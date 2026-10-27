"""Full preparation routing for a non-EUR instrument; no real SDK invocation."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as N
from unittest.mock import Mock,patch
import unittest

import run_agent
from aurelia_fx.forecasting.config import TimestralConfig
from aurelia_fx.historical.core import TIMEFRAMES
from .test_runtime_profiles import RuntimeProfileTests


class ProfilePreparationTests(unittest.TestCase):
    def setUp(self):
        r=RuntimeProfileTests();r.setUp();self.profile,_=r.calibrate()
        self.state=dict(symbol='XAUUSD',session_id='gold-session',generation=1,desired='running',mode='demo',lot='.01')
        def publish(session,**fields):
            self.state.update({k:v for k,v in fields.items() if not k.startswith('expected_')});return dict(self.state)
        self.memory=N(record_project_data=Mock())
        self.control=N(symbol='XAUUSD',memory=self.memory,status=lambda:dict(self.state),publish=publish,heartbeat=Mock())
        self.repo=N(profile=self.profile,memory=self.memory,symbol='XAUUSD')
        self.stop=N(is_set=lambda:False)
        self.source=dict(symbol='XAUUSD',symbol_contract=self.profile.contract.as_dict(),
                         source_clock=dict(clock_id='clock',profile='thinkmarkets-ny-close-v1'))
        self.fetch=Mock(return_value=self.source)

    def test_gold_captures_thirty_and_sixty_days_and_receives_own_authorization(self):
        requests=[];native_args=[]
        def collect(repo,capture,*,days,full):
            for tf in TIMEFRAMES:capture('XAUUSD',tf,100)
            requests.append(days);now=datetime.now(timezone.utc)
            return dict(baseline_id='fixture:'+str(days),symbol='XAUUSD',profile_id=self.profile.fingerprint,
                clock_id='clock',start=(now-timedelta(days=days)).isoformat(),as_of=now.isoformat(),status='ready',blocker=None,
                timeframes={tf:dict(statistics=dict(bars=100)) for tf in TIMEFRAMES})
        @contextmanager
        def terminal(**kw):
            native_args.append(kw);yield N(account_id='fixture-account',check_account=Mock())
        def warmup(repo,capture,*,clock_id,days):
            capture('XAUUSD','M5',17300)
            return dict(status='ready',start='fixture-start',as_of='fixture-end',baseline_id='warmup')
        config=TimestralConfig(enabled=True,revision='a'*40,local_release='EURUSD-only',local_artifact_sha256='b'*64)
        with patch.object(run_agent,'collect',side_effect=collect), \
             patch('aurelia_fx.historical.collector.collect_warmup',side_effect=warmup) as warm, \
             patch('aurelia_fx.forecasting.config.load_config',return_value=config), \
             patch('aurelia_fx.demo_terminal.demo_terminal',terminal), \
             patch.object(run_agent,'OperationControl',return_value=N(status=lambda:dict(demo_authorization=dict(account_id='fixture-account')))), \
             patch('aurelia_fx.agent_live.run_paper') as live:
            run_agent.prepare(self.control,self.repo,dict(self.state),self.fetch,'worker',self.stop)
        self.assertEqual(requests,[30]);self.assertEqual(warm.call_args.kwargs['days'],60)
        self.assertTrue(all(call.args[0]=='XAUUSD' for call in self.fetch.call_args_list))
        self.assertEqual(native_args[0]['profile'],self.profile)
        self.assertEqual(native_args[0]['account_id'],'fixture-account')
        auth=self.state['demo_authorization']
        self.assertEqual(auth['symbol'],'XAUUSD')
        self.assertEqual(auth['profile_id'],self.profile.fingerprint)
        self.assertEqual(self.state['research_profile']['profile_id'],self.profile.fingerprint)
        self.assertFalse(live.call_args.args[5].local_release)
        self.assertEqual(live.call_args.kwargs['research_policy'].profile,self.profile)

    def test_gold_never_falls_back_to_the_euro_preparation(self):
        with self.assertRaisesRegex(ValueError,'multiativo'):
            run_agent.prepare(self.control,N(profile=None),dict(self.state),self.fetch,'worker',self.stop)
        self.fetch.assert_not_called()

    def test_wrong_returned_symbol_stops_before_importing_history(self):
        self.fetch.return_value={**self.source,'symbol':'EURUSD'}
        with patch.object(run_agent,'collect') as collect:
            with self.assertRaisesRegex(ValueError,'SOURCE_INSTRUMENT_MISMATCH'):
                run_agent.prepare(self.control,self.repo,dict(self.state),self.fetch,'worker',self.stop)
        collect.assert_not_called()

    def test_new_instrument_does_not_enter_legacy_quote_simulator(self):
        with self.assertRaisesRegex(ValueError,'MT5 Demo'):
            run_agent.prepare(self.control,self.repo,{**self.state,'mode':'paper'},self.fetch,'worker',self.stop)
        self.fetch.assert_not_called()
