"""Native execution protocol tests; SDK is entirely fake."""
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace as N

from aurelia_fx.demo_gateway import DemoGateway, MAGIC
from aurelia_fx.operation_control import OperationControl
from .test_demo_intents_pg import DemoIntentTests


class GatewayTests(DemoIntentTests):
    def gateway(self):
        self.control=OperationControl(self.memory)
        with self.pool.connection() as c:
            self.control.append(c,dict(session_id='fixture-session',mode='demo',desired='running',generation=1,sequence=1))
        self.positions=[];self.orders=[];self.deals=[];self.sent=[]
        self.sdk=N(TRADE_RETCODE_DONE=10009,TRADE_RETCODE_REJECT=10006,
                   DEAL_ENTRY_IN=0,DEAL_ENTRY_OUT=1,DEAL_ENTRY_OUT_BY=3,DEAL_ENTRY_INOUT=2,
                   order_check=lambda _:N(retcode=0))
        def send(request):
            self.sent.append(request)
            return N(retcode=10009,deal=200,order=100,volume=.01,price=1.1,request_id=1)
        self.sdk.order_send=send
        def history(**kwargs):
            return [d for d in self.deals if ('ticket' not in kwargs or d.ticket==kwargs['ticket'])
                    and ('position' not in kwargs or d.position_id==kwargs['position'])]
        self.sdk.history_deals_get=lambda *args,**kwargs:history(**kwargs)
        self.terminal=N(sdk=self.sdk,check_account=lambda **kw:N(balance=1000,equity=1000,currency='USD'),
                        quote=lambda:dict(bid=1.1,ask=1.1001),positions=lambda:self.positions,
                        orders=lambda:self.orders,info=N(trade_tick_size=.00001,point=.00001))
        @contextmanager
        def factory(**kwargs):yield self.terminal
        self.auth=dict(scope='autonomous_demo_research',real_orders=False,account_id='fixture-account',
                       authorization_id='fixture-approval',protocol_id='fixture-model',
                       session_id='fixture-session',clock_id='fixture-clock')
        return DemoGateway(self.control,self.auth,factory)

    def trend_metadata(self):
        return dict(trend_snapshot=dict(regime="TREND",
            macro_trend=dict(direction="bullish",state="BULL_CONFIRMED"),
            context_trend=dict(direction="bullish",state="BULL_CONFIRMED")))

    def broker_request(self):
        return dict(action=1,symbol='EURUSD',volume=.01,type=0,sl=1.09,tp=1.12,magic=MAGIC)

    def test_countertrend_and_missing_context_never_reach_sdk(self):
        gateway=self.gateway()
        for metadata in [{},self.trend_metadata()]:
            with self.subTest(metadata=metadata),gateway.journal.locked() as scope:
                request={**self.broker_request(),'type':1}
                with self.assertRaises(ValueError):
                    gateway.send(self.terminal,scope,self.client,request,metadata,generation=1)
        self.assertEqual(self.sent,[])

    def test_confirmation_uses_deal_position_identifier_not_order_ticket(self):
        gateway=self.gateway()
        with gateway.journal.locked() as scope:
            intent=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.assertEqual(intent['status'],'UNCERTAIN')
            self.positions=[N(ticket=900,identifier=800,magic=MAGIC,symbol='EURUSD',comment='',sl=1.09,tp=1.12)]
            self.deals=[N(ticket=200,position_id=800,magic=MAGIC,symbol='EURUSD',entry=0,comment='')]
            resolved=gateway.resolve(self.terminal,scope,intent)
            self.assertEqual(resolved['status'],'CONFIRMED')
            self.assertEqual(resolved['evidence']['position_tickets'],[900])
            gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.assertEqual(len(self.sent),1)

    def test_sdk_timeout_is_durable_and_never_resent(self):
        gateway=self.gateway()
        def fail(request):self.sent.append(request);raise TimeoutError('fixture')
        self.sdk.order_send=fail
        with gateway.journal.locked() as scope:
            intent=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.assertEqual(intent['status'],'UNCERTAIN')
        with gateway.journal.locked() as scope:
            again=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.assertEqual(again['status'],'UNCERTAIN')
            self.assertEqual(len(self.sent),1)

    def test_sent_intent_without_checkpoint_is_detected_even_when_stopped(self):
        from aurelia_fx.agent_live import demo_recovery_required
        gateway=self.gateway()
        with gateway.journal.locked() as scope:
            gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
        state={**self.control.status(),'demo_authorization':self.auth,'desired':'stopped','position':None}
        self.assertTrue(demo_recovery_required(self.control,state))
        self.assertEqual(len(self.sent),1)

    def test_missing_native_stop_is_marked_unprotected(self):
        gateway=self.gateway()
        with gateway.journal.locked() as scope:
            intent=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.positions=[N(ticket=900,identifier=800,magic=MAGIC,symbol='EURUSD',
                              comment='AFX:'+self.client[:20],sl=0,tp=1.12)]
            result=gateway.resolve(self.terminal,scope,intent)
            self.assertEqual(result['status'],'UNPROTECTED')
            self.assertEqual(result['evidence']['position_tickets'],[900])

    def test_active_close_order_stays_pending_without_duplicate_close(self):
        gateway=self.gateway()
        with gateway.journal.locked() as scope:
            request={**self.broker_request(),'position':900}
            intent=gateway.send(self.terminal,scope,self.client,request,{})
            self.orders=[N(magic=MAGIC,comment='AFX:'+self.client[:20])]
            self.positions=[]
            result=gateway.resolve(self.terminal,scope,intent)
            self.assertEqual(result['status'],'PARTIAL')
            self.assertEqual(scope.pending('fixture-account')[0]['status'],'PARTIAL')
            self.assertEqual(len(self.sent),1)

    def test_foreign_deal_in_same_position_is_not_automatically_closed(self):
        gateway=self.gateway()
        with gateway.journal.locked() as scope:
            intent=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.positions=[N(ticket=900,identifier=800,magic=MAGIC,symbol='EURUSD',
                              comment='AFX:'+self.client[:20],sl=1.09,tp=1.12)]
            self.deals=[N(ticket=201,position_id=800,magic=999,symbol='EURUSD',volume=.01)]
            with self.assertRaises(ValueError):gateway.resolve(self.terminal,scope,intent)
            self.assertEqual(len(self.sent),1)

    def test_pause_before_linearized_send_cancels_without_sdk_order(self):
        gateway=self.gateway()
        with self.pool.connection() as c:
            state=self.control.latest(c);self.control.append(c,{**state,'desired':'paused','sequence':2})
        with gateway.journal.locked() as scope:
            result=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.assertEqual(result['status'],'CANCELLED')
        self.assertEqual(self.sent,[])

    def test_closed_result_includes_fees_and_swap(self):
        gateway=self.gateway()
        with gateway.journal.locked() as scope:
            intent=gateway.send(self.terminal,scope,self.client,self.broker_request(),self.trend_metadata(),generation=1)
            self.deals=[N(ticket=200,position_id=800,magic=MAGIC,symbol='EURUSD',entry=0,
                          comment='',volume=.01,price=1.1,profit=0,commission=-.035,swap=0,fee=0),
                        N(ticket=201,position_id=800,magic=MAGIC,symbol='EURUSD',entry=1,
                          comment='',volume=.01,price=1.12,profit=20,commission=-.035,swap=-.1,fee=-.01)]
            result=gateway.resolve(self.terminal,scope,intent)
            self.assertEqual(result['status'],'CLOSED')
            self.assertAlmostEqual(result['evidence']['net_pnl'],19.82)
            self.assertEqual(result['evidence']['position_ids'],[800])
