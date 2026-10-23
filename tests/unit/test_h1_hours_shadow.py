from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from run_h1_hours_shadow import main


class HoursShadowTests(unittest.TestCase):
    def test_reuses_tape_and_does_not_retroactively_trade_before_registration(self):
        def encode(value):
            text=json.dumps(value,sort_keys=True)
            return text,hashlib.sha256(text.encode()).hexdigest()
        def row(value):
            text,digest=encode(value)
            return dict(payload_json=text,payload_sha256=digest)
        protocol=dict(start='2024-01-15T12:00:00+00:00',selected='exclude_new_york_only')
        old=dict(entry_at='2024-01-15T11:00:00+00:00')
        timely=dict(entry_at='2024-01-15T12:00:00+00:00')
        source=dict(as_of='2024-01-15T12:05:00+00:00',signals=[old,timely],late_signals_not_traded=2)
        bars=[dict(timestamp=f'2024-01-15T{clock}:00+00:00',open=1.1,high=1.101,low=1.099,close=1.1,volume=100,spread_pips=1.2)
              for clock in ('11:55','12:00','12:05')]
        writes=[]
        class Connection:
            def execute(self,sql,args=None):
                if 'pg_try_advisory_lock' in sql:return SimpleNamespace(fetchone=lambda:dict(ok=True))
                if 'pg_advisory_unlock' in sql:return None
                if "record_type='agent_h1_shadow_cycle'" in sql:return SimpleNamespace(fetchone=lambda:row(source))
                if "record_type='agent_h1_shadow_bar'" in sql:return SimpleNamespace(fetchall=lambda:[row(b) for b in bars])
                value=dict(selected='exclude_new_york_only') if args[0]=='agent_h1_hours_selection' else protocol
                return SimpleNamespace(fetchone=lambda:row(value))
        memory=SimpleNamespace(pool=SimpleNamespace(connection=lambda:nullcontext(Connection())),
            _encode=encode,record_project_data=lambda *args:writes.append(args),close=lambda:None)
        result=dict(closed_trades=0,net_pnl=None,censored_trades=1,account_locked=True)
        with patch('sys.argv',['run_h1_hours_shadow.py']),patch('aurelia_fx.storage.open_memory',return_value=memory),\
             patch('run_literature_experiment.simulate',return_value=result) as replay,patch('builtins.print'):
            main()
        self.assertEqual(replay.call_count,8)
        for call in replay.call_args_list:
            signals,candles=call.args
            self.assertEqual(signals,[timely])
            self.assertEqual(len(candles),1)
            self.assertEqual(candles[0].timestamp.isoformat(),'2024-01-15T12:00:00+00:00')
        self.assertEqual(writes[0][0],'agent_h1_hours_shadow_cycle')
        cycle=writes[0][2]
        self.assertEqual(cycle['source_late_signals_not_traded'],2)
        self.assertEqual(cycle['orders_sent'],0)
        self.assertTrue(cycle['results']['reference']['normal']['account_locked'])
