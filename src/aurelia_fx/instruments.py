"""Exact broker instrument identities and native contract economics.

No order is submitted here. Tick values are descriptive; risk must be verified
with MT5 order_calc_profit, not inferred from a currency-pair name.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import math


def symbol_name(value):
    if not isinstance(value,str) or not 1<=len(value)<=80 or value.strip()!=value or any(ord(c)<32 or ord(c)==127 for c in value):
        raise ValueError('Informe o nome exato do ativo na corretora.')
    return value


def identity(broker, server, symbol):
    return hashlib.sha256(json.dumps([broker,server,symbol_name(symbol)],ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class InstrumentContract:
    symbol: str
    description: str
    broker: str
    server: str
    currency_profit: str
    currency_margin: str
    digits: int
    point: float
    tick_size: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level: int
    calculation_mode: int
    trade_mode: int

    def __post_init__(self):
        symbol_name(self.symbol)
        if not isinstance(self.digits,int) or not 0<=self.digits<=16 or self.stops_level<0:
            raise ValueError('Precisão ou distância mínima do contrato inválida.')
        for key in ('point','tick_size','contract_size','volume_min','volume_max','volume_step'):
            value=getattr(self,key)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('Contrato inválido: '+key)
        if self.volume_max<self.volume_min or not self.currency_profit or not self.broker or not self.server:
            raise ValueError('Contrato ou identidade da corretora incompletos.')

    @property
    def key(self):return identity(self.broker,self.server,self.symbol)

    def as_dict(self):return {**asdict(self),'instrument_id':self.key}

    @classmethod
    def from_mt5(cls, info, *, broker, server):
        return cls(symbol=info.name,description=info.description,broker=broker,server=server,
            currency_profit=info.currency_profit,currency_margin=info.currency_margin,
            digits=int(info.digits),point=float(info.point),tick_size=float(info.trade_tick_size or info.point),
            contract_size=float(info.trade_contract_size),volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),volume_step=float(info.volume_step),
            stops_level=int(info.trade_stops_level),calculation_mode=int(info.trade_calc_mode),trade_mode=int(info.trade_mode))


def inspect_contract(sdk, requested, *, broker, server):
    requested=symbol_name(requested);info=sdk.symbol_info(requested)
    if info is None or info.name!=requested:
        raise ValueError('Ativo exato não encontrado: '+requested)
    if not sdk.symbol_select(requested,True):raise RuntimeError('Não foi possível selecionar '+requested)
    contract=InstrumentContract.from_mt5(info,broker=broker,server=server)
    tick=sdk.symbol_info_tick(requested)
    if tick is None or not tick.bid or not tick.ask:
        sdk.copy_rates_from_pos(requested,sdk.TIMEFRAME_M5,0,100)
        tick=sdk.symbol_info_tick(requested)
    result=dict(contract=contract.as_dict(),economics=None,
                scope='read_only_contract_discovery_not_entry_authorization',commission=None)
    if tick is None or not all(math.isfinite(x) and x>0 for x in (tick.bid,tick.ask)) or tick.ask<tick.bid:
        result['status']='WAITING_QUOTE';return result
    move=10*contract.tick_size;lot=contract.volume_min
    buy=sdk.order_calc_profit(sdk.ORDER_TYPE_BUY,requested,lot,tick.ask,tick.ask-move)
    sell=sdk.order_calc_profit(sdk.ORDER_TYPE_SELL,requested,lot,tick.bid,tick.bid+move)
    if any(v is None or not math.isfinite(v) or v>=0 for v in (buy,sell)):
        result['status']='WAITING_NATIVE_RISK_CALCULATION';return result
    result.update(status='CONTRACT_VERIFIED',economics=dict(
        price_value_per_lot_buy=abs(buy)/(lot*move),price_value_per_lot_sell=abs(sell)/(lot*move),
        currency='account_currency',spread_price=tick.ask-tick.bid,
        minimum_lot=lot,probe_price_distance=move,probe_buy_pnl=buy,probe_sell_pnl=sell,
        source='MT5.order_calc_profit',bid=tick.bid,ask=tick.ask))
    return result
