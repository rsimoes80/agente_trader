"""Persisted account/instrument runtime profiles calibrated on past data only."""
from datetime import datetime,timedelta,timezone
import json
import math

from .account_pricing import AccountPricingRepository
from .agent_model import fingerprint
from .historical.core import percentile,utc
from .instrument_research import InstrumentResearchProfile,ResearchSession,WeeklySchedule

HOURS_SOURCE='https://www.thinkmarkets.com/en/contract-specifications/'


def calendar_for(contract):
    if contract.broker!='TF Global Markets (Aust) Pty Ltd':
        raise ValueError('INSTRUMENT_MARKET_CALENDAR_REQUIRED')
    if contract.calculation_mode==0:
        return WeeklySchedule('thinkmarkets-forex-profile-v1','America/New_York',
            ((0,4*1440+16*60+55),(6*1440+17*60+3,10080)),HOURS_SOURCE)
    if contract.symbol=='XAUUSD' and contract.calculation_mode==4:
        intervals=[]
        for day in range(5):
            intervals.append((day*1440,day*1440+17*60))
            if day<4:intervals.append((day*1440+18*60,(day+1)*1440))
        intervals.append((6*1440+18*60,10080))
        # Frozen weekly bar schedule checked against four complete weeks of
        # source data; the general PDF's Monday opening differs by five minutes.
        # New unexplained gaps never extend this closure schedule.
        return WeeklySchedule('thinkmarkets-xauusd-observed-weekly-v1','America/New_York',
            tuple(intervals),HOURS_SOURCE+'; verified 2026-09-27..2026-10-23: NY 18:00-17:00, daily break 17:00-18:00')
    raise ValueError('INSTRUMENT_MARKET_CALENDAR_REQUIRED')


def calibrate(contract,pricing,baseline,rows,*,economics):
    if baseline.get('symbol','EURUSD')!=contract.symbol or any(r.get('symbol',contract.symbol)!=contract.symbol for r in rows):
        raise ValueError('PROFILE_CALIBRATION_SYMBOL_MISMATCH')
    if baseline.get('days',0)<30:raise ValueError('PROFILE_CALIBRATION_REQUIRES_30_DAYS')
    calendar=calendar_for(contract)
    value=economics.get('price_value_per_lot_buy') if economics else None
    sell=economics.get('price_value_per_lot_sell') if economics else None
    if not economics or economics.get('source')!='MT5.order_calc_profit' or not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (value,sell)) or not math.isclose(value,sell,rel_tol=1e-6):
        raise ValueError('NATIVE_FINANCIAL_PROBE_REQUIRED')
    unit=baseline.get('price_unit')
    if not isinstance(unit,(int,float)) or not math.isfinite(unit) or unit<=0:
        raise ValueError('PROFILE_PRICE_UNIT_REQUIRED')
    cutoff=utc(baseline['start'])+timedelta(days=20)
    history=[r for r in rows if utc(r['timestamp'])+timedelta(minutes=5)<=cutoff]
    if len(history)<1000:raise ValueError('PROFILE_CALIBRATION_SAMPLE_INSUFFICIENT')
    spreads=[r['spread_pips'] for r in history if r.get('spread_pips') is not None]
    if len(spreads)<.95*len(history) or any(not math.isfinite(x) or x<0 for x in spreads):
        raise ValueError('PROFILE_CALIBRATION_SPREADS_UNAVAILABLE')
    ranges=[];atr=[];previous=None
    for row in history:
        if previous and (utc(row['timestamp'])-utc(previous['timestamp'])).total_seconds()!=300:ranges=[]
        tr=max(row['high']-row['low'],abs(row['high']-previous['close']) if previous else 0.,
               abs(row['low']-previous['close']) if previous else 0.)
        ranges=(ranges+[tr])[-14:]
        if len(ranges)==14:atr.append(sum(ranges)/14/unit)
        previous=row
    low,high=percentile(atr,1/3),percentile(atr,2/3)
    bands=(low,high) if low is not None and high>low>0 else None
    costs=pricing.research_costs(contract,account_id=pricing.account_id,account_currency=pricing.account_currency,
        slippage_price=2*contract.tick_size,slippage_source='Research assumption: two native ticks per market fill; not observed broker slippage')
    result=InstrumentResearchProfile(contract,pricing.account_currency,unit,
        max(1.,2*percentile(spreads,.95)),calendar,value,costs,
        volatility_bands_units=bands,sessions=(ResearchSession('london','Europe/London',480,1020),
                                              ResearchSession('new_york','America/New_York',480,1020)))
    result.execution_config(contract.volume_min)
    evidence=dict(baseline_id=baseline['baseline_id'],source_clock_id=baseline['clock_id'],
        source_dataset_sha256=baseline['timeframes']['M5']['dataset_sha256'],
        calibration_end=cutoff.isoformat(),calibration_bars=len(history),calendar=calendar.version,
        numeric_hypotheses=dict(max_spread='2 x historical P95; floor one price unit',
            volatility='past ATR14 terciles',slippage='two native ticks per market fill'),
        scope='past-data calibration; no claim of strategy validation or profitability',swap='must exit before daily market break')
    return result,evidence


