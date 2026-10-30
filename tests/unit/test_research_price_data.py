from datetime import timedelta
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,PropertyMock

from aurelia_fx.offline_integrity import canonical,sha256
from aurelia_fx.research_price.context import PriceContext
from aurelia_fx.research_price.replay import load_rows,run_window
from tests.unit.test_research_price import D,bar,params,signal,scripted


class DataTests(unittest.TestCase):
    def load_fixture(self,rows,mutate=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=b''.join(json.dumps(b).encode()+b'\n' for b in rows)
            (root/'bars.jsonl').write_bytes(raw)
            index={'bars.jsonl':sha256(raw)};index_raw=canonical(index)
            (root/'artifact_hashes.json').write_bytes(index_raw)
            p=params();p['source']=dict(bundle=str(root),index_sha256=sha256(index_raw),files=index,
                source='synthetic',clock_id='clockA',symbol='TEST',time_contract='UTC')
            if mutate:mutate(root,p)
            return load_rows(p)

    def test_mixed_clock_origin_or_contract_is_rejected(self):
        for key in ['clock_id','source','time_contract']:
            with self.subTest(key=key):
                changed=bar(1);changed[key]='OTHER'
                with self.assertRaisesRegex(ValueError,'MIXED_SOURCE_CLOCK_OR_CONTRACT'):
                    self.load_fixture([bar(0),changed])

    def test_tampered_file_or_index_is_rejected_before_pnl(self):
        def change_file(root,p):(root/'bars.jsonl').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'INPUT_HASH_MISMATCH'):
            self.load_fixture([bar(0)],change_file)
        def change_index(root,p):(root/'artifact_hashes.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'INPUT_INDEX_CHANGED'):
            self.load_fixture([bar(0)],change_index)

    def test_duplicate_time_invalid_ohlc_and_invalid_spread_fail_closed(self):
        for rows in [[bar(0),bar(0)],[bar(0,low=12.)],[bar(0,spread_pips=-1.)]]:
            with self.subTest(rows=rows),self.assertRaises(ValueError):self.load_fixture(rows)

    def test_no_labels_from_next_partition_change_previous_partition(self):
        p=params();window=dict(name='first',start=D.isoformat(),end=bar(6)['timestamp'])
        rows=[bar(i) for i in range(6)]
        later=[bar(i,high=1000,low=.01) for i in range(6,20)]
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            a=run_window(rows,p,window,proposer=scripted)
            b=run_window(rows+later,p,window,proposer=scripted)
        self.assertEqual(a,b)
        self.assertEqual(a['trades'][0]['reason'],'PARTITION_END')

    def test_session_end_forces_flat_without_overnight_carry(self):
        p=params();p['session']['end_hour_utc']=9
        rows=[bar(i) for i in range(15)]
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            result=run_window(rows,p,p['partitions'][0],proposer=scripted)
        self.assertEqual(result['trades'][0]['reason'],'SESSION_END')
        self.assertEqual(result['trades'][0]['observed_at'],(D+timedelta(hours=1)).isoformat())

    def test_impulse_not_reused_after_first_fill(self):
        p=params()
        def repeat(context,p):return signal(context.bars[-1]['closed_at'] and D+timedelta(minutes=5*len(context.bars))),None
        rows=[bar(i) for i in range(30)]
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            result=run_window(rows,p,p['partitions'][0],proposer=repeat)
        self.assertEqual(len(result['trades']),1)
        self.assertGreater(result['summary']['reason_counts']['IMPULSE_ALREADY_USED'],0)

    def test_real_context_end_to_end_without_mocks_produces_causal_entry_and_exit(self):
        # Artificial market deliberately exercises a complete pattern; no real outcomes or tuning.
        p=params();p['warmup_contiguous_m5']=240
        baseline=[]
        wave=[0,1,3,1,0]
        for i in range(240):
            hour=i//12;v=80+hour*.3+wave[hour%5]
            baseline.append(bar(i-240,open=v,close=v,high=v+.4,low=v-.4))
        rows=[bar(i,open=104.4,close=104.4,low=104.1,high=104.6) for i in range(40)]
        rows[10]=bar(10,open=104.4,close=104.4,low=104.1,high=105)
        rows[15]=bar(15,open=104.4,close=104.4,low=95,high=104.6)
        rows[20]=bar(20,open=101,close=101,low=100,high=101.5)
        for i in range(21,26):
            o=101+2*(i-21);cl=min(110,o+2);rows[i]=bar(i,open=o,close=cl,low=o-.1,high=cl)
        for i in range(26,39):rows[i]=bar(i,open=104.5,close=104.4,low=104 if i==30 else 104.1,high=104.6)
        rows[39]=bar(39,open=104.1,close=104.3,low=104,high=104.4)
        rows.extend([bar(40,open=104.45,high=105,low=104.2,close=104.8),
                     bar(41,open=104.8,high=110.2,low=104.7,close=110)])
        window=dict(name='synthetic_integrated',start=baseline[0]['timestamp'],end=rows[-1]['closed_at'])
        result=run_window(baseline+rows,p,window)
        self.assertEqual(len(result['trades']),1,result['summary'])
        t=result['trades'][0]
        self.assertEqual(t['status'],'CLOSED');self.assertEqual(t['reason'],'TARGET')
        self.assertEqual(t['signal_at'],rows[39]['closed_at'])
        self.assertEqual(t['entry_bar_open_at'],rows[40]['timestamp'])
        self.assertTrue(result['decisions'][279]['h1_bullish'])
        # Extending beyond this frozen boundary cannot amend its decisions/events/results.
        extended=run_window(baseline+rows+[bar(42,high=1000,low=.1)],p,window)
        self.assertEqual(result,extended)

    def test_uncertain_entry_local_scenarios_are_not_horizon_bounds(self):
        rows=[bar(0),bar(1,open=9.7,low=8.9,high=10.5,close=10.2),bar(2,open=8,low=7,high=9,close=8)]
        p=params()
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            result=run_window(rows,p,p['partitions'][0],proposer=scripted)
        trade=result['trades'][0]
        self.assertIsNone(trade['net_pnl_usd']);self.assertIsNone(trade['lower_net_usd'])
        self.assertIsNone(trade['upper_net_usd']);self.assertFalse(trade['local_scenarios_exhaustive'])
        self.assertIn('local_stop_net_usd',trade)

    def test_intrabar_entry_and_rr_rejection_observed_at_close_not_open(self):
        p=params();rows=[bar(0),bar(1,open=9.7,low=9.5,high=10.5,close=10.2),bar(2)]
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            result=run_window(rows,p,p['partitions'][0],proposer=scripted)
        entry=next(e for e in result['events'] if e['kind']=='SCENARIO_ENTRY')
        self.assertIsNone(entry['entry_at']);self.assertEqual(entry['observed_at'],rows[1]['closed_at'])
        rows[1]=bar(1,open=13.9,high=14.1,low=13.8,close=14)
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            result=run_window(rows,p,p['partitions'][0],proposer=scripted)
        rejection=next(e for e in result['events'] if e.get('reason')=='FILL_GEOMETRY_OR_RR')
        self.assertEqual(rejection['at'],rows[1]['closed_at'])
