import unittest
from run_demo_fee_sensitivity import zero_fee_simulator
from aurelia_fx.agent_research import simulator


class DemoFeeTests(unittest.TestCase):
    def test_profile_changes_only_commission_in_isolated_engine(self):
        from dataclasses import asdict
        original=simulator(1000)
        changed=zero_fee_simulator(simulator)(1000)
        old=asdict(original.config);new=asdict(changed.config)
        self.assertEqual(old.pop('commission_per_million_side'),35)
        self.assertEqual(new.pop('commission_per_million_side'),0)
        self.assertEqual(old,new)
        self.assertEqual(simulator(1000).config.commission_per_million_side,35)

    def test_full_replay_retains_zero_fee_without_changing_default(self):
        from datetime import datetime,timedelta,timezone
        from unittest.mock import patch
        from aurelia_fx.domain import Candle
        from run_literature_experiment import simulate
        at=datetime(2026,1,7,12,tzinfo=timezone.utc)
        s=dict(sample_id='cost',signal_at=at.isoformat(),entry_at=at.isoformat(),
            snapshot=dict(snapshot_id='cost',session=['london'],regime='RESEARCH'),
            candidate=dict(side='long',entry=1.1,stop=1.099,target=1.104,
                expires_at=(at+timedelta(hours=1)).isoformat(),evidence=[]))
        bars=[Candle(at,1.1,1.105,1.098,1.1,100,1.2)]
        kw=dict(start=at,end=at+timedelta(days=2),holding_bars=72,purge_hours=24)
        normal=simulate([s],bars,**kw)
        with patch('aurelia_fx.agent_research.simulator',zero_fee_simulator(simulator)):
            changed=simulate([s],bars,**kw)
        self.assertEqual(changed['closed_trades'],1)
        self.assertEqual(changed['trades'][0]['financial_result']['commission'],0)
        self.assertAlmostEqual(changed['net_pnl']-normal['net_pnl'],.07)
        self.assertEqual(simulate([s],bars,**kw),normal)
