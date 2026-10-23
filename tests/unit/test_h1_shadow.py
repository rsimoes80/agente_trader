import unittest
from run_h1_shadow import on_time,pending_rows


class ShadowTests(unittest.TestCase):
    def test_startup_keeps_the_candle_that_was_still_forming_in_seed(self):
        seed=[dict(timestamp='2026-10-23T16:25:00+00:00')]
        forming=dict(timestamp='2026-10-23T16:30:00+00:00')
        next_bar=dict(timestamp='2026-10-23T16:35:00+00:00')
        data=seed+[forming,next_bar]
        self.assertEqual(pending_rows(data,seed,[]),[forming,next_bar])
        self.assertEqual(pending_rows(data,seed,[forming]),[next_bar])
        self.assertEqual(pending_rows(data,seed,[forming,next_bar]),[])
        with self.assertRaises(ValueError):pending_rows(data,[],[])
    def test_late_backfills_never_count_as_forward_signals(self):
        signals = [dict(signal_at='2026-10-23T15:00:00+00:00')]
        bar = dict(timestamp='2026-10-23T14:55:00+00:00',first_seen_at='2026-10-23T15:00:45+00:00')
        self.assertEqual(on_time(signals,[bar]),(signals,[]))
        bar['first_seen_at']='2026-10-23T15:02:00+00:00'
        self.assertEqual(on_time(signals,[bar]),([],signals))

    def test_unobserved_or_future_capture_cannot_authorize_signal(self):
        signals = [dict(signal_at='2026-10-23T15:00:00+00:00')]
        self.assertEqual(on_time(signals,[]),([],signals))
        bar = dict(timestamp='2026-10-23T14:55:00+00:00',first_seen_at='2026-10-23T14:59:59+00:00')
        self.assertEqual(on_time(signals,[bar]),([],signals))
