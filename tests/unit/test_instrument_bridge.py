import json
import os
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch

import mt5_bridge


class InstrumentBridgeTests(unittest.TestCase):
    def setUp(self):
        self.token=patch.object(mt5_bridge,'TOKEN','fixture-token');self.token.start();self.addCleanup(self.token.stop)
        self.logs=patch.object(mt5_bridge.Handler,'log_message');self.logs.start();self.addCleanup(self.logs.stop)
        self.server=mt5_bridge.BridgeServer(('127.0.0.1',0),mt5_bridge.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def get(self,path,auth=True):
        request=urllib.request.Request(self.base+path,headers={'X-Bridge-Token':'fixture-token'} if auth else {})
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)

    def test_requested_symbol_reaches_provider_without_eurusd_substitution(self):
        with patch.object(mt5_bridge,'fetch_history',return_value={'symbol':'XAUUSD','candles':[]}) as fetch:
            self.assertEqual(self.get('/api/mt5/chart?symbol=XAUUSD&count=100')['symbol'],'XAUUSD')
            self.assertEqual(fetch.call_args.args[0],'XAUUSD')

    def test_catalog_still_requires_private_bridge_authentication(self):
        with patch.object(mt5_bridge,'instrument_catalog') as catalog:
            with self.assertRaises(urllib.error.HTTPError) as error:self.get('/api/mt5/instruments?q=XAU',auth=False)
            self.assertEqual(error.exception.code,403);catalog.assert_not_called()
            error.exception.close()

    def test_catalog_and_exact_contract_are_read_only_routes(self):
        with patch.object(mt5_bridge,'instrument_catalog',return_value={'symbols':[{'symbol':'XAUUSD247'}]}) as catalog:
            self.assertEqual(self.get('/api/mt5/instruments?q=XAU&limit=10')['symbols'][0]['symbol'],'XAUUSD247')
            catalog.assert_called_once_with('XAU','10')
        with patch.object(mt5_bridge,'inspect_instrument',return_value={'status':'CONTRACT_VERIFIED'}) as inspect:
            self.assertEqual(self.get('/api/mt5/instrument?symbol=XAUUSD247')['status'],'CONTRACT_VERIFIED')
            inspect.assert_called_once_with('XAUUSD247')

    def test_rpc_requires_both_token_and_allowed_linux_address(self):
        from aurelia_fx.bridge_transport import BridgeClient
        with patch.dict(os.environ, {'AURELIA_MT5_BRIDGE_LINUX_IP': '127.0.0.2'}), patch.object(mt5_bridge, 'dispatch') as dispatch:
            with self.assertRaises(RuntimeError):
                BridgeClient(self.base, 'fixture-token').call('status')
            dispatch.assert_not_called()
        with patch.dict(os.environ, {'AURELIA_MT5_BRIDGE_LINUX_IP': '127.0.0.1'}), patch.object(mt5_bridge, 'dispatch') as dispatch:
            with self.assertRaises(RuntimeError):
                BridgeClient(self.base, 'wrong-token').call('status')
            dispatch.assert_not_called()

    def test_linux_client_round_trip_preserves_history_arguments(self):
        from aurelia_fx.bridge_transport import BridgeClient
        with patch.dict(os.environ, {'AURELIA_MT5_BRIDGE_LINUX_IP': '127.0.0.1'}), patch.object(mt5_bridge, 'dispatch', return_value={'candles': [], 'symbol': 'XAUUSD'}) as dispatch:
            result = BridgeClient(self.base, 'fixture-token').call('fetch_history', 'XAUUSD', 'M5', 100, include_current=True)
            self.assertEqual(result['symbol'], 'XAUUSD')
            payload = dispatch.call_args.args[1]
            self.assertEqual(payload['args'], ['XAUUSD', 'M5', 100])
            self.assertEqual(payload['kwargs'], {'include_current': True})


if __name__=='__main__':unittest.main()
