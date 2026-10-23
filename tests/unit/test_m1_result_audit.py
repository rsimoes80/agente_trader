from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import unittest
from unittest.mock import patch

from aurelia_fx.domain import Candle
from run_m1_context_experiment import ROOT, simulate
from tests.unit import test_m1_context_experiment as fixtures
from verify_m1_context_results import audit


class M1ResultAuditTests(unittest.TestCase):
    def data(self):
        at=datetime(2026,1,7,12,tzinfo=timezone.utc)
        sample=fixtures.M1ContextTests().sample(at)
        sample['snapshot']['research_context']=dict(known_at=at.isoformat(),context_bias=1,
            confirmation_bias=1,context_last=(at-timedelta(minutes=15)).isoformat(),
            confirmation_last=(at-timedelta(minutes=10)).isoformat())
        bars=[Candle(at,1.1,1.105,1.098,1.1,100,1.2)]
        pair={label:simulate([sample],bars,start=at,end=at+timedelta(days=1),fee=fee,stress=stress)
              for label,fee,stress in (('normal',35.,False),('stress',35.,True),
                                       ('zero_fee_normal',0.,False),('zero_fee_stress',0.,True))}
        arm='M15_M10_M1:trend_pullback'
        report=dict(report_id='test',protocol=dict(protocol_id='test',code_hashes={
            'README.md':hashlib.sha256((ROOT/'README.md').read_bytes()).hexdigest()}),
            results={p:{arm:deepcopy(pair)} for p in ('development','check','final')},
            selected=None,checks={'check':False,'final':False},historical_checks_passed=False,
            orders_sent=0,live_policy_changed=False)
        return report,dict(samples={arm:[sample]})

    def test_all_paired_results_and_financial_costs_reconcile(self):
        report,signals=self.data()
        with patch('verify_m1_context_results.read',return_value=signals):
            result=audit(None,report)
        self.assertEqual(result['portfolios_checked'],12)
        self.assertEqual(result['paired_closed_results_checked'],12)
        self.assertFalse(result['paired_results_are_independent_samples'])

    def test_cost_or_unknown_exposure_tampering_is_detected(self):
        for field in ('cost','lock'):
            report,signals=self.data()
            r=next(iter(report['results']['final'].values()))['normal']
            if field=='cost':r['trades'][0]['financial_result']['commission']=0.
            else:r['account_locked']=True
            with patch('verify_m1_context_results.read',return_value=signals):
                with self.assertRaises(ValueError):audit(None,report)

    def test_future_context_and_changed_source_are_detected(self):
        for field in ('context','source'):
            report,signals=self.data()
            if field=='context':
                sample=next(iter(signals['samples'].values()))[0]
                sample['snapshot']['research_context']['context_last']=sample['signal_at']
            else:report['protocol']['code_hashes']['README.md']='wrong'
            with patch('verify_m1_context_results.read',return_value=signals):
                with self.assertRaises(ValueError):audit(None,report)


if __name__=='__main__':unittest.main()
