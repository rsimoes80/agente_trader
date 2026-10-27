from dataclasses import replace
import threading
import time
import unittest

from aurelia_fx.forecasting.config import TimestralConfig
from aurelia_fx.forecasting.shared import SharedTimestralPool


class SharedInferenceTests(unittest.TestCase):
    def setUp(self):
        self.live=0;self.peak=0;self.calls=0;self.max_calls=0
        parent=self
        class Adapter:
            def __init__(self,config):
                self.config=config;self.closed=False
                parent.live+=1;parent.peak=max(parent.peak,parent.live)
            def close(self):
                if not self.closed:parent.live-=1;self.closed=True
            def warmup(self):return None
            def forecast(self,values):
                parent.calls+=1;parent.max_calls=max(parent.max_calls,parent.calls)
                time.sleep(.01);parent.calls-=1
                return (self.config.revision,values[-1])
            def forecast_batch(self,values):return [self.forecast(v) for v in values]
        self.pool=SharedTimestralPool(Adapter);self.addCleanup(self.pool.close)
        self.config=TimestralConfig(revision='a'*40)

    def test_two_assets_share_one_model_and_closing_one_does_not_interrupt_other(self):
        euro=self.pool.acquire(self.config);gold=self.pool.acquire(self.config)
        euro.warmup();gold.warmup();self.assertEqual(self.live,1)
        euro.close();self.assertEqual(self.live,1)
        self.assertEqual(gold.forecast([4000.]),('a'*40,4000.))
        gold.close();self.assertEqual(self.live,0)

    def test_tuned_versions_are_swapped_without_mixing_outputs_or_loading_both(self):
        euro=self.pool.acquire(self.config);gold=self.pool.acquire(replace(self.config,revision='b'*40))
        self.assertEqual(euro.forecast([1.1])[0],'a'*40)
        self.assertEqual(gold.forecast([4000.])[0],'b'*40)
        self.assertEqual(euro.forecast([1.2])[0],'a'*40)
        self.assertEqual(self.peak,1)
        gold.close();self.assertEqual(self.live,1)

    def test_parallel_calls_are_serialized_and_retain_their_inputs(self):
        a=self.pool.acquire(self.config);b=self.pool.acquire(self.config);results=[]
        workers=[threading.Thread(target=lambda h=h,v=v:results.append(h.forecast([v]))) for h,v in ((a,1.1),(b,4000.))]
        for t in workers:t.start()
        for t in workers:t.join(3);self.assertFalse(t.is_alive())
        self.assertEqual(self.max_calls,1)
        self.assertEqual(sorted(v for model,v in results),[1.1,4000.])

    def test_resource_changes_are_not_hidden_by_numerical_model_fingerprint(self):
        a=self.pool.acquire(self.config);b=self.pool.acquire(replace(self.config,timeout_seconds=60))
        self.assertNotEqual(a.key,b.key)
        self.assertEqual(a.config.fingerprint,b.config.fingerprint)

    def test_closed_handles_or_pool_cannot_restart_a_model(self):
        a=self.pool.acquire(self.config);a.close()
        with self.assertRaises(RuntimeError):a.forecast([1.1])
        self.pool.close()
        with self.assertRaises(RuntimeError):self.pool.acquire(self.config)
