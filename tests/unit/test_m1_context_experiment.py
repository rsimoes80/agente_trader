from datetime import datetime, timedelta, timezone
import unittest

from aurelia_fx.domain import Candle
from aurelia_fx.literature_strategies import setups
from run_m1_context_experiment import aggregator, proposals, simulate
from tests.unit import test_literature_strategies as fixtures


class M1ContextTests(unittest.TestCase):
    def history(self, mirror=False):
        fixture = fixtures.LiteratureStrategyTests()
        h = fixture.history()
        if mirror:
            h = fixture.mirror(h)
        known = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)
        def retime(bars, minutes):
            return [Candle(known-timedelta(minutes=minutes*(len(bars)-i)),
                          b.open, b.high, b.low, b.close, b.volume, b.spread_pips)
                    for i, b in enumerate(bars)]
        return dict(M1=retime(h['M5'], 1), M5=retime(h['H1'], 5),
                    M10=retime(h['H1'], 10), M15=retime(h['H1'], 15),
                    H1=retime(h['H1'], 60), H4=retime(h['H1'], 240))

    def test_both_short_profiles_require_matching_direction_and_real_expiry(self):
        for profile in ('M15_M10_M1', 'M10_M5_M1'):
            for mirror, side in ((False, 'long'), (True, 'short')):
                s = proposals(self.history(mirror), profile)['trend_pullback']
                self.assertEqual(s['candidate'].side, side)
                self.assertEqual(s['context_bias'], s['confirmation_bias'])
                self.assertEqual(s['candidate'].expires_at,
                    datetime(2026, 1, 7, 12, 1, tzinfo=timezone.utc))
                self.assertEqual(s['event'], self.history(mirror)['M1'][-2].timestamp.isoformat())

    def test_conflict_neutral_future_missing_and_bad_spread_fail_closed(self):
        h = self.history(); h['M10'] = self.history(True)['M10']
        self.assertEqual(proposals(h, 'M15_M10_M1'), {})
        h = self.history(); h['M10'] = h['M10'][:30]
        self.assertEqual(proposals(h, 'M15_M10_M1'), {})
        h = self.history(); h['M10'][-1] = Candle(datetime(2026, 1, 7, 12, tzinfo=timezone.utc), 1.1, 1.2, 1., 1.1, 1, 1)
        with self.assertRaises(ValueError): proposals(h, 'M15_M10_M1')
        h = self.history(); h['M1'].pop(-10)
        self.assertEqual(proposals(h, 'M15_M10_M1'), {})
        h = self.history(); b = h['M1'][-1]
        h['M1'][-1] = Candle(b.timestamp, b.open, b.high, b.low, b.close, 1, 3)
        self.assertEqual(proposals(h, 'M15_M10_M1'), {})

    def test_geometry_matches_existing_family_implementation(self):
        original = fixtures.LiteratureStrategyTests().history()
        expected = setups(original)['trend_pullback']['candidate']
        actual = proposals(self.history(), 'M15_M10_M1')['trend_pullback']['candidate']
        self.assertEqual((actual.entry, actual.stop, actual.target),
                         (expected.entry, expected.stop, expected.target))

    def test_breakout_geometry_matches_original_and_stays_on_real_time(self):
        h = self.history(); bars = h['M1']
        bars[-3] = Candle(bars[-3].timestamp, 1.1, 1.1006, 1.0999, 1.1005, 100, 1.2)
        bars[-2] = Candle(bars[-2].timestamp, 1.1005, 1.10055, 1.1, 1.1003, 100, 1.2)
        bars[-1] = Candle(bars[-1].timestamp, 1.1002, 1.1008, 1.10005, 1.1007, 100, 1.2)
        s = proposals(h, 'M10_M5_M1')['breakout_retest']
        self.assertEqual(s['event'], bars[-3].timestamp.isoformat())
        self.assertEqual(s['known_at'], (bars[-1].timestamp+timedelta(minutes=1)).isoformat())

    def test_m10_and_m15_emit_only_complete_closed_buckets(self):
        agg = aggregator(); at = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)
        for i in range(9): h = agg.add(Candle(at+timedelta(minutes=i), 1.1, 1.2, 1., 1.1, 1, 1))
        self.assertEqual(len(h['M10']), 0)
        self.assertEqual(len(h['M15']), 0)
        h = agg.add(Candle(at+timedelta(minutes=9), 1.1, 1.2, 1., 1.1, 1, 1))
        self.assertEqual(len(h['M10']), 1)
        for i in range(10, 15): h = agg.add(Candle(at+timedelta(minutes=i), 1.1, 1.2, 1., 1.1, 1, 1))
        self.assertEqual(len(h['M15']), 1)

    def sample(self, at):
        return dict(sample_id='m1', signal_at=at.isoformat(), entry_at=at.isoformat(),
            snapshot=dict(snapshot_id='m1', session=['london'], regime='RESEARCH'),
            candidate=dict(side='long', entry=1.1, stop=1.099, target=1.104,
                           expires_at=(at+timedelta(minutes=1)).isoformat(), evidence=[]))

    def test_m1_execution_next_open_stop_first_and_true_minute_timestamp(self):
        at = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)
        bar = Candle(at, 1.1, 1.105, 1.098, 1.1, 100, 1.2)
        r = simulate([self.sample(at)], [bar], start=at, end=at+timedelta(days=1))
        self.assertEqual(r['closed_trades'], 1)
        self.assertEqual(r['trades'][0]['reason'], 'STOP_FIRST_AMBIGUOUS')
        self.assertEqual(r['trades'][0]['observed_at'], (at+timedelta(minutes=1)).isoformat())
        self.assertLess(r['net_pnl'], 0)

    def test_gap_censors_exposure_and_fee_sensitivity_is_local(self):
        at = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)
        bars = [Candle(at+timedelta(minutes=i), 1.1, 1.1001, 1.0999, 1.1, 100, 1.2) for i in (0, 2)]
        r = simulate([self.sample(at)], bars, start=at, end=at+timedelta(days=1))
        self.assertEqual(r['censored_trades'], 1)
        self.assertIsNone(r['net_pnl'])
        from aurelia_fx.agent_research import simulator
        self.assertEqual(simulator(1000).config.commission_per_million_side, 35.)

    def test_common_holding_limit_is_sixty_real_minutes(self):
        at = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)
        bars = [Candle(at+timedelta(minutes=i), 1.1, 1.1001, 1.0999, 1.1, 100, 1.2) for i in range(60)]
        r = simulate([self.sample(at)], bars, start=at, end=at+timedelta(days=1))
        self.assertEqual(r['closed_trades'], 1)
        self.assertEqual(r['trades'][0]['observed_at'], (at+timedelta(minutes=60)).isoformat())

    def test_fee_profile_and_stress_do_not_modify_shared_configuration(self):
        at = datetime(2026, 1, 7, 12, tzinfo=timezone.utc)
        bars = [Candle(at, 1.1, 1.105, 1.098, 1.1, 100, 1.2)]
        standard = simulate([self.sample(at)], bars, start=at, end=at+timedelta(days=1))
        free = simulate([self.sample(at)], bars, start=at, end=at+timedelta(days=1), fee=0.)
        stressed = simulate([self.sample(at)], bars, start=at, end=at+timedelta(days=1), stress=True)
        self.assertAlmostEqual(free['net_pnl']-standard['net_pnl'], .07, places=6)
        self.assertLess(stressed['net_pnl'], standard['net_pnl'])
        from aurelia_fx.agent_research import simulator
        self.assertEqual(simulator(1000).config.bar_seconds, 300)

    def test_signal_generation_is_prefix_invariant(self):
        import random
        from run_m1_context_experiment import generate
        at = datetime(2026, 1, 6, 0, tzinfo=timezone.utc)
        rng = random.Random(17); price = 1.1; bars = []
        for i in range(2100):
            close = price+.000007+rng.uniform(-.00003, .00003)
            bars.append(Candle(at+timedelta(minutes=i), price, max(price, close)+.00001,
                               min(price, close)-.00001, close, 100, .8))
            price = close
        first, _ = generate(bars[:2000], at)
        extended, _ = generate(bars, at)
        boundary = at+timedelta(minutes=2000)
        for arm in first:
            self.assertEqual(first[arm], [s for s in extended[arm]
                if datetime.fromisoformat(s['signal_at']) <= boundary])
        self.assertGreater(sum(len(v) for v in first.values()), 0)


if __name__ == '__main__': unittest.main()
