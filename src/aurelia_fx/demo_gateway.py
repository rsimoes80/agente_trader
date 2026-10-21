"""Native DEMO requests with durable send markers and broker reconciliation."""

import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

from .agent_model import fingerprint
from .demo_intents import DemoIntentJournal
from .operation_control import LOCK, validate_lot
from .historical.core import utc

MAGIC=70616041
NON_EXECUTION=("REQUOTE","REJECT","CANCEL","INVALID","INVALID_VOLUME","INVALID_PRICE",
               "INVALID_STOPS","TRADE_DISABLED","MARKET_CLOSED","NO_MONEY","PRICE_CHANGED",
               "PRICE_OFF","INVALID_EXPIRATION","INVALID_FILL","INVALID_ORDER",
               "LONG_ONLY","SHORT_ONLY","CLOSE_ONLY","LIMIT_VOLUME","LIMIT_ORDERS",
               "POSITION_CLOSED")


def finite(value):
    return isinstance(value,(int,float)) and math.isfinite(value)


def filling(sdk,info):
    if info.filling_mode & 1:return sdk.ORDER_FILLING_FOK
    if info.filling_mode & 2:return sdk.ORDER_FILLING_IOC
    if info.trade_exemode!=sdk.SYMBOL_TRADE_EXECUTION_MARKET:return sdk.ORDER_FILLING_RETURN
    raise ValueError("O símbolo não informou política de preenchimento executável.")


def price_level(value,step,*,up):
    unit=Decimal(str(step))
    if not unit.is_finite() or unit<=0:raise ValueError("Precisão do contrato inválida.")
    return float((Decimal(str(value))/unit).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*unit)


def result_view(result):
    return {k:getattr(result,k,None) for k in ("retcode","deal","order","volume","price","request_id")}


