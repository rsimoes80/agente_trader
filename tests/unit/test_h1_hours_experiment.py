import unittest
from run_h1_hours_experiment import permits,choose,ARMS


class HoursTests(unittest.TestCase):
    def sample(self,stamp):return dict(entry_at=stamp)

    def test_actual_dst_sessions_and_overlap(self):
        # US already in DST, UK still winter:13UTC is overlap,17UTC NY only.
        overlap=self.sample('2024-03-15T13:00:00+00:00')
        ny=self.sample('2024-03-15T17:00:00+00:00')
        self.assertTrue(permits(overlap,'exclude_new_york_only'))
        self.assertFalse(permits(overlap,'london_only'))
        self.assertFalse(permits(ny,'exclude_new_york_only'))
        self.assertTrue(permits(self.sample('2024-07-15T07:00:00+00:00'),'london_only'))
        self.assertFalse(permits(self.sample('2024-01-15T07:00:00+00:00'),'london_only'))

    def test_two_hours_remaining_uses_local_sessions(self):
        self.assertTrue(permits(self.sample('2024-07-15T18:00:00+00:00'),'avoid_last_two_hours'))
        self.assertFalse(permits(self.sample('2024-07-15T19:00:00+00:00'),'avoid_last_two_hours'))
        self.assertFalse(permits(self.sample('2024-01-15T20:00:00+00:00'),'avoid_last_two_hours'))

    def test_closed_market_rejected_and_unknown_policy_fails(self):
        for arm in ARMS:self.assertFalse(permits(self.sample('2024-07-13T12:00:00+00:00'),arm))
        with self.assertRaises(ValueError):permits(self.sample('2024-07-15T12:00:00+00:00'),'optimized')

    def test_selection_never_relaxes_minimum_or_uses_check_year(self):
        def result(n,net,pf=1.2):
            return dict(closed_trades=n,net_pnl=net,profit_factor=pf,account_locked=False,unresolved_position=False,censored_trades=0,expectancy_usd=net/n)
        def pair(n,net):return dict(normal=result(n,net),stress=result(n,net-1))
        data=dict(reference=pair(100,100),london_only=pair(49,100),exclude_new_york_only=pair(60,12),avoid_last_two_hours=pair(90,9))
        self.assertEqual(choose(data),'exclude_new_york_only')
        data['exclude_new_york_only']['stress']['account_locked']=True
        self.assertEqual(choose(data),'avoid_last_two_hours')

    def test_entry_window_does_not_close_an_existing_position(self):
        from datetime import datetime,timedelta,timezone
        from aurelia_fx.domain import Candle
        from run_literature_experiment import simulate
        at=datetime(2024,7,15,15,55,tzinfo=timezone.utc)
        sample=dict(sample_id='window',entry_at=at.isoformat(),signal_at=at.isoformat(),
            snapshot=dict(snapshot_id='window',session=['london','new_york'],regime='RESEARCH'),
            candidate=dict(side='long',entry=1.1,stop=1.099,target=1.104,
                expires_at=(at+timedelta(hours=1)).isoformat(),evidence=[]))
        self.assertTrue(permits(sample,'exclude_new_york_only'))
        self.assertFalse(permits(dict(sample,entry_at=(at+timedelta(minutes=5)).isoformat()),'exclude_new_york_only'))
        bars=[Candle(at+timedelta(minutes=5*i),1.1,1.1001,1.0999,1.1,100,1.2) for i in range(3)]
        r=simulate([sample],bars,start=at,end=at+timedelta(days=2),holding_bars=288,purge_hours=24,session_buffer_minutes=5)
        self.assertEqual(r['closed_trades'],0)
        self.assertTrue(r['unresolved_position'])
