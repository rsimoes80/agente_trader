import copy
from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.agent_model import fingerprint
from aurelia_fx import forecast_diagnostics as audit


class ForecastDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,1,5,9,tzinfo=timezone.utc)
        self.bars=[Candle(self.start+timedelta(minutes=5*i),1.1,1.101,1.099,1.1,10,1.1) for i in range(80)]
        self.context=self.bars[:64]
        self.cache=dict(cache_key='a',configuration='fixed',input_bars=64,
            input_last=self.context[-1].timestamp.isoformat(),input_hash=fingerprint([c.as_dict() for c in self.context]),
            output=dict(model='fixture',revision='fixed',artifact_sha256='weights',sdk_revision='sdk',
                levels=[.1,.5,.9],quantiles=[[1.099,1.1001,1.101] for _ in range(12)]))

    def test_horizon_target_is_close_after_reference_close(self):
        cases,counts=audit.cases(self.bars,[self.cache])
        self.assertEqual(len(cases),3)
        self.assertEqual(cases[0]['known_at'],(self.context[-1].timestamp+timedelta(minutes=5)).isoformat())
        self.assertEqual(cases[0]['target_closed_at'],(self.context[-1].timestamp+timedelta(minutes=20)).isoformat())
        self.assertAlmostEqual(cases[0]['cost_pips'],2.2)
        self.assertFalse(cases[0]['median_exceeds_cost'])
        self.assertEqual(cases[0]['empirical_pinball_pips'],0.)

    def test_empirical_quantile_is_interpolated_and_past_only(self):
        self.assertEqual(audit.empirical_quantile([0.,10.],.1),1.)
        self.assertEqual(audit.empirical_quantile([0.,10.],.9),9.)
        with self.assertRaises(ValueError):audit.empirical_quantile([],.5)

    def test_wrong_input_hash_is_excluded_before_scoring(self):
        cases,counts=audit.cases(self.bars,[{**self.cache,'input_hash':'wrong'}])
        self.assertEqual(cases,[]);self.assertEqual(counts['input_hash_mismatch'],1)

    def test_different_models_are_never_deduplicated_together(self):
        other=copy.deepcopy(self.cache);other['cache_key']='b';other['output']['artifact_sha256']='other'
        rows,counts=audit.cases(self.bars,[self.cache,other])
        self.assertEqual(len(rows),6)
        self.assertEqual(len({r['model_key'] for r in rows}),2)

    def test_duplicate_reference_is_not_an_extra_sample(self):
        other={**self.cache,'cache_key':'b'}
        rows,counts=audit.cases(self.bars,[other,self.cache])
        self.assertEqual(len(rows),3);self.assertEqual(counts['duplicate_reference'],1)
        self.assertTrue(all(r['cache_key']=='a' for r in rows))

    def test_future_gap_is_not_a_traded_return(self):
        bars=self.bars[:65]+self.bars[66:]
        rows,counts=audit.cases(bars,[self.cache])
        self.assertEqual(rows,[]);self.assertEqual(counts['future_gap'],3)

    def test_stale_future_not_in_coverage_is_not_fabricated(self):
        rows,counts=audit.cases(self.bars[:64],[self.cache])
        self.assertEqual(rows,[]);self.assertEqual(counts['future_outside_coverage'],3)

    def test_baseline_can_beat_a_directional_forecast(self):
        rows,_=audit.cases(self.bars,[self.cache]);m=audit.metrics(rows)
        self.assertGreater(m['forecast_mae_pips'],m['persistence_mae_pips'])
        self.assertLess(m['diagnostic_signed_move_net_pips'],0)
        self.assertIsNone(m['paired_persistence_minus_model_mae']['interval'])

    def test_bootstrap_is_reproducible_with_week_blocks(self):
        rows=[dict(week=str(i),persistence_mae_pips=2.,forecast_mae_pips=1.) for i in range(8)]
        self.assertEqual(audit.week_interval(rows),audit.week_interval(rows))
        self.assertEqual(audit.week_interval(rows)['interval'],[1.,1.])


if __name__=='__main__':unittest.main()
