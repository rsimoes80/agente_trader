import copy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,PropertyMock

from aurelia_fx.offline_integrity import canonical,sha256
from aurelia_fx.research_price.context import PriceContext,candidate,closed_at,prefix_trace
from aurelia_fx.research_price.execution import fill,advance,outcome
from aurelia_fx.research_price.replay import BRANCH,load_rows,run,run_window,validate_protocol

D=datetime(2026,1,2,8,tzinfo=timezone.utc)


def params():
    return dict(schema_version=1,experiment_id='synthetic',branch=BRANCH,direction='long_only',
        audit_case_id='synthetic-audit',audit_as_of=D.isoformat(),bar_seconds=300,
        trading_authority=False,model_inference=False,pivot_window=2,warmup_contiguous_m5=22,
        entry_ttl_bars=3,max_holding_bars=12,pip_size=.0001,tick_size=.00001,units=100000,
        costs=dict(slippage_pips_per_market_side=.2,commission_usd_per_million_per_side=35.,swap_financing_usd=0.),
        session=dict(start_hour_utc=8,end_hour_utc=16,weekdays=[0,1,2,3,4],force_flat_at_end=True),
        partitions=[dict(name='retrospective',start=D.isoformat(),end=(D+timedelta(hours=6)).isoformat())])


def bar(i=0,**kw):
    row=dict(timestamp=(D+timedelta(minutes=5*i)).isoformat(),open=10.1,high=10.4,low=9.8,close=10.2,
             spread_pips=2.,source='synthetic',clock_id='clockA',symbol='TEST',timeframe='M5',time_contract='UTC')
    row.update(kw);row['closed_at']=closed_at(row).isoformat();return row


def signal(at=None):
    t=at or D
    return dict(signal_at=t.isoformat(),expires_at=(t+timedelta(minutes=15)).isoformat(),side='long',
                trigger=10.,stop=9.,target=14.,protected_low=8.,leg_id='synthetic-A/B')


def scripted(context,p):
    return (signal(closed_at(context.bars[-1])),None) if len(context.bars)==1 else (None,'NO_SCRIPTED_SETUP')


class ContextTests(unittest.TestCase):
    def test_m5_pivot_is_not_known_at_extreme_or_before_right_bars_close(self):
        c=PriceContext(2);values=[10,11,15,12,11]
        for i,v in enumerate(values):
            c.add(bar(i,open=v,close=v,low=v-.4,high=v+.4))
            if i<4:self.assertEqual(c.pivots,[])
        pivot=[p for p in c.pivots if p['kind']=='high'][0]
        self.assertEqual(pivot['timestamp'],bar(2)['timestamp'])
        self.assertEqual(pivot['confirmed_at'],bar(4)['closed_at'])

    def test_h1_requires_twelve_closed_contiguous_bars_and_late_pivots(self):
        c=PriceContext(2)
        values=[10,11,13,11,10,11,14,12,11,12,15,13,12]
        for hour,v in enumerate(values):
            for j in range(12):
                c.add(bar(hour*12+j,open=v,close=v,high=v+.4,low=v-.4))
                if hour==0 and j<11:self.assertEqual(c.hourly,[])
                if hour<10:self.assertFalse(c.h1_bullish)
        self.assertTrue(c.h1_bullish)
        self.assertTrue(all(p['confirmed_at']<=c.bars[-1]['closed_at'] for p in c.hourly_pivots))

    def test_missing_m5_does_not_create_h1_and_mixed_gap_is_refused(self):
        c=PriceContext(2);c.add(bar(0))
        with self.assertRaisesRegex(ValueError,'CONTIGUOUS'):
            c.add(bar(2))
        trace=prefix_trace([bar(i) for i in range(12) if i!=5],D+timedelta(hours=1))
        self.assertEqual(trace[-1]['contiguous_m5'] if 'contiguous_m5' in trace[-1] else trace[-1]['bars'],6)
        self.assertEqual(trace[-1]['h1_confirmed_pivots'],[])

    def test_prefix_is_invariant_when_future_price_extremes_are_appended(self):
        rows=[bar(i,high=10.4+(i%5),low=9.8-(i%3)*.1) for i in range(70)]
        cut=closed_at(rows[-1]);first=prefix_trace(rows,cut)
        future=[bar(i,high=1000.,low=.1) for i in range(70,100)]
        self.assertEqual(first,prefix_trace(rows+future,cut))

    def test_observable_pattern_has_previous_bar_sma_region_and_frozen_structural_levels(self):
        c=PriceContext(2)
        rows=[bar(i,open=104.4,close=104.4,low=104.1,high=104.6) for i in range(40)]
        rows[15]=bar(15,open=104.4,close=104.4,low=95,high=104.6)
        rows[20]=bar(20,open=101,close=101,low=100,high=101.5)
        for i in range(21,26):
            o=101+2*(i-21);cl=min(110,o+2);rows[i]=bar(i,open=o,close=cl,low=o-.1,high=cl)
        for i in range(26,39):rows[i]=bar(i,open=104.5,close=104.4,low=104.0 if i==30 else 104.1,high=104.6)
        rows[39]=bar(39,open=104.1,close=104.3,low=104,high=104.4)
        c.bars=rows
        c.pivots=[dict(index=i,kind=k,price=v,timestamp=rows[i]['timestamp'],confirmed_at=rows[i+2]['closed_at'])
                  for i,k,v in [(10,'high',105),(15,'low',95),(20,'low',100),(25,'high',110)]]
        c.hourly_pivots=[dict(kind=k,price=v) for k,v in [('high',105),('low',100),('high',106),('low',101)]]
        proposal,reason=candidate(c,params())
        self.assertIsNone(reason)
        self.assertAlmostEqual(proposal['depth'],.6)
        self.assertAlmostEqual(proposal['stop'],104-.00001)
        self.assertEqual(proposal['target'],110)
        self.assertEqual(proposal['correction_min_at'],rows[30]['timestamp'])
        self.assertEqual(proposal['signal_at'],rows[-1]['closed_at'])
        self.assertGreater(proposal['trigger'],rows[-1]['high'])


