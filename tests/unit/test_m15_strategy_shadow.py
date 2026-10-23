from datetime import datetime,timedelta,timezone
import unittest
from aurelia_fx.domain import Candle
from aurelia_fx.agent_research import simulator
from run_m15_strategy_shadow import replay_candidates,persist_experiences


class M15StrategyShadowTests(unittest.TestCase):
    def test_persistent_entries_and_outcomes_are_not_duplicated_in_cycles(self):
        from types import SimpleNamespace
        writes=[];memory=SimpleNamespace(record_project_data=lambda *args:writes.append(args))
        signal=dict(sample_id='s',signal_at='2026-10-23T18:45:00+00:00')
        raw=[dict(timestamp='2026-10-23T18:40:00+00:00',first_seen_at='2026-10-23T18:45:20+00:00')]
        result=dict(normal=dict(closed_trades=1,trades=[dict(decision_id='s',financial_result=dict(net_pnl=1))]),
                    conservative_normal=dict(closed_trades=1,trades=[dict(decision_id='s',financial_result=dict(net_pnl=.93))]))
        seen=set()
        first=persist_experiences(memory,'study','tape',[signal],raw,result,seen)
        second=persist_experiences(memory,'study','tape',[signal],raw,result,seen)
        self.assertEqual(first,second)
        self.assertEqual(len(writes),3)
        self.assertNotIn('trades',first['normal'])
        self.assertEqual(writes[0][2]['first_captured_at'],raw[0]['first_seen_at'])
        self.assertEqual(writes[1][2]['sample_id'],'s')
        self.assertEqual(len({w[1] for w in writes}),3)

    def test_fee_profiles_remain_separate_and_do_not_mutate_default(self):
        at=datetime(2026,1,7,12,tzinfo=timezone.utc)
        signal=dict(sample_id='paper',signal_at=at.isoformat(),entry_at=at.isoformat(),
            snapshot=dict(snapshot_id='paper',session=['london'],regime='RESEARCH'),
            candidate=dict(side='long',entry=1.1,stop=1.099,target=1.104,
                expires_at=(at+timedelta(minutes=15)).isoformat(),evidence=[]))
        bar=Candle(at,1.1,1.105,1.098,1.1,100,1.2)
        results=replay_candidates([signal],[bar],start=at,end=at+timedelta(minutes=5))
        self.assertEqual(results['normal']['closed_trades'],1)
        self.assertEqual(results['normal']['trades'][0]['financial_result']['commission'],0)
        self.assertAlmostEqual(results['conservative_normal']['trades'][0]['financial_result']['commission'],.07)
        self.assertAlmostEqual(results['normal']['net_pnl']-results['conservative_normal']['net_pnl'],.07)
        self.assertEqual(simulator(1000).config.commission_per_million_side,35)
