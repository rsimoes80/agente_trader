"""Broker proof learning and restart tests, isolated PostgreSQL schema."""
from types import SimpleNamespace as N
from datetime import datetime, timezone
from .test_demo_intents_pg import DemoIntentTests
from aurelia_fx.agent_demo import NativeDemoAccount
from aurelia_fx.agent_live import commit
from aurelia_fx.operation_control import OperationControl


class NativeAccountTests(DemoIntentTests):
    def setup_account(self):
        control=OperationControl(self.memory)
        auth=dict(session_id='fixture-session',lot='0.01',protocol_id='fixture-model',
                  clock_id='fixture-clock',account_id='fixture-account')
        with self.pool.connection() as c:
            control.append(c,dict(session_id=auth['session_id'],sequence=1,desired='running',
                                 mode='demo',execution_owner='worker',generation=1))
        now=datetime.now(timezone.utc).isoformat()
        intent=dict(client_id=self.client,owner=dict(session_id=auth['session_id']),
                    status='CLOSED',created_at=now,
                    request=dict(broker=dict(volume=.01),metadata=dict(side='long',entry_at=now,
                        stop=1.09,target=1.12,initial_risk=10,quoted_entry=1.1,
                        hypothesis=dict(id='price_action_pullback',context='RANGE',protocol_id='fixture-model'))),
                    evidence=dict(net_pnl=-5,filled_volume=.01,weighted_entry=1.1,
                                  position_ids=[800],deal_tickets=[200,201]))
        result=dict(intents=[intent],balance=995,equity=995,orders=[],positions=[],currency='USD')
        gateway=N(authorization=auth,control=control,reconcile=lambda **kw:result)
        contract=dict(currency_profit='USD',contract_size=100000)
        return control,gateway,contract,result

    def test_broker_loss_learned_once_across_commit_and_restart(self):
        control,gateway,contract,result=self.setup_account()
        account=NativeDemoAccount(gateway,contract)
        account.sync()
        self.assertEqual(account.data['losses'],1)
        self.assertEqual(account.events[-1]['mode'],'demo')
        self.assertEqual(account.data['balance'],995)
        self.assertEqual(account.data['lab_state']['live']['RANGE']['price_action_pullback']['n'],1)
        account.sync()
        self.assertEqual(account.data['losses'],1)
        self.assertTrue(commit(control,account,'worker',generation=1))
        restored=NativeDemoAccount(gateway,contract,checkpoint=account.snapshot())
        restored.sync()
        self.assertEqual(restored.data['losses'],1)
        self.assertEqual(restored.events,[])
        self.assertEqual(restored.summary()['mode'],'demo')

    def test_unknown_execution_blocks_entry_without_invented_position(self):
        _,gateway,contract,result=self.setup_account()
        result['intents'][0]['status']='UNCERTAIN'
        account=NativeDemoAccount(gateway,contract)
        account.sync()
        self.assertTrue(account.data['pending_execution'])
        self.assertIsNone(account.data['position'])
        self.assertEqual(account.data['closed_trades'],0)

    def test_pause_after_native_fill_does_not_erase_broker_exposure(self):
        control,gateway,contract,result=self.setup_account()
        intent=result['intents'][0];intent['status']='CONFIRMED'
        intent['observed_positions']=[N(ticket=900,volume=.01,price_open=1.1)]
        result['positions']=intent['observed_positions']
        account=NativeDemoAccount(gateway,contract);account.sync()
        with self.pool.connection() as c:
            state=control.latest(c);control.append(c,{**state,'desired':'paused','generation':2,'sequence':2})
        self.assertTrue(commit(control,account,'worker',generation=1))
        self.assertEqual(control.status()['position']['broker_tickets'],[900])