class ExecutionTests(unittest.TestCase):
    def setUp(self):self.p=params();self.position,error=fill(signal(),bar(),self.p);self.assertIsNone(error)

    def test_costs_reconcile_without_double_charging_spread(self):
        result=outcome(self.position,11.,'TIMEOUT',bar(1),self.p)
        self.assertAlmostEqual(result['gross_pnl_usd'],90000.)
        self.assertAlmostEqual(result['spread_cost_usd'],20.)
        self.assertAlmostEqual(result['slippage_cost_usd'],4.)
        self.assertAlmostEqual(result['commission_usd'],7.)
        self.assertAlmostEqual(result['net_pnl_usd'],89969.)
        self.assertAlmostEqual(result['net_pnl_usd'],(result['exit_price']-result['entry_price'])*100000-7)

    def test_stop_gap_can_exceed_one_r_and_target_gap_gets_no_better_fill(self):
        loss=advance(copy.deepcopy(self.position),bar(1,open=8.5,high=10.,low=8.,close=9.),self.p)
        self.assertEqual(loss['reason'],'STOP_GAP');self.assertLess(loss['result_in_r'],-1)
        gain=advance(copy.deepcopy(self.position),bar(1,open=15.,high=16.,low=14.5,close=15.),self.p)
        self.assertEqual(gain['exit_price'],14.);self.assertEqual(gain['reason'],'TARGET_GAP_LIMIT')
        self.assertAlmostEqual(gain['slippage_cost_usd'],2.)

    def test_intrabar_stop_target_order_is_censored_not_positive_or_negative_point(self):
        result=advance(self.position,bar(1,open=11.,low=8.,high=15.,close=12.),self.p)
        self.assertEqual(result['status'],'CENSORED');self.assertIsNone(result['net_pnl_usd'])
        self.assertLess(result['lower_net_usd'],result['upper_net_usd'])

    def test_unknown_entry_stop_order_is_preserved(self):
        pos,error=fill(signal(),bar(open=9.7,low=8.9,high=10.5,close=10.2),self.p)
        self.assertIsNotNone(pos);self.assertEqual(error,'AMBIGUOUS_ENTRY_ORDER')

    def test_gap_or_spread_cannot_move_stop_or_target_to_force_entry(self):
        pos,error=fill(signal(),bar(open=13.9,high=14.2,low=13.8,close=14.),self.p)
        self.assertIsNone(pos);self.assertEqual(error,'FILL_GEOMETRY_OR_RR')
        pos,error=fill(signal(),bar(spread_pips=None),self.p)
        self.assertIsNone(pos);self.assertEqual(error,'SPREAD_UNAVAILABLE')
        self.assertEqual(signal()['stop'],9.)

    def test_time_is_counted_from_fill_and_levels_precede_timeout(self):
        self.p['max_holding_bars']=2
        self.assertIsNone(advance(self.position,bar(),self.p))
        result=advance(self.position,bar(1,high=15.),self.p)
        self.assertEqual(result['reason'],'TARGET')
        pos,_=fill(signal(),bar(),self.p)
        advance(pos,bar(),self.p)
        self.assertEqual(advance(pos,bar(1),self.p)['reason'],'TIMEOUT')


