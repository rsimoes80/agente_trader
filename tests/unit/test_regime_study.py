import unittest
from dataclasses import asdict
from aurelia_fx.regime_study import configurations,project,evaluate


class RegimeStudyTests(unittest.TestCase):
    def test_each_experiment_changes_one_threshold_only_after_expiry_fix(self):
        configs={k:asdict(v) for k,v in configurations().items()}
        for name,field in [('efficiency55','trend_efficiency_min'),('confirmations2','confirmation_bars')]:
            self.assertEqual([k for k,v in configs[name].items() if configs['expiry_fixed'][k]!=v],[field])
        self.assertEqual(configs['expiry_fixed']['transition_expiry_policy'],'reset_pending_v1')
        self.assertEqual(configs['legacy']['transition_expiry_policy'],'legacy_research_v0')

    def test_projection_keeps_original_immutable_and_missing_context_unknown(self):
        sample=dict(snapshot=dict(regime='RANGE',context_trend=dict(timestamp_utc='2026-01-01T10:00:00+00:00')))
        projected=project([sample],{})
        self.assertEqual(projected[0]['snapshot']['regime'],'UNKNOWN')
        self.assertEqual(sample['snapshot']['regime'],'RANGE')

    def test_no_future_observations_do_not_mean_zero_percent_failures(self):
        results=evaluate([],[],start='2026-01-01T00:00:00+00:00',end='2026-01-02T00:00:00+00:00',lot='.01',contract=dict(contract_size=100000))
        for result in results.values():
            self.assertIsNone(result['breakout_followthrough']['failure_rate_pct'])
            self.assertIsNone(result['portfolios']['h1']['win_rate_pct'])