class DemoGateway:
    def __init__(self,control,authorization,terminal_factory):
        if authorization.get("scope")!="autonomous_demo_research" or authorization.get("real_orders") is not False:
            raise ValueError("Autorização específica de pesquisa demo ausente.")
        self.control=control;self.authorization=authorization;self.terminal_factory=terminal_factory
        self.journal=DemoIntentJournal(control.memory)

    def terminal(self):
        return self.terminal_factory(account_id=self.authorization["account_id"],clock_id=self.authorization["clock_id"])

    def owner(self):
        return dict(account_id=self.authorization["account_id"],approval_id=self.authorization["authorization_id"],
                    model_id=self.authorization["protocol_id"],session_id=self.authorization["session_id"],
                    clock_id=self.authorization["clock_id"])

    def entry_request(self,terminal,setup,lot,risk_state):
        sdk=terminal.sdk;info=terminal.info;quote=terminal.quote()
        terminal.check_account(sending=True)
        validate_lot(lot,dict(volume_min=info.volume_min,volume_max=info.volume_max,volume_step=info.volume_step))
        if terminal.positions() or terminal.orders():raise ValueError("Há exposição ou ordem na conta demo; nova entrada recusada.")
        if info.trade_mode!=sdk.SYMBOL_TRADE_MODE_FULL:raise ValueError("O símbolo não permite novas posições.")
        candidate=setup["candidate"];long=candidate.side=="long"
        entry=quote["ask"] if long else quote["bid"]
        step=info.trade_tick_size or info.point
        # Quantization is conservative and happens before the final risk check.
        stop=price_level(candidate.stop,step,up=not long)
        target=price_level(candidate.target,step,up=not long)
        if not (stop<entry<target if long else target<entry<stop):raise ValueError("O preço invalidou os níveis da hipótese demo.")
        spread=(quote["ask"]-quote["bid"])/0.0001
        if spread>2:raise ValueError("Spread demo acima do limite.")
        trigger=quote["bid"] if long else quote["ask"]
        minimum=info.trade_stops_level*info.point
        if min(abs(trigger-stop),abs(target-trigger))<minimum:raise ValueError("Stop/alvo abaixo da distância mínima da corretora.")
        if datetime.now(timezone.utc)>=candidate.expires_at:raise ValueError("A hipótese demo expirou.")
        account=terminal.account
        equity=account.equity
        if not finite(equity) or equity<=0:raise ValueError("Equidade demo inválida.")
        if risk_state["daily_entries"]>=5:raise ValueError("Limite diário de operações demo atingido.")
        if equity<=risk_state["day_start"]*.98:raise ValueError("Limite diário de perda demo atingido.")
        if equity<=risk_state["peak"]*.95:raise ValueError("Limite de drawdown demo atingido.")
        order_type=sdk.ORDER_TYPE_BUY if long else sdk.ORDER_TYPE_SELL
        units=float(lot)*info.trade_contract_size
        commission=70*units/1_000_000
        sign=1 if long else -1
        stop_result=sdk.order_calc_profit(order_type,terminal.symbol,float(lot),entry,stop-sign*.00002)
        target_result=sdk.order_calc_profit(order_type,terminal.symbol,float(lot),entry,target-sign*.00002)
        if not finite(stop_result) or not finite(target_result) or stop_result>=0:raise ValueError("Não foi possível calcular o risco na moeda da conta demo.")
        risk=-stop_result+commission;reward=target_result-commission
        if risk>equity*.005:raise ValueError("O lote escolhido excede o orçamento de risco demo.")
        if reward/risk<2:raise ValueError("Relação retorno/risco demo insuficiente após custos.")
        margin=sdk.order_calc_margin(order_type,terminal.symbol,float(lot),entry)
        if not finite(margin) or margin<0 or margin>account.margin_free:raise ValueError("Margem demo insuficiente ou indisponível.")
        request=dict(action=sdk.TRADE_ACTION_DEAL,symbol=terminal.symbol,volume=float(lot),type=order_type,
                     sl=stop,tp=target,deviation=max(1,int(.00002/info.point)),magic=MAGIC,
                     type_time=sdk.ORDER_TIME_GTC,type_filling=filling(sdk,info))
        if info.trade_exemode!=sdk.SYMBOL_TRADE_EXECUTION_MARKET:request["price"]=entry
        return request,dict(initial_risk=risk,quoted_entry=entry,stop=stop,target=target,quote_at=quote["at"])

    def send(self,terminal,scope,client_id,request,metadata,*,generation=None,risk_reduction_for=None):
        previous=scope.latest(client_id)
        if previous:return previous
        sdk=terminal.sdk;terminal.check_account(sending=True)
        request={**request,"comment":"AFX:"+client_id[:20]}
        check=sdk.order_check(request)
        if check is None or check.retcode!=0:
            raise ValueError("A corretora recusou a verificação prévia da ordem demo.")
        scope.prepare(client_id,dict(broker=request,metadata=metadata,
                                    **({"position":request["position"]} if "position" in request else {})),
                      self.owner(),risk_reduction_for=risk_reduction_for)
        # The send intent is linearized against pause/stop, then committed BEFORE
        # calling the SDK. Later cancellation cannot erase an already sent intent.
        with scope.connection.transaction():
            scope.connection.execute("SELECT pg_advisory_xact_lock(%s)",(LOCK,))
            state=self.control.latest(scope.connection)
            if "position" not in request and (state.get("session_id")!=self.authorization["session_id"]
                or state["desired"]!="running" or state.get("generation")!=generation):
                scope.transition(client_id,"CANCELLED",evidence=dict(reason="OPERATOR_INTENT_CHANGED"))
                return scope.latest(client_id)
            terminal.check_account(sending=True)
            terminal.quote()
            scope.begin_send(client_id)
        try:
            result=sdk.order_send(request)
        except Exception as exc:
            return scope.transition(client_id,"UNCERTAIN",evidence=dict(error_type=type(exc).__name__))
        if result is None:return scope.transition(client_id,"UNCERTAIN",evidence=dict(reason="EMPTY_SDK_RESULT"))
        evidence=dict(result=result_view(result))
        rejected={value for name in NON_EXECUTION
                  if (value:=getattr(sdk,"TRADE_RETCODE_"+name,None)) is not None}
        if result.retcode in rejected:
            return scope.transition(client_id,"REJECTED",evidence=evidence)
        return scope.transition(client_id,"UNCERTAIN",evidence=evidence)

    def resolve(self,terminal,scope,intent):
        """Confirm only positively identified exposure or a complete deal path."""
        sdk=terminal.sdk;request=intent["request"]["broker"]
        marker="AFX:"+intent["client_id"][:20]
        positions=terminal.positions();orders=terminal.orders()
        if "position" in request:
            present=[p for p in positions if p.ticket==request["position"] and p.magic==MAGIC]
            own_order=[o for o in orders if o.magic==MAGIC and marker in o.comment]
            if own_order:
                return scope.transition(intent['client_id'],'PARTIAL',evidence=dict(reason='CLOSE_ORDER_STILL_ACTIVE'))
            if not present and not own_order:
                if intent["status"] in {"SENDING","UNCERTAIN","PARTIAL"}:
                    return scope.transition(intent["client_id"],"CONFIRMED",evidence=dict(closed_ticket=request["position"]))
            deal_id=intent.get("evidence",{}).get("result",{}).get("deal")
            if deal_id and intent["status"] in {"SENDING","UNCERTAIN","PARTIAL"}:
                deals=sdk.history_deals_get(ticket=int(deal_id))
                if deals and all(d.magic==MAGIC and d.entry in {sdk.DEAL_ENTRY_OUT,sdk.DEAL_ENTRY_OUT_BY} for d in deals):
                    return scope.transition(intent["client_id"],"CONFIRMED",evidence=dict(closed_ticket=request["position"],partial_close=bool(present)))
            return intent
        matched=[p for p in positions if p.magic==MAGIC and p.symbol==request["symbol"] and marker in p.comment]
        position_ids=set(intent.get("evidence",{}).get("position_ids",[]))
        deal_ticket=intent.get("evidence",{}).get("result",{}).get("deal")
        deals=[]
        if deal_ticket:
            found=sdk.history_deals_get(ticket=int(deal_ticket))
            if found is None:raise RuntimeError("Histórico de execução demo indisponível.")
            deals.extend(found)
        if not matched and not position_ids:
            found=sdk.history_deals_get(utc(intent["created_at"])-timedelta(days=2),datetime.now(timezone.utc)+timedelta(days=2))
            if found is None:raise RuntimeError("Histórico de reconciliação demo indisponível.")
            deals.extend(d for d in found if d.magic==MAGIC and d.symbol==request["symbol"] and marker in d.comment)
        for deal in deals:
            if deal.magic==MAGIC and deal.symbol==request["symbol"]:position_ids.add(deal.position_id)
        for p in matched:position_ids.add(p.identifier)
        if position_ids:
            for position_id in position_ids:
                history=sdk.history_deals_get(position=int(position_id))
                if history is None:raise RuntimeError('Histórico da posição demo indisponível.')
                if any(getattr(d,'volume',0)>0 and d.magic!=MAGIC for d in history):
                    raise ValueError('A posição recebeu negócios externos; encerramento automático bloqueado para não afetar operações alheias.')
            matched=[p for p in positions if p.magic==MAGIC and p.identifier in position_ids]
        own_orders=[o for o in orders if o.magic==MAGIC and (marker in o.comment or o.ticket==intent.get("evidence",{}).get("result",{}).get("order"))]
        proof=dict(position_ids=sorted(position_ids),position_tickets=[p.ticket for p in matched],
                   result=intent.get("evidence",{}).get("result",{}))
        if matched:
            tolerance=max(terminal.info.trade_tick_size,terminal.info.point)*.1
            protected=all(p.sl>0 and p.tp>0 and abs(p.sl-request["sl"])<=tolerance and abs(p.tp-request["tp"])<=tolerance for p in matched)
            target="UNPROTECTED" if not protected else "PARTIAL" if own_orders else "CONFIRMED"
            if intent["status"]!=target:
                intent=scope.transition(intent["client_id"],target,evidence=proof)
            return {**intent,"observed_positions":matched}
        if position_ids and not own_orders:
            complete=True;all_deals=[]
            for position_id in position_ids:
                history=sdk.history_deals_get(position=int(position_id))
                if history is None:raise RuntimeError("Histórico da posição demo indisponível.")
                all_deals.extend(history)
                incoming=sum(d.volume for d in history if d.entry==sdk.DEAL_ENTRY_IN)
                outgoing=sum(d.volume for d in history if d.entry in {sdk.DEAL_ENTRY_OUT,sdk.DEAL_ENTRY_OUT_BY})
                complete=complete and incoming>0 and outgoing>=incoming-1e-8 and not any(d.entry==sdk.DEAL_ENTRY_INOUT for d in history)
            if complete:
                proof.update(already_closed=True,net_pnl=sum(d.profit+d.commission+d.swap+getattr(d,"fee",0) for d in all_deals),
                             deal_tickets=sorted({d.ticket for d in all_deals}),
                             filled_volume=sum(d.volume for d in all_deals if d.entry==sdk.DEAL_ENTRY_IN),
                             weighted_entry=sum(d.price*d.volume for d in all_deals if d.entry==sdk.DEAL_ENTRY_IN)/sum(d.volume for d in all_deals if d.entry==sdk.DEAL_ENTRY_IN))
                if intent["status"] in {"SENDING","UNCERTAIN","PARTIAL"}:
                    intent=scope.transition(intent["client_id"],"CONFIRMED",evidence=proof)
                if intent["status"] in {"CONFIRMED","UNPROTECTED"}:
                    return scope.transition(intent["client_id"],"CLOSED",evidence=proof)
        return intent

    def enter(self,setup,hypothesis,features,lot,risk_state,generation):
        client_id=fingerprint(dict(session=self.authorization["session_id"],signal=setup["signal_at"],hypothesis=hypothesis["id"]))[:32]
        with self.journal.locked() as scope, self.terminal() as terminal:
            previous=scope.latest(client_id)
            if previous:return self.resolve(terminal,scope,previous)
            request,risk=self.entry_request(terminal,setup,lot,risk_state)
            metadata=dict(**risk,side=setup["candidate"].side,hypothesis=hypothesis,features=features,
                          signal_at=setup["signal_at"],entry_at=datetime.now(timezone.utc).isoformat())
            result=self.send(terminal,scope,client_id,request,metadata,generation=generation)
            if result["status"] in {"UNCERTAIN","SENDING","PARTIAL"}:
                result=self.resolve(terminal,scope,result)
            return result

    def reconcile(self,*,force_close=False,close_expired=True):
        with self.journal.locked() as scope, self.terminal() as terminal:
            resolved=[]
            # Reconcile old close requests first; they may have completed while offline.
            intents=scope.for_account(self.authorization["account_id"])
            for intent in sorted(intents,key=lambda i:"position" not in i["request"]["broker"]):
                if intent["status"]=="PREPARED":
                    intent=scope.transition(intent["client_id"],"CANCELLED",evidence=dict(reason="RECOVERED_UNSENT_INTENT"))
                if intent["status"] in {"SENDING","UNCERTAIN","PARTIAL","UNPROTECTED","CONFIRMED"}:
                    intent=self.resolve(terminal,scope,intent)
                if "position" in intent["request"]["broker"]:continue
                if intent["status"] in {"REJECTED","CANCELLED"}:continue
                positions=intent.get("observed_positions",[])
                expired=close_expired and datetime.now(timezone.utc)>=utc(intent["created_at"])+timedelta(hours=1)
                risk_breach=False
                for p in positions:
                    loss=terminal.sdk.order_calc_profit(terminal.sdk.ORDER_TYPE_BUY if p.type==terminal.sdk.POSITION_TYPE_BUY else terminal.sdk.ORDER_TYPE_SELL,
                         p.symbol,p.volume,p.price_open,p.sl)
                    if not finite(loss) or loss>=0 or -loss+70*p.volume*terminal.info.trade_contract_size/1_000_000>terminal.account.equity*.005:risk_breach=True
                if positions and (force_close or expired or risk_breach or intent["status"]=="UNPROTECTED"):
                    self.close_positions(terminal,scope,intent,positions)
                    intent=self.resolve(terminal,scope,scope.latest(intent["client_id"]))
                resolved.append(intent)
            account=terminal.check_account()
            positions=terminal.positions();orders=terminal.orders()
            return dict(intents=resolved,balance=account.balance,equity=account.equity,
                        positions=positions,orders=orders,currency=account.currency,
                        trading_enabled=bool(terminal.terminal.trade_allowed and not terminal.terminal.tradeapi_disabled
                            and account.trade_allowed and account.trade_expert))

    def close_positions(self,terminal,scope,root,positions):
        for position in positions:
            if position.magic!=MAGIC or position.symbol!=terminal.symbol:
                raise ValueError("Recusado encerramento de posição alheia ao projeto.")
            if any(i["client_id"]!=root["client_id"] for i in scope.pending(self.authorization["account_id"])):
                return
            current=[p for p in terminal.positions() if p.ticket==position.ticket and p.magic==MAGIC]
            if not current:continue
            position=current[0];quote=terminal.quote();sdk=terminal.sdk
            long=position.type==sdk.POSITION_TYPE_BUY
            request=dict(action=sdk.TRADE_ACTION_DEAL,symbol=position.symbol,position=position.ticket,
                         volume=position.volume,type=sdk.ORDER_TYPE_SELL if long else sdk.ORDER_TYPE_BUY,
                         deviation=max(1,int(.00002/terminal.info.point)),magic=MAGIC,
                         type_time=sdk.ORDER_TIME_GTC,type_filling=filling(sdk,terminal.info))
            if terminal.info.trade_exemode!=sdk.SYMBOL_TRADE_EXECUTION_MARKET:request["price"]=quote["bid"] if long else quote["ask"]
            client=fingerprint(dict(close=root["client_id"],ticket=position.ticket,volume=position.volume,
                                    retry_window=int(datetime.now(timezone.utc).timestamp())//30))[:32]
            result=self.send(terminal,scope,client,request,dict(reduces=root["client_id"]),
                             risk_reduction_for=root["client_id"] if root["status"] in {"UNPROTECTED","PARTIAL"} else None)
            if result["status"] in {"SENDING","UNCERTAIN","PARTIAL"}:self.resolve(terminal,scope,result)