class RunnerTests(unittest.TestCase):
    def setUp(self):self.p=params();self.window=self.p['partitions'][0]

    def run_script(self,rows,**kw):
        with patch.object(PriceContext,'h1_bullish',new_callable=PropertyMock,return_value=True):
            return run_window(rows,self.p,self.window,proposer=kw.get('proposer',scripted))

    def test_entry_is_only_on_later_bar_after_signal_closed(self):
        result=self.run_script([bar(i) for i in range(3)])
        entry=[e for e in result['events'] if e['kind']=='SCENARIO_ENTRY'][0]
        self.assertEqual(entry['bar_open_at'],bar(1)['timestamp'])
        self.assertEqual(entry['observed_at'],bar(1)['closed_at'])
        self.assertEqual(entry['entry_at'],bar(1)['timestamp'])
        self.assertGreater(entry['at'],bar(0)['timestamp'])
        self.assertEqual(result['trades'][0]['reason'],'PARTITION_END')

    def test_expiration_is_exclusive_before_a_later_breakout(self):
        def short_lived(c,p):
            s=signal(closed_at(c.bars[-1]));s['expires_at']=(utc_time(s['signal_at'])+timedelta(minutes=5)).isoformat()
            return (s,None) if len(c.bars)==1 else (None,'NONE')
        rows=[bar(0),bar(1,open=9.5,high=9.9,low=9.3,close=9.6),bar(2)]
        result=self.run_script(rows,proposer=short_lived)
        self.assertEqual(result['trades'],[])
        self.assertTrue(any(e.get('reason')=='EXPIRED' for e in result['events']))

    def test_h1_must_be_known_bullish_before_fill(self):
        # Proposer stub bypasses signal gating, but the real runner must still veto the fill.
        result=run_window([bar(i) for i in range(3)],self.p,self.window,proposer=scripted)
        self.assertEqual(result['trades'],[])
        self.assertTrue(any(e.get('reason')=='H1_NO_LONGER_BULLISH' for e in result['events']))

    def test_gap_censors_open_exposure_and_resets_warmup(self):
        result=self.run_script([bar(0),bar(1),bar(4),bar(5)])
        self.assertEqual(result['trades'][0]['reason'],'DATA_GAP')
        self.assertIsNone(result['summary']['complete_net_usd'])
        self.assertEqual(result['decisions'][2]['contiguous_m5'],1)

    def test_pending_stop_breach_without_breakout_cancels_after_close(self):
        rows=[bar(0),bar(1,open=9.5,high=9.8,low=8.9,close=9.6),bar(2)]
        result=self.run_script(rows)
        self.assertEqual(result['trades'],[])
        self.assertTrue(any(e.get('reason')=='STOP_OR_STRUCTURE_BEFORE_BREAKOUT' and e['at']==rows[1]['closed_at'] for e in result['events']))

    def test_ambiguous_entry_is_kept_and_quarantines_new_candidates(self):
        rows=[bar(0),bar(1,open=9.7,low=8.9,high=10.5,close=10.2)]+[bar(i) for i in range(2,16)]
        result=self.run_script(rows)
        self.assertTrue(result['trades'][0]['uncertain_entry'])
        self.assertIsNone(result['summary']['complete_net_usd'])
        self.assertGreater(result['summary']['reason_counts']['AMBIGUOUS_ENTRY_QUARANTINE'],0)

    def test_zero_entries_and_partition_isolation_are_valid_results(self):
        rows=[bar(i) for i in range(30)]
        self.p['partitions']=[dict(name='first',start=D.isoformat(),end=bar(10)['timestamp']),
                              dict(name='second',start=bar(10)['timestamp'],end=bar(30)['timestamp'])]
        result=run(rows,self.p)
        self.assertEqual([w['summary']['trades'] for w in result['partitions']],[0,0])
        self.assertEqual(result['partitions'][1]['decisions'][0]['contiguous_m5'],1)
        self.assertIsNone(result['partitions'][0]['summary']['complete_mean_r'])

    def test_warmup_and_window_overlap_are_rejected(self):
        p=params();p['warmup_contiguous_m5']=1
        with self.assertRaisesRegex(ValueError,'WARMUP_TOO_SHORT'):validate_protocol(p)
        p=params();p['partitions'].append(dict(p['partitions'][0]))
        with self.assertRaisesRegex(ValueError,'PARTITIONS'):validate_protocol(p)


