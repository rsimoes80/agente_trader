from dataclasses import replace
from datetime import datetime, timezone
import unittest
import os

from aurelia_fx.account_pricing import AccountPricing,AccountPricingRepository
from .test_instrument_research import profile


class AccountPricingTests(unittest.TestCase):
    def setUp(self):
        self.contract=replace(profile().contract,broker='TF Global Markets (Aust) Pty Ltd')
        self.policy=AccountPricing('fixture-account',self.contract.broker,self.contract.server,
                                   'USD','Standard',(self.contract.key,),datetime.now(timezone.utc).isoformat())

    def commission(self,contract=None,**kw):
        return self.policy.commission(contract or self.contract,account_id=kw.get('account_id','fixture-account'),
                                      account_currency=kw.get('currency','USD'))

    def test_confirmed_standard_gold_has_zero_commission_not_zero_total_cost(self):
        e=self.commission()
        self.assertEqual(e['commission_per_lot_side'],0.)
        self.assertEqual(e['spread'],'observed_bid_ask_or_archived_spread')
        self.assertEqual(e['swap'],'not_included')
        costs=self.policy.research_costs(self.contract,account_id='fixture-account',account_currency='USD',
                                        slippage_price=.02,slippage_source='synthetic two-tick assumption')
        self.assertEqual(costs.slippage_price,.02)
        self.assertEqual(costs.commission_per_lot_side,0.)

    def test_zero_commission_does_not_spread_to_another_account_broker_or_instrument(self):
        for kw in ({'account_id':'other'},{'currency':'EUR'}):
            with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):self.commission(**kw)
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):
            self.commission(replace(self.contract,broker='Other'))
        for symbol in ('XAUUSD247','XAUUSDx','OTHER.SHARE'):
            with self.assertRaisesRegex(ValueError,'COMMISSION_NOT_CONFIRMED'):
                self.commission(replace(self.contract,symbol=symbol))

    def test_type_and_evidence_cannot_be_changed_to_unknown_pricing(self):
        for kw in ({'account_type':'ThinkZero'},{'source':''},{'instrument_ids':()}):
            with self.assertRaises(ValueError):replace(self.policy,**kw)

    def test_policy_roundtrip_and_tampering(self):
        p=self.policy.as_dict()
        self.assertEqual(AccountPricing.from_dict(p),self.policy)
        p['account_id']='other'
        with self.assertRaisesRegex(ValueError,'INTEGRITY_ERROR'):AccountPricing.from_dict(p)

    def test_slippage_is_not_inferred_from_standard_account(self):
        with self.assertRaises(ValueError):
            self.policy.research_costs(self.contract,account_id='fixture-account',account_currency='USD',
                                      slippage_price=.02,slippage_source='')


@unittest.skipUnless(os.environ.get('TIMESTRAL_TEST_POSTGRES')=='1','PostgreSQL opt-in')
class AccountPricingStorageTests(unittest.TestCase):
    def setUp(self):
        from .test_multi_instrument_learning import MultiInstrumentLearningStorageTests
        fixture=MultiInstrumentLearningStorageTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.memory=fixture.memory;self.c=fixture.c;self.repo=AccountPricingRepository(self.memory)
        pure=AccountPricingTests();pure.setUp();self.policy=pure.policy

    def test_persisted_policy_is_bound_to_account_and_checked_against_hash(self):
        self.repo.record(self.policy)
        self.assertEqual(self.repo.latest(self.policy.account_id),self.policy)
        self.assertIsNone(self.repo.latest('other-account'))
        self.c.execute("UPDATE project_records SET payload_sha256='bad' WHERE record_type='account_pricing_policy'")
        with self.assertRaisesRegex(ValueError,'STORAGE_INTEGRITY_ERROR'):self.repo.latest(self.policy.account_id)

    def test_a_valid_policy_cannot_be_stored_under_a_different_account_key(self):
        self.memory.record_project_data('account_pricing_policy','other-account',self.policy.as_dict())
        with self.assertRaisesRegex(ValueError,'IDENTITY_MISMATCH'):self.repo.latest('other-account')


if __name__=='__main__':unittest.main()
