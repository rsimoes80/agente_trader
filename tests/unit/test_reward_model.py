from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx import reward_model as rm
from aurelia_fx.agent_strategy import FEATURES
from aurelia_fx.domain import Candle
from run_reward_model_experiment import relabel


class RewardModelTests(unittest.TestCase):
    def setUp(self):
        self.at=datetime(2026,7,1,tzinfo=timezone.utc)
        self.samples=[]
        for i in range(120):
            features={f:0. for f in FEATURES};features['body_atr']=float(i%2)
            known=self.at-timedelta(days=2,hours=i)
            self.samples.append(dict(sample_id=str(i),features=features,signal_at=(known-timedelta(minutes=10)).isoformat(),
                exit_at=known.isoformat(),result_in_r=1. if i%2 else -1.))

    def test_learns_reward_differences_and_roundtrips_json(self):
        import json
        model=rm.fit(self.samples,known_before=self.at)
        lo={f:0. for f in FEATURES};hi={**lo,'body_atr':1.}
        self.assertLess(rm.predict(model,lo),0)
        self.assertGreater(rm.predict(model,hi),0)
        self.assertEqual(rm.predict(model,hi),rm.predict(json.loads(json.dumps(model)),hi))

    def test_future_labels_are_rejected(self):
        self.samples[0]['exit_at']=self.at.isoformat()
        with self.assertRaises(ValueError):rm.fit(self.samples,known_before=self.at)

    def test_nonfinite_features_are_rejected(self):
        self.samples[0]['features']['body_atr']=float('nan')
        with self.assertRaises(ValueError):rm.fit(self.samples,known_before=self.at)

    def test_constant_losses_do_not_become_positive_expectancy(self):
        for s in self.samples:s['result_in_r']=-.3
        model=rm.fit(self.samples,known_before=self.at)
        self.assertAlmostEqual(rm.predict(model,self.samples[-1]['features']),-.3)

    def test_large_losses_are_not_truncated_out_of_expected_reward(self):
        for s in self.samples:s['result_in_r']=-6.
        model=rm.fit(self.samples,known_before=self.at)
        self.assertAlmostEqual(model['constant_prediction'],-6.)
        self.assertAlmostEqual(rm.predict(model,self.samples[-1]['features']),-6.)

    def sample(self, at, session):
        return dict(sample_id='fixture',signal_at=at.isoformat(),features={f:0. for f in FEATURES},
            snapshot=dict(snapshot_id='fixture',session=[session],regime='RESEARCH'),
            candidate=dict(side='long',entry=1.1,stop=1.098,target=1.105,
                expires_at=(at+timedelta(minutes=5)).isoformat(),evidence=['fixture']))

    def test_relabels_with_known_broker_close_not_old_financial_labels(self):
        at=datetime(2026,1,5,21,45,tzinfo=timezone.utc)
        bars=[Candle(at+timedelta(minutes=5*i),1.1,1.1001,1.0999,1.1,10,1.1) for i in range(12)]
        s=self.sample(at,'new_york');s['net_pnl']=9999.
        labels,excluded=relabel([s],bars)
        self.assertEqual(len(labels),1)
        self.assertEqual(labels[0]['exit_at'],'2026-01-05T21:55:00+00:00')
        self.assertLess(labels[0]['net_pnl'],0)

    def test_censored_exposure_is_not_a_training_label(self):
        at=datetime(2026,1,5,10,tzinfo=timezone.utc)
        bars=[Candle(at+timedelta(minutes=i),1.1,1.1001,1.0999,1.1,10,1.1) for i in (0,20)]
        labels,excluded=relabel([self.sample(at,'london')],bars)
        self.assertEqual(labels,[])
        self.assertEqual(excluded['unresolved_or_rejected'],1)


if __name__=='__main__':unittest.main()
