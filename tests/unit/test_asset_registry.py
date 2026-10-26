import os
import unittest
from uuid import uuid4
from unittest.mock import Mock

from aurelia_fx.asset_registry import AssetRegistry
from aurelia_fx.instruments import InstrumentContract
from aurelia_fx.operation_control import OperationControl
from . import test_operation_control as fixtures


class AssetReadinessTests(unittest.TestCase):
    def test_capability_requires_live_worker_for_the_exact_symbol(self):
        from diagnostic_server import instrument_execution_ready
        w=dict(available=True,heartbeat=dict(symbol='XAUUSD',engine_version='multi-instrument-v1'))
        self.assertTrue(instrument_execution_ready('XAUUSD',w))
        self.assertFalse(instrument_execution_ready('EURJPY',w))
        self.assertFalse(instrument_execution_ready('XAUUSD',{**w,'available':False}))
        self.assertFalse(instrument_execution_ready('XAUUSD',dict(available=True)))


@unittest.skipUnless(os.environ.get('TIMESTRAL_TEST_POSTGRES')=='1','PostgreSQL opt-in')
class AssetRegistryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.OperationPostgresTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.memory=self.fixture.control.memory;self.registry=AssetRegistry(self.memory)

    def snapshot(self,symbol='XAUUSD'):
        c=InstrumentContract(symbol,'Fixture gold','Test','Demo','USD','USD',2,.01,.01,100.,.01,10.,.01,1,4,4)
        return dict(contract=c.as_dict(),status='CONTRACT_VERIFIED',economics=None,account_currency='USD')

    def select(self,symbol='XAUUSD',lot='0.01',key=None,inspect=None):
        return self.registry.command(dict(action='SELECT',symbol=symbol,lot=lot),key or uuid4().hex,inspect or Mock(return_value=self.snapshot(symbol)))

    def test_default_euro_and_gold_configuration_do_not_start_or_replace_sessions(self):
        euro=OperationControl(self.memory);e=euro.command(dict(action='START',lot='0.01'),uuid4().hex,actor='fixture')
        self.select()
        self.assertEqual(euro.status(),e)
        self.assertEqual(OperationControl(self.memory,'XAUUSD').status()['state'],'STOPPED')
        self.assertEqual([r['symbol'] for r in self.registry.list()],['EURUSD','XAUUSD'])

    def test_retry_does_not_repeat_native_inspection_or_append_configuration(self):
        key=uuid4().hex;inspect=Mock(return_value=self.snapshot())
        a=self.select(key=key,inspect=inspect);b=self.select(key=key,inspect=inspect)
        self.assertEqual(a,b);inspect.assert_called_once()
        self.assertEqual(self.fixture.c.execute("SELECT count(*) n FROM project_records WHERE record_type='asset_configuration'").fetchone()['n'],1)
        with self.assertRaises(ValueError):self.select(lot='0.02',key=key,inspect=inspect)

    def test_wrong_broker_symbol_and_invalid_lot_never_persist(self):
        with self.assertRaises(ValueError):self.select(inspect=Mock(return_value=self.snapshot('XAUUSD247')))
        with self.assertRaises(ValueError):self.select(lot='0.015')
        self.assertIsNone(self.registry.get('XAUUSD'))

    def test_active_instrument_cannot_be_removed_or_reconfigured(self):
        self.select();gold=OperationControl(self.memory,'XAUUSD')
        gold.command(dict(action='START',lot='0.01'),uuid4().hex,actor='fixture')
        with self.assertRaises(ValueError):self.select(lot='0.02')
        with self.assertRaises(ValueError):self.registry.command(dict(action='REMOVE',symbol='XAUUSD'),uuid4().hex,Mock())
        gold.command(dict(action='STOP'),uuid4().hex,actor='fixture')
        r=self.registry.command(dict(action='REMOVE',symbol='XAUUSD'),uuid4().hex,Mock())
        self.assertFalse(r['selected'])

    def test_commands_and_generations_are_independent_for_two_assets(self):
        euro=OperationControl(self.memory);gold=OperationControl(self.memory,'XAUUSD');key=uuid4().hex
        e=euro.command(dict(action='START',lot='0.01'),key,actor='fixture')
        g=gold.command(dict(action='START',lot='0.02'),key,actor='fixture')
        self.assertNotEqual(e['session_id'],g['session_id'])
        gold.command(dict(action='PAUSE'),uuid4().hex,actor='fixture')
        self.assertEqual(euro.status()['desired'],'running')
        self.assertIsNone(gold.publish(e['session_id'],state='ANALYZING'))
        self.assertFalse(gold.worker_status()['available'])
        self.assertEqual(euro.status()['symbol'],'EURUSD')
        self.assertEqual(gold.status()['symbol'],'XAUUSD')
        with self.assertRaises(ValueError):gold.command(dict(action='STOP',symbol='EURUSD'),uuid4().hex,actor='fixture')

    def test_started_lot_is_remembered_but_old_session_cannot_overwrite_new_configuration(self):
        self.select();gold=OperationControl(self.memory,'XAUUSD')
        state=gold.command(dict(action='START',lot='0.02'),uuid4().hex,actor='fixture')
        self.registry.remember_session_lot(state)
        self.assertEqual(self.registry.get('XAUUSD')['lot'],'0.02')
        gold.command(dict(action='STOP'),uuid4().hex,actor='fixture')
        self.select(lot='0.03');self.registry.remember_session_lot(state)
        self.assertEqual(self.registry.get('XAUUSD')['lot'],'0.03')

    def test_wrong_symbol_cannot_be_published_as_gold_state(self):
        gold=OperationControl(self.memory,'XAUUSD')
        with self.assertRaises(ValueError):gold.append(self.fixture.c,dict(symbol='EURUSD',state='STOPPED'))

    def test_configured_gold_is_readable_but_cannot_start_before_engine_is_ready(self):
        import json,threading,urllib.request,urllib.error
        from http.server import ThreadingHTTPServer
        from types import SimpleNamespace
        import diagnostic_server as api
        self.select()
        class Handler(api.Handler):
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        server.app=SimpleNamespace(memory=self.memory,assets=self.registry)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base='http://127.0.0.1:'+str(server.server_port)
        with urllib.request.urlopen(base+'/api/diagnostics/agent?symbol=XAUUSD',timeout=5) as r:data=json.load(r)
        self.assertEqual(data['state']['symbol'],'XAUUSD');self.assertFalse(data['execution_ready'])
        request=urllib.request.Request(base+'/api/diagnostics/agent/command',json.dumps(dict(action='START',symbol='XAUUSD',lot='0.01',mode='demo')).encode(),headers={'Content-Type':'application/json','X-Diagnostics-CSRF':data['csrf'],'Idempotency-Key':uuid4().hex})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request,timeout=5)
        self.assertEqual(error.exception.code,400);error.exception.close()
        self.assertEqual(OperationControl(self.memory,'XAUUSD').status()['state'],'STOPPED')


if __name__=='__main__':unittest.main()
