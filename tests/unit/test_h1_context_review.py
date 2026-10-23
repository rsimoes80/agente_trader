import copy
import unittest
from run_h1_context_review import alignment,context,summarize,group,attach_readiness


class ContextReviewTests(unittest.TestCase):
    def sample(self):
        return dict(signal_at='2024-02-01T15:00:00+00:00',candidate=dict(side='long'),
                    snapshot=dict(session=['london','new_york'],research_context=dict(
                        known_at='2024-02-01T15:00:00+00:00',event='2024-02-01T11:00:00+00:00',h1_bias=1,macro_bias=-1)))

    def test_alignment_is_relative_to_side(self):
        self.assertEqual(alignment(1,'long'),'aligned')
        self.assertEqual(alignment(1,'short'),'opposed')
        self.assertEqual(alignment(0,'short'),'neutral')
        with self.assertRaises(ValueError):alignment(2,'short')

    def test_context_uses_frozen_pre_entry_information(self):
        sample=self.sample()
        c=context(sample)
        self.assertEqual(c['session'],'overlap')
        self.assertEqual(c['d1_alignment'],'opposed')
        self.assertEqual(c['breakout_age_hours'],4)
        for field in ('known_at','event'):
            bad=copy.deepcopy(sample)
            bad['snapshot']['research_context'][field]='2024-02-01T16:00:00+00:00'
            with self.assertRaises(ValueError):context(bad)

    def test_groups_reconcile_without_dropping_losses(self):
        rows=[]
        for side,pnl in [('long',2),('short',-3)]:
            rows.append(dict(reason='STOP',context=dict(side=side,breakout_age_hours=4),
                financial_result=dict(net_pnl=pnl,gross_pnl=pnl+.2,spread_cost=.1,slippage_cost=.03,commission=.07,initial_risk=1)))
        self.assertEqual(summarize(rows)['net'],-1)
        self.assertAlmostEqual(summarize(rows)['costs'],.4)
        groups=group(rows,'side')
        self.assertEqual(sum(v['closed'] for v in groups.values()),2)
        self.assertEqual(sum(v['net'] for v in groups.values()),-1)

    def test_insufficient_history_is_not_market_neutrality(self):
        row=dict(decision_id='x',context=dict(h1_alignment='neutral',d1_alignment='neutral'))
        attach_readiness([row],{'x':dict(H1=60,H4=100,D1=59)})
        self.assertEqual(row['context']['h1_state'],'neutral')
        self.assertEqual(row['context']['d1_state'],'insufficient_history')
