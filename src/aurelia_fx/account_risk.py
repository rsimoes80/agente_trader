"""One account risk ledger, used while the durable demo journal is locked.

No SDK send exists here. Open-risk calculations use each instrument's native
profit calculator in account currency; quantities are broker lots.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math

MAGIC=70616041


def finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


@dataclass(frozen=True)
class AccountRiskSnapshot:
    account_id: str
    equity: float
    day_start: float
    peak: float
    daily_entries: int
    open_risk: float
    position_symbols: tuple[str,...]
    known_position_tickets: tuple[int,...]

    def check(self, symbol, candidate_risk):
        if symbol in self.position_symbols:raise ValueError('SYMBOL_EXPOSURE_ALREADY_OPEN')
        if self.daily_entries>=5:raise ValueError('ACCOUNT_DAILY_ENTRY_LIMIT')
        if self.equity<=self.day_start*.98:raise ValueError('ACCOUNT_DAILY_LOSS_LIMIT')
        if self.equity<=self.peak*.95:raise ValueError('ACCOUNT_DRAWDOWN_LIMIT')
        if not finite(candidate_risk) or candidate_risk<=0:raise ValueError('INVALID_CANDIDATE_RISK')
        if self.open_risk+candidate_risk>self.equity*.005+1e-9:
            raise ValueError('ACCOUNT_AGGREGATE_RISK_LIMIT')


def position_owner(position,intents):
    matches=[]
    if position.magic!=MAGIC:return None
    for intent in intents:
        request=intent['request']['broker']
        if 'position' in request or request.get('symbol')!=position.symbol or intent['status'] not in {'CONFIRMED','UNPROTECTED','PARTIAL'}:continue
        proof=intent.get('evidence',{})
        tickets=proof.get('position_tickets',[]);ids=proof.get('position_ids',[])
        marker='AFX:'+intent['client_id'][:20]
        if position.ticket in tickets or getattr(position,'identifier',None) in ids or marker in getattr(position,'comment',''):
            matches.append(intent)
    return matches[0] if len(matches)==1 else None


def known_position_tickets(positions,intents):
    return tuple(p.ticket for p in positions if position_owner(p,intents))


class AccountRiskBook:
    def __init__(self,memory):self.memory=memory

    def observe(self,scope,terminal,*,now=None):
        scope._check()
        account=terminal.check_account();account_id=terminal.account_id
        now=now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:raise ValueError('ACCOUNT_RISK_UTC_REQUIRED')
        now=now.astimezone(timezone.utc);day=now.date().isoformat()
        if not finite(account.equity) or account.equity<=0:raise ValueError('ACCOUNT_EQUITY_UNAVAILABLE')
        row=scope.connection.execute("""SELECT payload_json,payload_sha256 FROM project_records
            WHERE record_type='agent_demo_account_risk' AND record_key=%s
            ORDER BY recorded_at DESC LIMIT 1""",(account_id,)).fetchone()
        old=json.loads(row['payload_json']) if row else None
        if old and (self.memory._encode(old)[1]!=row['payload_sha256'] or old.get('account_id')!=account_id):
            raise ValueError('ACCOUNT_RISK_INTEGRITY_ERROR')
        if old and old.get('currency')!=account.currency:raise ValueError('ACCOUNT_RISK_CURRENCY_CHANGED')
        if old and datetime.fromisoformat(old['observed_at'])>now:raise ValueError('ACCOUNT_RISK_CLOCK_REWIND')
        legacy=None
        if not old:
            saved=scope.connection.execute("""SELECT payload_json,payload_sha256 FROM project_records
                WHERE record_type='agent_paper_account' AND record_key=%s ORDER BY recorded_at DESC LIMIT 1""",('DEMO:'+account_id,)).fetchone()
            if saved:
                legacy=json.loads(saved['payload_json'])
                if self.memory._encode(legacy)[1]!=saved['payload_sha256']:
                    raise ValueError('ACCOUNT_RISK_LEGACY_INTEGRITY_ERROR')
        reference=old or legacy or {}
        peak=max(reference.get('peak') or account.equity,account.equity)
        day_start=reference['day_start'] if reference.get('day')==day else account.equity
        if any(not finite(v) or v<=0 for v in (peak,day_start)):raise ValueError('ACCOUNT_RISK_REFERENCE_INVALID')
        data=dict(account_id=account_id,currency=account.currency,day=day,day_start=day_start,
                  peak=peak,equity=account.equity,observed_at=now.isoformat(),
                  aggregate_risk_limit_pct=.5,daily_loss_limit_pct=2.,drawdown_limit_pct=5.)
        text,digest=self.memory._encode(data)
        scope.connection.execute("""INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at)
            VALUES('agent_demo_account_risk',%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING""",(account_id,text,digest))
        intents=scope.for_account(account_id)
        if scope.pending(account_id):raise ValueError('ACCOUNT_UNRESOLVED_SEND')
        if terminal.orders():raise ValueError('ACCOUNT_PENDING_ORDER')
        daily_entries=sum('position' not in i['request']['broker'] and i['status'] not in {'PREPARED','REJECTED','CANCELLED'}
                          and datetime.fromisoformat(i['created_at']).astimezone(timezone.utc).date().isoformat()==day for i in intents)
        positions=terminal.positions();risk=0.;symbols=[];tickets=[]
        for p in positions:
            intent=position_owner(p,intents)
            if intent is None:raise ValueError('ACCOUNT_FOREIGN_OR_UNRECONCILED_POSITION')
            if intent['status']!='CONFIRMED':raise ValueError('ACCOUNT_UNPROTECTED_POSITION')
            if p.type not in {terminal.sdk.POSITION_TYPE_BUY,terminal.sdk.POSITION_TYPE_SELL} or not finite(p.volume) or p.volume<=0:
                raise ValueError('POSITION_VOLUME_OR_TYPE_INVALID')
            info=terminal.sdk.symbol_info(p.symbol)
            if info is None:raise ValueError('POSITION_CONTRACT_UNAVAILABLE')
            assumptions=intent['request'].get('metadata',{}).get('financial_assumptions')
            if assumptions is None and p.symbol=='EURUSD':
                assumptions=dict(slippage_price=.00002,commission_round_trip_per_lot=7.)
            if assumptions is None:raise ValueError('POSITION_COSTS_UNAVAILABLE')
            slip=assumptions.get('slippage_price');fee=assumptions.get('commission_round_trip_per_lot')
            if any(not finite(v) or v<0 for v in (slip,fee)):raise ValueError('POSITION_COSTS_INVALID')
            quote=terminal.quote_for(p.symbol);long=p.type==terminal.sdk.POSITION_TYPE_BUY
            liquidation=quote['bid'] if long else quote['ask']
            if not finite(p.sl) or p.sl<=0 or not finite(p.tp) or p.tp<=0 or not (p.sl<liquidation if long else p.sl>liquidation):
                raise ValueError('POSITION_STOP_UNRESOLVED')
            request=intent['request']['broker'];tolerance=max(info.trade_tick_size or info.point,info.point)*.1
            if abs(p.sl-request['sl'])>tolerance or abs(p.tp-request['tp'])>tolerance:
                raise ValueError('POSITION_PROTECTION_CHANGED')
            order_type=terminal.sdk.ORDER_TYPE_BUY if long else terminal.sdk.ORDER_TYPE_SELL
            pnl=terminal.sdk.order_calc_profit(order_type,p.symbol,p.volume,liquidation,p.sl-(slip if long else -slip))
            if not finite(pnl) or pnl>=0:raise ValueError('POSITION_NATIVE_RISK_UNAVAILABLE')
            risk+=-pnl+fee*p.volume;symbols.append(p.symbol);tickets.append(p.ticket)
        return AccountRiskSnapshot(account_id,account.equity,day_start,peak,daily_entries,risk,
                                   tuple(symbols),tuple(tickets))
