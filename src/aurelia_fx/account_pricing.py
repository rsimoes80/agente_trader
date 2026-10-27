"""Account-bound commission evidence, separate from execution assumptions.

The confirmed Standard tariff applies only to explicitly inspected instruments.
It never turns an unknown symbol, swap or slippage into a zero-cost instrument.
"""
from dataclasses import asdict, dataclass
from datetime import datetime
import json

from .agent_model import fingerprint
from .instrument_research import ResearchCosts
from .instruments import InstrumentContract


STANDARD_SOURCE = 'https://support.thinkmarkets.com/hc/en-gb/articles/11613269516945-Standard-account'
CONFIRMED_COMPANIES = frozenset({'TF Global Markets (Aust) Pty Ltd'})


@dataclass(frozen=True)
class AccountPricing:
    account_id: str
    broker: str
    server: str
    account_currency: str
    account_type: str
    instrument_ids: tuple[str, ...]
    confirmed_at: str
    source: str = STANDARD_SOURCE
    confirmation: str = 'user_confirmed_account_type_and_broker_published_tariff'
    version: str = 'account-pricing-v1'

    def __post_init__(self):
        object.__setattr__(self,'instrument_ids',tuple(sorted(set(self.instrument_ids))))
        if self.account_type!='Standard' or not all((self.account_id,self.broker,self.server,self.account_currency,self.instrument_ids)):
            raise ValueError('Confirmed Standard account identity and inspected instruments are required.')
        if self.broker not in CONFIRMED_COMPANIES:
            raise ValueError('BROKER_STANDARD_TARIFF_NOT_VERIFIED')
        if self.source!=STANDARD_SOURCE or self.confirmation!='user_confirmed_account_type_and_broker_published_tariff':
            raise ValueError('Account pricing evidence is incomplete.')
        stamp=datetime.fromisoformat(self.confirmed_at)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('Pricing confirmation must have a timezone.')

    @property
    def policy_id(self):
        return fingerprint(asdict(self))

    def as_dict(self):
        return json.loads(json.dumps({**asdict(self),'policy_id':self.policy_id}))

    @classmethod
    def from_dict(cls,data):
        fields=dict(data);expected=fields.pop('policy_id');policy=cls(**fields)
        if policy.policy_id!=expected:raise ValueError('ACCOUNT_PRICING_INTEGRITY_ERROR')
        return policy

    def commission(self, contract: InstrumentContract, *, account_id, account_currency):
        if (account_id!=self.account_id or account_currency!=self.account_currency
                or contract.broker!=self.broker or contract.server!=self.server):
            raise ValueError('ACCOUNT_PRICING_IDENTITY_MISMATCH')
        if contract.key not in self.instrument_ids:
            raise ValueError('INSTRUMENT_COMMISSION_NOT_CONFIRMED')
        return dict(commission_per_lot_side=0.,account_currency=self.account_currency,
                    account_type=self.account_type,policy_id=self.policy_id,source=self.source,
                    spread='observed_bid_ask_or_archived_spread',swap='not_included',slippage='separate_assumption')

    def research_costs(self,contract,*,account_id,account_currency,slippage_price,slippage_source):
        evidence=self.commission(contract,account_id=account_id,account_currency=account_currency)
        if not slippage_source:raise ValueError('Explicit slippage assumption is required.')
        return ResearchCosts(evidence['commission_per_lot_side'],slippage_price,
            json.dumps(dict(commission_policy=self.policy_id,commission_source=self.source,
                            slippage_assumption=slippage_source),sort_keys=True))


class AccountPricingRepository:
    def __init__(self,memory):self.memory=memory

    def record(self,policy):
        self.memory.record_project_data('account_pricing_policy',policy.account_id,policy.as_dict())

    def latest(self,account_id):
        with self.memory.pool.connection() as c:
            row=c.execute("""SELECT payload_json,payload_sha256 FROM project_records
                WHERE record_type='account_pricing_policy' AND record_key=%s
                ORDER BY recorded_at DESC,payload_sha256 DESC LIMIT 1""",(account_id,)).fetchone()
        if not row:return None
        payload=json.loads(row['payload_json'])
        if self.memory._encode(payload)[1]!=row['payload_sha256']:
            raise ValueError('ACCOUNT_PRICING_STORAGE_INTEGRITY_ERROR')
        policy=AccountPricing.from_dict(payload)
        if policy.account_id!=account_id:raise ValueError('ACCOUNT_PRICING_IDENTITY_MISMATCH')
        return policy
