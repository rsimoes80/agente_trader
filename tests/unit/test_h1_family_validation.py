from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from aurelia_fx.domain import Candle
from run_h1_family_validation import generate,ARMS,FAMILIES
from tests.unit import test_timeframe_experiment as fixtures


class FamilyValidationTests(unittest.TestCase):
    def test_predeclared_families_and_only_two_time_policies(self):
        self.assertEqual(len(ARMS),6)
        self.assertEqual(set(ARMS),{f+':'+h for f in FAMILIES for h in ('reference','exclude_new_york_only')})

    def test_generated_candidate_keeps_closed_h1_definition(self):
        histories,known=fixtures.TimeframeExperimentTests().higher('H1')
        current=histories['H1'][-1]
        base=Candle(known-timedelta(minutes=5),current.open,current.high,current.low,current.close,current.volume,current.spread_pips)
        aggregator=SimpleNamespace(add=lambda _:histories,reset=lambda:None)
        with patch('aurelia_fx.agent_research.intelligence_session',return_value=SimpleNamespace(aggregator=aggregator)):
            pools=generate([base],base.timestamp)
        signal=pools['trend_pullback'][0]
        self.assertEqual(signal['signal_at'],known.isoformat())
        self.assertEqual(signal['snapshot']['research_context']['execution_timeframe'],'H1')
        self.assertEqual(signal['snapshot']['research_context']['context_timeframe'],'H4')
        self.assertEqual(signal['candidate']['expires_at'],(known+timedelta(hours=1)).isoformat())

    def test_empty_input_never_generates_an_entry(self):
        self.assertTrue(all(not values for values in generate([],None).values()))

    def test_m15_uses_frozen_m15_profile_without_future_context(self):
        histories,known=fixtures.TimeframeExperimentTests().higher('M15')
        current=histories['M15'][-1]
        base=Candle(known-timedelta(minutes=5),current.open,current.high,current.low,current.close,current.volume,current.spread_pips)
        aggregator=SimpleNamespace(add=lambda _:histories,reset=lambda:None)
        with patch('aurelia_fx.agent_research.intelligence_session',return_value=SimpleNamespace(aggregator=aggregator)):
            pools=generate([base],base.timestamp,timeframe='M15')
        signal=pools['trend_pullback'][0]
        self.assertTrue(signal['sample_id'].startswith('M15:'))
        self.assertEqual(signal['snapshot']['research_context']['context_timeframe'],'H1')
        self.assertEqual(signal['candidate']['expires_at'],(known+timedelta(minutes=15)).isoformat())
        with self.assertRaises(ValueError):generate([],None,timeframe='M1')
