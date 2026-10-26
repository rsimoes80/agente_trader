from datetime import datetime,timedelta,timezone
import unittest

from aurelia_fx.historical.core import summarize
from aurelia_fx.replay_data import market_open


class WeekendFreshnessTests(unittest.TestCase):
    def fixture(self):
        start=datetime(2026,9,26,12,tzinfo=timezone.utc);now=start+timedelta(days=30)
        stamp=start.replace(hour=21);rows=[]
        while stamp<now:
            if market_open(stamp):rows.append(dict(timestamp=stamp.isoformat(),open=1.1,high=1.101,low=1.099,
                close=1.1,volume=10,spread_pips=1.1))
            stamp+=timedelta(days=1)
        return rows,start,now

    def test_monday_last_closed_daily_bar_is_fresh(self):
        rows,start,now=self.fixture();r=summarize(rows,'D1',start=start,as_of=now)
        self.assertTrue(r['ready'])
        self.assertEqual(r['coverage'],1.)
        self.assertEqual(r['dataset_sha256'],'04b6c821695cf2e9949033ae4518e9ee90890c504b219243b371797f2a037b3a')

    def test_real_daily_history_loss_is_still_blocked(self):
        rows,start,now=self.fixture()
        self.assertFalse(summarize(rows[:-5],'D1',start=start,as_of=now)['ready'])

    def test_new_york_dst_weekend_is_not_elapsed_trading_time(self):
        from aurelia_fx.historical.core import trading_age_seconds
        start=datetime(2026,10,30,21,tzinfo=timezone.utc)
        now=datetime(2026,11,2,12,tzinfo=timezone.utc)
        self.assertEqual(trading_age_seconds(start,now),14*3600)

    def test_active_hours_still_count_for_staleness(self):
        from aurelia_fx.historical.core import trading_age_seconds
        start=datetime(2026,10,26,9,tzinfo=timezone.utc)
        self.assertEqual(trading_age_seconds(start,start+timedelta(hours=7)),7*3600)