class RuntimeProfileRepository:
    def __init__(self,memory):self.memory=memory

    @staticmethod
    def key(account_id,symbol):return fingerprint(dict(account_id=account_id,symbol=symbol))

    def record(self,account_id,profile,evidence):
        pricing=AccountPricingRepository(self.memory).latest(account_id)
        if not pricing:raise ValueError('ACCOUNT_PRICING_POLICY_REQUIRED')
        pricing.commission(profile.contract,account_id=account_id,account_currency=profile.account_currency)
        profile.execution_config(profile.contract.volume_min);profile.session_windows()
        payload=dict(account_id=account_id,symbol=profile.symbol,profile_id=profile.fingerprint,
            research_profile=profile.as_dict(),pricing_policy_id=pricing.policy_id,evidence=evidence,
            recorded_at=datetime.now(timezone.utc).isoformat(),scope='native_demo_intraday_research')
        self.memory.record_project_data('instrument_runtime_profile',self.key(account_id,profile.symbol),payload)
        return payload

    def latest(self,account_id,symbol):
        with self.memory.pool.connection() as c:
            row=c.execute("""SELECT payload_json,payload_sha256 FROM project_records
                WHERE record_type='instrument_runtime_profile' AND record_key=%s
                ORDER BY recorded_at DESC,payload_sha256 DESC LIMIT 1""",(self.key(account_id,symbol),)).fetchone()
        if not row:return None
        data=json.loads(row['payload_json'])
        if self.memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('RUNTIME_PROFILE_STORAGE_INTEGRITY_ERROR')
        profile=InstrumentResearchProfile.from_dict(data['research_profile'])
        if data['account_id']!=account_id or data['symbol']!=symbol or profile.symbol!=symbol or data['profile_id']!=profile.fingerprint:
            raise ValueError('RUNTIME_PROFILE_IDENTITY_MISMATCH')
        return profile


def provision(memory,symbol,account_id,fetch,*,progress=lambda **kw:None):
    """Prepare a selected instrument. This function never starts a session."""
    from dataclasses import replace
    from .demo_terminal import demo_terminal
    from .instruments import InstrumentContract,inspect_contract
    from .historical.repository import HistoricalRepository
    from .historical.collector import collect
    from .historical.core import readiness
    store=RuntimeProfileRepository(memory)
    existing=store.latest(account_id,symbol)
    if existing:return existing
    pricing_repo=AccountPricingRepository(memory);pricing=pricing_repo.latest(account_id)
    if not pricing:raise ValueError('ACCOUNT_PRICING_POLICY_REQUIRED')
    progress(stage='contract',message='Verificando contrato, conta demo e custos do ativo.')
    with demo_terminal(account_id=account_id) as terminal:
        discovery=inspect_contract(terminal.sdk,symbol,broker=terminal.account.company,server=terminal.account.server)
        contract=InstrumentContract(**{k:v for k,v in discovery['contract'].items() if k!='instrument_id'})
        calendar_for(contract)
        if discovery['status']!='CONTRACT_VERIFIED':raise ValueError(discovery['status'])
        if contract.key not in pricing.instrument_ids:
            # Standard's published Forex commission applies to native Forex
            # contracts selected by this user; never infer a share/CFD category.
            if contract.calculation_mode!=0:raise ValueError('INSTRUMENT_COMMISSION_NOT_CONFIRMED')
            if contract.broker!=pricing.broker or contract.server!=pricing.server or terminal.account.currency!=pricing.account_currency:
                raise ValueError('ACCOUNT_PRICING_IDENTITY_MISMATCH')
            pricing=replace(pricing,instrument_ids=pricing.instrument_ids+(contract.key,));pricing_repo.record(pricing)
        pricing.commission(contract,account_id=account_id,account_currency=terminal.account.currency)
    repository=HistoricalRepository(memory,symbol)
    baseline=repository.latest()
    if readiness(baseline,as_of=datetime.now(timezone.utc),clock_id=baseline['clock_id'] if baseline else None):
        def capture(*args,**kw):
            progress(stage='history',message='Preparando 30 dias de '+symbol+' em '+args[1]+'.')
            return fetch(*args,**kw)
        baseline=collect(repository,capture,days=30,full=False)
    frozen,rows=repository.frozen_candles(baseline)
    progress(stage='calibration',message='Calibrando custos, spread e volatilidade com dados passados do próprio ativo.')
    profile,evidence=calibrate(contract,pricing,frozen,rows,economics=discovery['economics'])
    with demo_terminal(account_id=account_id):pass
    store.record(account_id,profile,evidence)
    progress(stage='ready',message='Perfil do ativo preparado; aguardando início da sessão.')
    return profile