def utc_time(t):return datetime.fromisoformat(t)


class CliTests(unittest.TestCase):
    def test_seal_execute_repeatable_and_reject_changed_code_or_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';repo.mkdir();original=Path(__file__).resolve().parents[2]
            files=['run_price_replay.py','src/aurelia_fx/__init__.py','src/aurelia_fx/offline_integrity.py',
                   'src/aurelia_fx/research_price/__init__.py','src/aurelia_fx/research_price/context.py',
                   'src/aurelia_fx/research_price/execution.py','src/aurelia_fx/research_price/replay.py',
                   'tests/unit/test_research_price.py','tests/unit/test_research_price_data.py']
            for name in files:
                dest=repo/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original/name,dest)
            source=root/'source';source.mkdir();rows=[bar(i) for i in range(30)]
            raw=b''.join(json.dumps(b).encode()+b'\n' for b in rows);(source/'bars.jsonl').write_bytes(raw)
            index={'bars.jsonl':sha256(raw)};(source/'artifact_hashes.json').write_bytes(canonical(index))
            p=params();p['source']=dict(bundle=str(source),index_sha256=sha256(canonical(index)),files=index,
                source='synthetic',clock_id='clockA',symbol='TEST',time_contract='UTC')
            experiment=root/'experiment';experiment.mkdir();protocol_raw=canonical(p);protocol_hash=sha256(protocol_raw)
            (experiment/'protocol.json').write_bytes(protocol_raw)
            (experiment/'implementation_notes.md').write_text('synthetic pre-result notes')
            (experiment/'freeze.json').write_bytes(canonical(dict(before_economic_results=True,files={'protocol.json':protocol_hash})))
            args=[sys.executable,str(repo/'run_price_replay.py'),'--experiment',str(experiment),'--protocol-sha256',protocol_hash]
            sealed=subprocess.run(args+['--seal'],capture_output=True,text=True)
            self.assertEqual(sealed.returncode,0,sealed.stderr)
            seal_hash=json.loads(sealed.stdout)['execution_seal_sha256']
            for n in range(2):
                done=subprocess.run(args+['--execute','--execution-seal-sha256',seal_hash,'--output',str(root/f'out{n}')],capture_output=True,text=True)
                self.assertEqual(done.returncode,0,done.stderr)
            self.assertEqual((root/'out0/result.json').read_bytes(),(root/'out1/result.json').read_bytes())
            context_path=repo/'src/aurelia_fx/research_price/context.py'
            original_context=context_path.read_bytes();context_path.write_bytes(original_context+b'\n# changed\n')
            rejected=subprocess.run(args+['--execute','--execution-seal-sha256',seal_hash,'--output',str(root/'bad')],capture_output=True,text=True)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('SEALED_INPUT_OR_CODE_CHANGED',rejected.stderr)
            self.assertFalse((root/'bad').exists())
            context_path.write_bytes(original_context)
            init=repo/'src/aurelia_fx/__init__.py';init.write_bytes(init.read_bytes()+b'\n# changed\n')
            rejected=subprocess.run(args+['--execute','--execution-seal-sha256',seal_hash,'--output',str(root/'bad-init')],capture_output=True,text=True)
            self.assertIn('SEALED_INPUT_OR_CODE_CHANGED',rejected.stderr)
            (experiment/'protocol.json').write_bytes(b'{}')
            rejected=subprocess.run(args+['--seal'],capture_output=True,text=True)
            self.assertIn('PROTOCOL_HASH_CHANGED',rejected.stderr)
