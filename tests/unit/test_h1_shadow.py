import unittest
from run_h1_shadow import on_time


class ShadowTests(unittest.TestCase):
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
