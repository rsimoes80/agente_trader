from datetime import datetime, timedelta, timezone
import unittest

from aurelia_fx.domain import Candle
from run_m1_native_context_experiment import generate, native_gap
from tests.unit import test_m1_context_experiment as fixtures


class NativeM1ContextTests(unittest.TestCase):
    def test_h4_phase_shift_only_over_known_closed_dst_weekend(self):
        before=datetime(2026,3,6,18,tzinfo=timezone.utc)
        after=datetime(2026,3,8,21,tzinfo=timezone.utc)
        self.assertFalse(native_gap(before,after,14400))
        self.assertTrue(native_gap(datetime(2026,3,9,18,tzinfo=timezone.utc),
                                   datetime(2026,3,10,1,tzinfo=timezone.utc),14400))

    def sources(self):
        h = fixtures.M1ContextTests().history()
        return h['M1'], {k:v for k,v in h.items() if k != 'M1'}

    def test_independent_native_contexts_match_closed_profile_fixture(self):
        bars, sources = self.sources(); start = bars[0].timestamp
        pools = generate(bars, sources, start)
        for profile in ('M15_M10_M1', 'M10_M5_M1'):
            self.assertEqual(len(pools[profile+':trend_pullback']), 1)
            signal = pools[profile+':trend_pullback'][0]
            self.assertEqual(signal['signal_at'], datetime(2026,1,7,12,tzinfo=timezone.utc).isoformat())
            self.assertEqual(signal['candidate']['side'], 'long')

    def test_future_native_context_never_enters_a_previous_signal(self):
        bars, sources = self.sources(); start = bars[0].timestamp
        old = generate(bars, sources, start)
        for tf, values in sources.items():
            values.append(Candle(datetime(2026,1,8,12,tzinfo=timezone.utc), 2, 3, 1, 2.5, 1, 1))
        self.assertEqual(generate(bars,sources,start),old)

    def test_missing_execution_minutes_do_not_create_signals_or_fabricated_bars(self):
        bars, sources = self.sources(); bars.pop(-10)
        pools = generate(bars,sources,bars[0].timestamp)
        self.assertEqual(len(pools['M15_M10_M1:trend_pullback']),0)

    def test_missing_whole_context_bar_and_stale_context_fail_closed(self):
        for stale in (False,True):
            bars,sources = self.sources()
            if stale:
                sources['M10'] = sources['M10'][:-2]
            else:
                sources['M10'].pop(-5)
            pools = generate(bars,sources,bars[0].timestamp)
            self.assertEqual(len(pools['M15_M10_M1:trend_pullback']),0)


if __name__ == '__main__':unittest.main()
