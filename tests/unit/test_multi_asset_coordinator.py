import threading
import time
import unittest

from aurelia_fx.multi_asset_coordinator import MultiAssetCoordinator


class CoordinatorTests(unittest.TestCase):
    def wait_for(self,predicate):
        until=time.monotonic()+3
        while not predicate():
            if time.monotonic()>=until:self.fail('Worker did not reach expected state')
            time.sleep(.005)

    def test_selection_does_not_overlap_workers_and_removal_cancels_only_one(self):
        selected=['EURUSD','XAUUSD'];started={};callbacks={}
        def serve(symbol,stop,progress):
            started[symbol]=started.get(symbol,0)+1;callbacks[symbol]=progress
            progress();stop.wait(10)
        c=MultiAssetCoordinator(lambda:selected,serve);self.addCleanup(c.close)
        c.poll();self.wait_for(lambda:len(started)==2)
        for _ in range(5):c.poll()
        self.assertEqual(started,{'EURUSD':1,'XAUUSD':1})
        old=c.slots['XAUUSD'];selected.remove('XAUUSD');c.poll()
        self.wait_for(lambda:not old.thread.is_alive());c.poll()
        self.assertTrue(c.slots['EURUSD'].thread.is_alive())
        selected.append('XAUUSD');c.poll();self.wait_for(lambda:started['XAUUSD']==2)
        self.assertIsNot(c.slots['XAUUSD'].stop,old.stop)
        self.assertFalse(c.slots['XAUUSD'].stop.is_set())

    def test_other_workers_cannot_mask_a_stalled_asset(self):
        clock=[0.];callbacks={}
        def serve(symbol,stop,progress):callbacks[symbol]=progress;progress();stop.wait(10)
        c=MultiAssetCoordinator(lambda:['EURUSD','XAUUSD'],serve,stall_seconds=30,now=lambda:clock[0])
        self.addCleanup(c.close);c.poll();self.wait_for(lambda:len(callbacks)==2)
        clock[0]=31.;callbacks['EURUSD']()
        self.assertFalse(c.status()['healthy'])
        callbacks['XAUUSD']();self.assertTrue(c.status()['healthy'])

    def test_failed_asset_retries_without_restarting_the_healthy_one(self):
        clock=[0.];started={}
        def serve(symbol,stop,progress):
            started[symbol]=started.get(symbol,0)+1
            if symbol=='XAUUSD' and started[symbol]==1:raise RuntimeError('fixture')
            progress();stop.wait(10)
        c=MultiAssetCoordinator(lambda:['EURUSD','XAUUSD'],serve,now=lambda:clock[0]);self.addCleanup(c.close)
        c.poll();self.wait_for(lambda:'XAUUSD' in started and not c.slots['XAUUSD'].thread.is_alive())
        clock[0]=9.;c.poll();self.assertEqual(started['XAUUSD'],1)
        clock[0]=11.;c.poll();self.wait_for(lambda:started['XAUUSD']==2)
        self.assertEqual(started['EURUSD'],1)

    def test_capacity_is_visible_and_freed_slots_can_start_waiting_assets(self):
        selected=['EURUSD','XAUUSD'];started=[]
        def serve(symbol,stop,progress):started.append(symbol);progress();stop.wait(10)
        c=MultiAssetCoordinator(lambda:selected,serve,max_workers=1);self.addCleanup(c.close)
        self.assertEqual(c.poll()['queued'],['XAUUSD'])
        self.wait_for(lambda:started==['EURUSD']);old=c.slots['EURUSD']
        selected.remove('EURUSD');c.poll();self.wait_for(lambda:not old.thread.is_alive())
        c.poll();self.wait_for(lambda:started==['EURUSD','XAUUSD'])

    def test_close_stops_all_threads_and_prevents_another_poll(self):
        c=MultiAssetCoordinator(lambda:['EURUSD','XAUUSD'],lambda s,e,p:e.wait(10))
        c.poll();self.assertTrue(c.close())
        with self.assertRaises(RuntimeError):c.poll()
