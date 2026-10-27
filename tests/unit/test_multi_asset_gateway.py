"""Exercise the account gate through the real gateway; SDK sends are simulated."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace as N
from unittest.mock import Mock

from aurelia_fx.agent_demo import NativeDemoAccount
from aurelia_fx.demo_gateway import DemoGateway,MAGIC
from aurelia_fx.domain import Candidate
from aurelia_fx.operation_control import OperationControl
from .test_account_risk import AccountRiskTests
from .test_demo_intents_pg import DemoIntentTests
from .test_instrument_research import profile


class MultiGatewayTests(DemoIntentTests):
    def setup_gateways(self,eur_lot='.01',gold_lot='.01'):
        AccountRiskTests.setup_risk(self);self.sent=[];self.deals=[]
        gold=profile();self.gold=gold
        eur=replace(profile('EURUSD').contract,digits=5,point=.00001,tick_size=.00001,contract_size=100000.,calculation_mode=0)
        self.contracts={'EURUSD':eur,'XAUUSD':gold.contract}
        self.account.company=gold.contract.broker;self.account.server=gold.contract.server
        self.account.margin_free=50000.;self.account.trade_allowed=True;self.account.trade_expert=True
        def info(symbol):
            c=self.contracts[symbol]
            return N(name=symbol,description=c.description,currency_base='EUR' if symbol=='EURUSD' else 'XAU',
                currency_profit=c.currency_profit,currency_margin=c.currency_margin,digits=c.digits,
                point=c.point,trade_tick_size=c.tick_size,trade_contract_size=c.contract_size,
                volume_min=c.volume_min,volume_max=c.volume_max,volume_step=c.volume_step,
                trade_stops_level=1,trade_calc_mode=c.calculation_mode,trade_mode=4,
                filling_mode=1,trade_exemode=2)
        self.sdk.symbol_info=info
        self.sdk.SYMBOL_TRADE_MODE_FULL=4;self.sdk.SYMBOL_TRADE_EXECUTION_MARKET=2
        self.sdk.ORDER_FILLING_FOK=0;self.sdk.ORDER_FILLING_IOC=1;self.sdk.ORDER_FILLING_RETURN=2
        self.sdk.TRADE_ACTION_DEAL=1;self.sdk.ORDER_TIME_GTC=0
        self.sdk.TRADE_RETCODE_DONE=10009;self.sdk.DEAL_ENTRY_IN=0
        self.sdk.order_calc_margin=lambda *a:0.
        self.sdk.order_check=lambda request:N(retcode=0)
        def send(request):
            self.sent.append(request)
            ticket=900+len(self.sent);identifier=800+len(self.sent);deal_id=200+len(self.sent)
            price=self.quotes[request['symbol']]['ask']
            self.positions.append(N(ticket=ticket,identifier=identifier,symbol=request['symbol'],
                magic=MAGIC,type=request['type'],volume=request['volume'],sl=request['sl'],tp=request['tp'],
                comment=request['comment'],price_open=price,profit=0.,swap=0.))
            self.deals.append(N(ticket=deal_id,position_id=identifier,magic=MAGIC,symbol=request['symbol'],
                entry=0,volume=request['volume'],price=price,comment=request['comment']))
            return N(retcode=10009,deal=deal_id,order=ticket,volume=request['volume'],price=price,request_id=1)
        self.sdk.order_send=send
        self.sdk.history_deals_get=lambda **kw:[d for d in self.deals if
            ('ticket' not in kw or d.ticket==kw['ticket']) and ('position' not in kw or d.position_id==kw['position'])]
        @contextmanager
        def factory(**kw):
            symbol=kw['profile'].symbol if kw.get('profile') else 'EURUSD'
            quote=lambda s:{**self.quotes[s],'at':datetime.now(timezone.utc).isoformat()}
            yield N(sdk=self.sdk,info=info(symbol),symbol=symbol,account_id=self.owner['account_id'],
                account=self.account,terminal=N(trade_allowed=True,tradeapi_disabled=False),
                check_account=lambda **k:self.account,positions=lambda:self.positions,orders=lambda:self.orders,
                quote=lambda:quote(symbol),quote_for=quote)
        gateways={}
        for symbol,lot in (('EURUSD',eur_lot),('XAUUSD',gold_lot)):
            control=OperationControl(self.memory,symbol)
            auth=dict(scope='autonomous_demo_research',real_orders=False,account_id=self.owner['account_id'],
                authorization_id='fixture:'+symbol,protocol_id='fixture:'+symbol,session_id='session:'+symbol,
                clock_id='fixture',lot=lot)
            if symbol=='XAUUSD':auth.update(symbol=symbol,research_profile=gold.as_dict())
            with self.pool.connection() as c:
                control.append(c,dict(session_id=auth['session_id'],mode='demo',desired='running',generation=1,sequence=1))
            gateways[symbol]=DemoGateway(control,auth,factory)
        return gateways

    def setup(self,symbol):
        price,dist=(1.1,.002) if symbol=='EURUSD' else (4000.,10.)
        snapshot=dict(regime='TREND',macro_trend=dict(direction='bullish',state='BULL_CONFIRMED'),
                      context_trend=dict(direction='bullish',state='BULL_CONFIRMED'))
        if symbol=='XAUUSD':snapshot.update(symbol=symbol,profile_id=self.gold.fingerprint)
        return dict(candidate=Candidate('long',price,price-dist,price+3*dist,
            datetime.now(timezone.utc)+timedelta(minutes=5),('fixture',)),
            signal_at=self.now.isoformat(),snapshot=snapshot)

    def enter(self,gateway,symbol,lot):
        hypothesis=dict(id='context_pullback',protocol_id=gateway.authorization['protocol_id'])
        return gateway.enter(self.setup(symbol),hypothesis,{},lot,{},1)

    def test_two_symbols_can_enter_within_one_shared_budget(self):
        g=self.setup_gateways()
        for symbol in ('EURUSD','XAUUSD'):
            self.assertEqual(self.enter(g[symbol],symbol,'.01')['status'],'CONFIRMED')
        self.assertEqual(len(self.sent),2)
        self.assertEqual({p.symbol for p in self.positions},{'EURUSD','XAUUSD'})
        g['XAUUSD'].close_positions=Mock()
        result=g['XAUUSD'].reconcile(force_close=True)
        self.assertTrue(all(i['request']['broker']['symbol']=='XAUUSD' for i in result['intents']))
        self.assertEqual(set(result['known_position_tickets']),{p.ticket for p in self.positions})
        args=g['XAUUSD'].close_positions.call_args.args
        self.assertEqual({p.symbol for p in args[3]},{'XAUUSD'})
        account=NativeDemoAccount(g['XAUUSD'],self.contracts['XAUUSD'].as_dict())
        account.sync()
        self.assertFalse(account.data['pending_execution'])
        self.assertEqual(account.data['symbol'],'XAUUSD')
        self.assertEqual(account.data['units'],.01)
        self.assertEqual(account.data['closed_trades'],0)

    def test_second_asset_is_rejected_when_combined_risk_exceeds_account_limit(self):
        g=self.setup_gateways(eur_lot='1',gold_lot='.05')
        self.assertEqual(self.enter(g['EURUSD'],'EURUSD','1')['status'],'CONFIRMED')
        with self.assertRaisesRegex(ValueError,'AGGREGATE_RISK_LIMIT'):
            self.enter(g['XAUUSD'],'XAUUSD','.05')
        self.assertEqual(len(self.sent),1)

    def test_increasing_lot_beyond_authorization_never_calls_sdk(self):
        g=self.setup_gateways()
        with self.assertRaisesRegex(ValueError,'AUTHORIZED_LOT_MISMATCH'):
            self.enter(g['EURUSD'],'EURUSD','.1')
        self.assertEqual(self.sent,[])
