import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from aurelia_fx.causal_diagnostic import (
    aggregate_utc_m5, confirmed_pivots, diagnose, load_and_diagnose, prefix, utc,
)
from aurelia_fx.offline_integrity import canonical, sha256

D = datetime(2026, 1, 2, 8, tzinfo=timezone.utc)


def bar(at, *, tf='M5', clock='clock-A', recorded=None, **kwargs):
    return dict(timestamp=at.isoformat(), timeframe=tf, clock_id=clock, symbol='TEST',
                source='synthetic', time_contract='utc-test', open=10., high=12., low=9., close=11.,
                volume=1., recorded_at_utc=(recorded or at + timedelta(minutes=5)).isoformat(), **kwargs)


def case():
    value = dict(schema_version=1, symbol='TEST', side='long', as_of=D.isoformat(), facts={
        'M5.0.timestamp': (D-timedelta(minutes=5)).isoformat(),
        'M5.0.open': 10., 'M5.0.high': 12., 'M5.0.low': 9., 'M5.0.close': 11.,
        'system.context_trend.direction': 'bullish', 'system.context_trend.state': 'BULL_CONFIRMED',
        'system.macro_trend.timestamp_utc': D.isoformat(),
        'system.market_structure.recent_swings.0.kind': 'low',
        'system.market_structure.recent_swings.0.price': 9.,
        'system.market_structure.recent_swings.0.timestamp': (D-timedelta(minutes=15)).isoformat(),
        'system.market_structure.recent_swings.0.confirmed_at': D.isoformat(),
    })
    value['case_id'] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                               allow_nan=False).encode()).hexdigest()
    return value


