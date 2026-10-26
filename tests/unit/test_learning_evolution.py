import copy
import unittest
from datetime import datetime, timedelta, timezone

from aurelia_fx import learning_evolution as ev
from . import test_continual_learning as fixtures


class EvolutionTests(unittest.TestCase):
    def setUp(self):
        f=fixtures.ContinualLearningTests();f.setUp()
        self.state=f.lab['continual'];self.at=f.at

    def row(self, value, offset=0, **extra):
        return dict(net_pnl=value, exit_at=(self.at+timedelta(minutes=offset)).isoformat(),
                    event_id=str(offset), variant='baseline', context='v|clock|model|config|TREND|long|london|vol:low', **extra)

    def test_metrics_include_costed_losses_flat_and_realized_drawdown(self):
        rows=[self.row(5,0),self.row(-3,1),self.row(-4,2),self.row(2,3),self.row(0,4)]
        result=ev.metrics(list(reversed(rows)))
        self.assertEqual(result['closed'],5)
        self.assertEqual(result['net_pnl'],0)
        self.assertEqual(result['average_gain'],3.5)
        self.assertEqual(result['average_loss'],-3.5)
        self.assertEqual(result['realized_drawdown'],7)

    def test_no_samples_are_not_a_zero_loss_or_an_infinite_profit_factor(self):
        result=ev.metrics([])
        self.assertIsNone(result['average_gain'])
        self.assertIsNone(result['average_loss'])
        self.assertIsNone(result['realized_drawdown'])

    def test_summary_is_read_only_and_never_combines_research_with_production(self):
        from aurelia_fx.continual_learning import VARIANTS
        self.state['outcomes']=[self.row(-3)]
        self.state['exploratory']={'hypothesis_review':{'reviews':[self.row(100)]}}
        original=copy.deepcopy(self.state)
        report=ev.summary(self.state,VARIANTS)
        self.assertEqual(report['portfolios'][0]['net_pnl'],-3)
        self.assertEqual(report['exploratory_metrics']['net_pnl'],100)
        self.assertIsNone(report['portfolios'][1]['delta_baseline'])
        self.assertEqual(self.state,original)

    def test_discovery_requires_comparable_context_not_total_samples(self):
        other={**self.row(-1),'context':'other'}
        result=ev.review_progress({'reviews':[self.row(-1),other]})
        self.assertEqual(result['samples'],1)
        self.assertIsNone(result['evaluation_not_before'])

    def test_future_deadline_includes_existing_settlement_day(self):
        ends=self.at+timedelta(days=14)
        report=ev.review_progress({'proposal':dict(status='COLLECTING_FUTURE',validation=[],
            minimum_samples=30,ends_at=ends.isoformat(),rule='WEAK_BODY',context='context')})
        self.assertEqual(report['evaluation_not_before'],(ends+timedelta(days=1)).isoformat())
        self.assertEqual(report['minimum'],30)
        self.assertFalse(report['automatic_activation'])

    def test_telemetry_is_monotonic_and_does_not_change_trading_state(self):
        original=copy.deepcopy(self.state)
        for _ in range(2):ev.record_decision(self.state,self.at.isoformat(),dict(action='WAIT',reason='TREND_REGIME_REQUIRED'))
        ev.record_decision(self.state,(self.at-timedelta(minutes=5)).isoformat(),dict(action='BUY'))
        self.assertEqual(self.state['diagnostics']['analyzed'],1)
        self.assertEqual(self.state['diagnostics']['reasons'],{'TREND_REGIME_REQUIRED':1})
        self.state.pop('diagnostics')
        self.assertEqual(self.state,original)

    def health(self, now=None, **fields):
        state=dict(desired='running',state='ANALYZING',last_decision=dict(candle=self.at.isoformat()),**fields)
        return ev.collection_health(state,{'available':True},now or self.at+timedelta(minutes=6))

    def test_recent_analysis_without_opportunities_is_healthy(self):
        self.assertEqual(self.health()['status'],'OK')

    def test_stalled_analysis_is_distinct_from_no_opportunity(self):
        self.assertEqual(self.health(self.at+timedelta(minutes=30))['status'],'ERROR')

    def test_weekend_quote_wait_is_not_a_false_collection_failure(self):
        saturday=datetime(2026,1,10,12,tzinfo=timezone.utc)
        state=dict(desired='running',state='WAITING_QUOTE')
        self.assertEqual(ev.collection_health(state,{'available':True},saturday)['status'],'MARKET_CLOSED')

    def test_missing_worker_paused_preparation_and_future_clock_are_distinct(self):
        self.assertEqual(ev.collection_health({'desired':'running'},{'available':False},self.at)['status'],'ERROR')
        self.assertEqual(ev.collection_health({'desired':'paused'},{'available':False},self.at)['status'],'PAUSED')
        self.assertEqual(ev.collection_health({'desired':'running','state':'ANALYSIS_WARMUP'},{'available':True},self.at)['status'],'PREPARING')
        self.assertEqual(self.health(self.at-timedelta(minutes=1))['status'],'WARNING')


if __name__=='__main__':unittest.main()
