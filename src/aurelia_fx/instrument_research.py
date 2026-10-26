"""Explicit instrument inputs for research; no broker or execution authority.

Cost assumptions and market hours belong to a frozen profile, never to a name
such as 'XAU'. Native discovery alone does not validate historical conversions.
"""
from dataclasses import asdict, dataclass
from datetime import timedelta, timezone
import hashlib
import json
import math
from zoneinfo import ZoneInfo

from .execution_simulator import ExecutionConfig
from .instruments import InstrumentContract


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class WeeklySchedule:
    """Half-open minute intervals in a timezone's Monday-based week.

    Holidays require a separate calendar revision; gaps never add closures.
    The source identifies the schedule being tested, including synthetic tests.
    """
    version: str
    timezone: str
    intervals: tuple[tuple[int, int], ...]
    source: str

    def __post_init__(self):
        ZoneInfo(self.timezone)
        object.__setattr__(self, 'intervals', tuple(tuple(pair) for pair in self.intervals))
        if not self.version or not self.source or not self.intervals:
            raise ValueError('Explicit market calendar and source are required.')
        last = -1
        for start, end in self.intervals:
            if any(type(x) is not int for x in (start, end)) or not 0 <= start < end <= 10080 or start < last:
                raise ValueError('Market calendar intervals must be ordered and disjoint.')
            last = end

    def instant_open(self, stamp):
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError('Calendar timestamps must have a timezone.')
        local = stamp.astimezone(ZoneInfo(self.timezone))
        minute = local.weekday() * 1440 + local.hour * 60 + local.minute
        return any(start <= minute < end for start, end in self.intervals)

    def slot_tradable(self, stamp, seconds=300):
        if type(seconds) is not int or seconds < 1:
            raise ValueError('Bar duration must be a positive integer.')
        # Walk UTC instants: DST repeats/skips local hours without inventing bars.
        if self.instant_open(stamp):
            return True
        stamp = stamp.astimezone(timezone.utc)
        offset = 60 - stamp.second - stamp.microsecond / 1_000_000
        while offset < seconds:
            if self.instant_open(stamp + timedelta(seconds=offset)):
                return True
            offset += 60
        return False

    def unexpected_gap(self, previous, current, seconds):
        if type(seconds) is not int or seconds < 1:
            raise ValueError('Bar duration must be a positive integer.')
        for bar in (previous, current):
            if bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None:
                raise ValueError('Calendar timestamps must have a timezone.')
        prior = previous.timestamp.astimezone(timezone.utc)
        latest = current.timestamp.astimezone(timezone.utc)
        difference = (latest - prior).total_seconds()
        if difference <= 0 or difference % seconds:
            return True
        stamp = prior + timedelta(seconds=seconds)
        while stamp < latest:
            if self.slot_tradable(stamp, seconds):
                return True
            stamp += timedelta(seconds=seconds)
        return False


@dataclass(frozen=True)
class ResearchCosts:
    """Declared per-lot, per-side account-currency commission and price slippage."""
    commission_per_lot_side: float
    slippage_price: float
    source: str

    def __post_init__(self):
        if not self.source or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0
                                  for x in (self.commission_per_lot_side, self.slippage_price)):
            raise ValueError('Research costs require finite values and a declared source.')


@dataclass(frozen=True)
class InstrumentResearchProfile:
    contract: InstrumentContract
    account_currency: str
    price_unit: float
    max_spread_units: float
    calendar: WeeklySchedule
    # A descriptive native probe, not a promise of a constant future conversion.
    value_per_price_per_lot: float | None = None
    costs: ResearchCosts | None = None
    volatility_bands_units: tuple[float, float] | None = None
    version: str = 'instrument-research-v1'

    def __post_init__(self):
        if not isinstance(self.contract, InstrumentContract) or not isinstance(self.calendar, WeeklySchedule) or (self.costs is not None and not isinstance(self.costs, ResearchCosts)):
            raise ValueError('Research profile requires typed contract, calendar and costs.')
        if not self.account_currency or not self.version:
            raise ValueError('Research identity is incomplete.')
        for value in (self.price_unit, self.max_spread_units):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('Instrument price units and spread limits must be positive.')
        if self.value_per_price_per_lot is not None and (
            isinstance(self.value_per_price_per_lot, bool) or not math.isfinite(self.value_per_price_per_lot) or self.value_per_price_per_lot <= 0
        ):
            raise ValueError('Invalid native price value.')
        if self.volatility_bands_units is not None:
            bands = tuple(self.volatility_bands_units)
            if len(bands) != 2 or any(not math.isfinite(x) or x <= 0 for x in bands) or bands[0] >= bands[1]:
                raise ValueError('Volatility bands must be explicitly calibrated and ordered.')
            object.__setattr__(self, 'volatility_bands_units', bands)

    @property
    def symbol(self):
        return self.contract.symbol

    @property
    def fingerprint(self):
        return digest(asdict(self))

    @property
    def learning_namespace(self):
        return 'instrument:' + self.contract.key + ':' + self.fingerprint

    def as_dict(self):
        return {**asdict(self), 'profile_id': self.fingerprint}

    @classmethod
    def from_dict(cls, data):
        fields = dict(data)
        expected = fields.pop('profile_id')
        fields['contract'] = InstrumentContract(**fields['contract'])
        fields['calendar'] = WeeklySchedule(**fields['calendar'])
        if fields.get('costs') is not None:
            fields['costs'] = ResearchCosts(**fields['costs'])
        result = cls(**fields)
        if result.fingerprint != expected:
            raise ValueError('RESEARCH_PROFILE_INTEGRITY_ERROR')
        return result

    def execution_config(self, lot, *, initial_equity=10000., max_holding_bars=12):
        from .operation_control import validate_lot
        lot = float(validate_lot(lot, self.contract.as_dict()))
        if self.costs is None:
            raise ValueError('INSTRUMENT_COSTS_REQUIRED')
        if self.value_per_price_per_lot is None:
            raise ValueError('NATIVE_PRICE_VALUE_REQUIRED')
        # The existing simulator is linear. Reject conversion-dependent, inverse,
        # futures and exchange models until their historical valuation is modeled.
        if self.contract.currency_profit != self.account_currency or self.contract.calculation_mode not in {0, 4} or not math.isclose(
            self.value_per_price_per_lot, self.contract.contract_size, rel_tol=1e-6
        ):
            raise ValueError('HISTORICAL_INSTRUMENT_VALUATION_REQUIRED')
        return ExecutionConfig(
            pip_size=self.price_unit,
            slippage_pips=self.costs.slippage_price / self.price_unit,
            commission_per_million_side=self.costs.commission_per_lot_side * 1_000_000,
            value_per_price_unit=self.value_per_price_per_lot,
            fixed_units=lot,  # Profile-backed simulation quantities are LOTS.
            initial_equity=initial_equity, max_holding_bars=max_holding_bars,
        )