class CausalTests(unittest.TestCase):
    def test_cut_filters_by_close_and_archive_persistence_inclusively(self):
        closed = bar(D-timedelta(minutes=5))
        not_yet_closed = bar(D)
        later_persisted = bar(D-timedelta(minutes=10), recorded=D+timedelta(seconds=1))
        self.assertEqual(sum(map(len, prefix([closed, not_yet_closed, later_persisted], D).values())), 2)
        known = prefix([closed, not_yet_closed, later_persisted], D, archive=True)
        self.assertEqual([b for v in known.values() for b in v], [closed])

    def test_naive_cutoff_and_conflicting_close_rejected(self):
        with self.assertRaisesRegex(ValueError, 'TIMEZONE_REQUIRED'):
            prefix([], datetime(2026, 1, 1))
        bad = bar(D-timedelta(minutes=5), expected_close_utc=(D+timedelta(minutes=5)).isoformat())
        with self.assertRaisesRegex(ValueError, 'CLOSE_TIME_CONFLICT'):
            prefix([bad], D)

    def test_pivot_only_available_after_confirmation_not_at_extreme(self):
        p = dict(timestamp=(D-timedelta(minutes=15)).isoformat(), confirmed_at=D.isoformat(), kind='low', price=9.)
        self.assertEqual(confirmed_pivots([p], D-timedelta(microseconds=1)), [])
        self.assertEqual(confirmed_pivots([p], D), [p])
        p['confirmed_at'] = (D-timedelta(minutes=20)).isoformat()
        with self.assertRaisesRegex(ValueError, 'CONFIRMATION_PRECEDES_EXTREME'):
            confirmed_pivots([p], D)

    def test_source_clock_and_contract_are_not_merged(self):
        rows = [bar(D-timedelta(minutes=5), clock='A'), bar(D-timedelta(minutes=5), clock='B')]
        third = copy.deepcopy(rows[0]); third['time_contract'] = 'other-contract'; rows.append(third)
        self.assertEqual(len(prefix(rows, D)), 3)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_PREFIX_BAR'):
            prefix(rows+[rows[0]], D)

    def test_missing_bar_cannot_be_filled_by_future_data(self):
        rows = [bar(D-timedelta(hours=4)+timedelta(minutes=5*i)) for i in range(48) if i != 20]
        future = bar(D+timedelta(minutes=5))
        self.assertEqual(aggregate_utc_m5(rows, D), [])
        self.assertEqual(aggregate_utc_m5(rows+[future], D), [])

    def test_clocks_cannot_supply_each_others_missing_half_bucket(self):
        rows = [bar(D-timedelta(hours=4)+timedelta(minutes=5*i), clock='A' if i<24 else 'B') for i in range(48)]
        self.assertEqual(aggregate_utc_m5(rows, D), [])

    def test_h4_reconstruction_keeps_native_phase_and_reports_unknown_origin(self):
        rows = [bar(D-timedelta(hours=4)+timedelta(minutes=5*i)) for i in range(48)]
        native = bar(D-timedelta(hours=7), tf='H4', recorded=D-timedelta(minutes=1))
        report = diagnose(case(), rows+[native], rows+[native])
        h4 = report['h4_investigation'][0]
        self.assertEqual(h4['native_utc_phase_seconds'], [3600])
        self.assertEqual(h4['native_latest_open'], native['timestamp'])
        self.assertEqual(h4['utc_bucket_with_context_close'][0]['timestamp'], (D-timedelta(hours=4)).isoformat())
        self.assertEqual(h4['status'], 'NÃO_COMPROVADA')

    def test_complete_diagnostic_prefix_is_invariant_when_future_bars_are_appended(self):
        rows = [bar(D-timedelta(hours=4)+timedelta(minutes=5*i)) for i in range(48)]
        native = bar(D-timedelta(hours=7), tf='H4', recorded=D-timedelta(minutes=1))
        original = diagnose(case(), rows+[native], rows+[native])
        future = [bar(D+timedelta(minutes=5*i), recorded=D+timedelta(days=1)) for i in range(10)]
        future.append(bar(D, tf='H4', recorded=D+timedelta(days=1)))
        expanded = diagnose(case(), rows+[native]+future, rows+[native]+future)
        self.assertEqual(canonical(original), canonical(expanded))

    def test_late_archive_does_not_assert_late_agent_arrival_or_backfill_archive(self):
        row = bar(D-timedelta(minutes=5), recorded=D+timedelta(minutes=10))
        report = diagnose(case(), [], [row], case_records=[dict(
            recorded_at_utc=(D+timedelta(seconds=1)).isoformat(), equals_frozen=True, hash_verified=True)])
        self.assertEqual(report['views']['archive_known_by_cut'], [])
        self.assertEqual(report['views']['represented_in_case']['bars'], 1)
        comparison = report['case_archive_comparison'][0]
        self.assertFalse(comparison['archive_known_by_cut'])
        self.assertEqual(comparison['agent_availability'], 'NÃO_COMPROVADA')
        statuses = {c['id']:c['classification'] for c in report['conditions']}
        self.assertEqual(statuses['last_case_bar_agent_available_by_cut'], 'NÃO_COMPROVADA')

    def test_case_content_tamper_and_open_candle_rejected(self):
        c = case(); c['side'] = 'short'
        with self.assertRaisesRegex(ValueError, 'CASE_CHANGED'):
            diagnose(c, [], [])
        c = case(); c['facts']['M5.0.timestamp'] = D.isoformat(); c.pop('case_id')
        c['case_id'] = sha256(json.dumps(c, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
        with self.assertRaisesRegex(ValueError, 'CASE_CONTAINS_OPEN_OR_FUTURE_BAR'):
            diagnose(c, [], [])

    def test_only_four_classifications_and_no_trading_or_pnl_fields(self):
        report = diagnose(case(), [], [])
        self.assertTrue({c['classification'] for c in report['conditions']} <=
                        {'ATENDIDA','CONTRARIADA','NÃO_MENSURÁVEL','NÃO_COMPROVADA'})
        self.assertFalse({'fills','pnl','net_pnl','orders','forecast'} & set(report))

    def test_sealed_exports_and_index_are_checked_before_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'artifact_hashes.json').write_bytes(canonical({'x':'0'*64}))
            expected=sha256((root/'artifact_hashes.json').read_bytes())
            (root/'x').write_text('tampered')
            with self.assertRaisesRegex(ValueError, 'INPUT_HASH_MISMATCH'):
                load_and_diagnose(root, expected)
            with self.assertRaisesRegex(ValueError, 'FROZEN_INDEX_HASH_MISMATCH'):
                load_and_diagnose(root, '0'*64)

    def test_module_imports_do_not_load_operational_or_model_modules(self):
        source_root=str(Path(__file__).resolve().parents[2]/'src')
        code = "import sys;sys.path.insert(0,sys.argv[1]);import aurelia_fx.causal_diagnostic;" \
               "assert not any(n in sys.modules for n in ['psycopg','torch','MetaTrader5','aurelia_fx.literature_model','aurelia_fx.execution_simulator'])"
        result=subprocess.run([sys.executable,'-c',code,source_root],capture_output=True,text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_clock_is_not_a_proven_aggregation_origin(self):
        rows=[bar(D-timedelta(hours=4)+timedelta(minutes=5*i), clock=None) for i in range(48)]
        self.assertEqual(aggregate_utc_m5(rows,D),[])

    def test_fully_sealed_synthetic_cli_end_to_end_is_deterministic_and_preserves_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'input';root.mkdir();(root/'observador').mkdir();(root/'revisor').mkdir()
            c=case(); row=bar(D-timedelta(minutes=5))
            (root/'observador/case.json').write_bytes(canonical(c))
            (root/'observador/case_db_identity.json').write_bytes(canonical([]))
            for n in ['configuration.json','state_details.json']:
                (root/'observador'/n).write_bytes(canonical({}))
            for n in ['replay_spec.md','decisions.md','revisor/numbered_evidence.txt']:
                (root/n).write_text('synthetic')
            coverage=[]
            for scope in ['known_at_case','market_prefix_collected_later','post_case_evaluation']:
                name=scope+'.jsonl';bars=[bar(D)] if scope=='post_case_evaluation' else [row]
                (root/'observador'/name).write_bytes(b''.join(json.dumps(b).encode()+b'\n' for b in bars))
                coverage.append(dict(file=name,timeframe='M5',clock_id='clock-A',bars=1,scope=scope))
            (root/'observador/coverage.json').write_bytes(canonical(coverage))
            hashes={str(p.relative_to(root)):sha256(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
            (root/'artifact_hashes.json').write_bytes(canonical(hashes))
            before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            command=Path(__file__).resolve().parents[2]/'run_causal_diagnostic.py'
            outputs=[]
            for n in range(2):
                out=Path(folder)/f'output{n}'
                args=[sys.executable,str(command),'--bundle',str(root),'--expected-index-sha256',
                      sha256((root/'artifact_hashes.json').read_bytes()),'--output',str(out)]
                done=subprocess.run(args,capture_output=True,text=True)
                self.assertEqual(done.returncode,0,done.stderr)
                outputs.append((out/'diagnostic.json').read_bytes())
                if n==0:
                    repeated=subprocess.run(args,capture_output=True,text=True)
                    self.assertEqual(repeated.returncode,2)
                    self.assertIn('OUTPUT_ALREADY_EXISTS',repeated.stderr)
            self.assertEqual(outputs[0],outputs[1])
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})
