"""Native calculators are fakes; PostgreSQL journal locks are real and isolated."""
from datetime import timedelta
from types import SimpleNamespace as N
from uuid import uuid4

from aurelia_fx.account_risk import AccountRiskBook,MAGIC
from .test_demo_intents_pg import DemoIntentTests


class AccountRiskTests(DemoIntentTests):
    def setup_risk(self):
        self.positions=[];self.orders=[]
        self.account=N(equity=50000.,balance=50000.,currency='USD')
        self.quotes={'EURUSD':dict(bid=1.1,ask=1.1001),'XAUUSD':dict(bid=4000.,ask=4000.2)}
        values={'EURUSD':100000.,'XAUUSD':100.}
        self.sdk=N(POSITION_TYPE_BUY=0,POSITION_TYPE_SELL=1,ORDER_TYPE_BUY=0,ORDER_TYPE_SELL=1,
            symbol_info=lambda s:N(trade_tick_size=.00001 if s=='EURUSD' else .01,point=.00001 if s=='EURUSD' else .01),
            order_calc_profit=lambda kind,s,lot,start,end:(1 if kind==0 else -1)*(end-start)*lot*values[s])
        self.terminal=N(sdk=self.sdk,account_id=self.owner['account_id'],check_account=lambda:self.account,
            orders=lambda:self.orders,positions=lambda:self.positions,quote_for=lambda s:self.quotes[s])
        return AccountRiskBook(self.memory)

    def position(self,scope,symbol='EURUSD',*,ticket=101,volume=.01,stop=None,session='eur'):
        client=uuid4().hex;price=self.quotes[symbol]['bid'];distance=.001 if symbol=='EURUSD' else 10.
        stop=stop if stop is not None else price-distance
        target=price+3*distance
        request=dict(broker=dict(symbol=symbol,volume=volume,sl=stop,tp=target),
                     metadata=dict(financial_assumptions=dict(slippage_price=.00002 if symbol=='EURUSD' else .02,
                                                              commission_round_trip_per_lot=7. if symbol=='EURUSD' else 0.)))
        scope.prepare(client,request,{**self.owner,'session_id':session});scope.begin_send(client)
        scope.transition(client,'CONFIRMED',evidence=dict(position_tickets=[ticket],position_ids=[ticket+1000]))
        p=N(symbol=symbol,ticket=ticket,identifier=ticket+1000,magic=MAGIC,type=0,
            volume=volume,sl=stop,tp=target,comment='AFX:'+client[:20])
        self.positions.append(p)
        return client,p

    def test_native_risk_for_both_symbols_shares_one_budget(self):
        book=self.setup_risk()
        with self.journal.locked() as scope:
            self.position(scope,'EURUSD');self.position(scope,'XAUUSD',ticket=102,session='gold')
            risk=book.observe(scope,self.terminal,now=self.now)
            self.assertAlmostEqual(risk.open_risk,11.11)
            self.assertEqual(risk.daily_entries,2)
            self.assertEqual(set(risk.position_symbols),{'EURUSD','XAUUSD'})
            risk.check('GBPUSD',200.)
            with self.assertRaisesRegex(ValueError,'AGGREGATE_RISK_LIMIT'):risk.check('GBPUSD',240.)
            with self.assertRaisesRegex(ValueError,'SYMBOL_EXPOSURE'):risk.check('EURUSD',1.)

    def test_two_sessions_do_not_each_receive_the_full_account_budget(self):
        book=self.setup_risk()
        with self.journal.locked() as scope:
            book.observe(scope,self.terminal,now=self.now).check('XAUUSD',200.)
            self.position(scope,'XAUUSD',ticket=102,volume=.2,session='gold')
            with self.assertRaises(RuntimeError):
                with self.journal.locked():pass
        with self.journal.locked() as scope:
            risk=book.observe(scope,self.terminal,now=self.now)
            self.assertGreater(risk.open_risk,200.)
            with self.assertRaisesRegex(ValueError,'AGGREGATE_RISK_LIMIT'):risk.check('EURUSD',60.)

    def test_peak_and_daily_reference_survive_symbol_changes_and_restart(self):
        book=self.setup_risk()
        with self.journal.locked() as scope:
            first=book.observe(scope,self.terminal,now=self.now)
        self.account.equity=48900.
        with self.journal.locked() as scope:
            again=AccountRiskBook(self.memory).observe(scope,self.terminal,now=self.now+timedelta(minutes=1))
            self.assertEqual(again.day_start,first.day_start)
            self.assertEqual(again.peak,first.peak)
            with self.assertRaisesRegex(ValueError,'DAILY_LOSS'):again.check('XAUUSD',1.)
            next_day=book.observe(scope,self.terminal,now=self.now+timedelta(days=1))
            self.assertEqual(next_day.day_start,48900.)
            self.assertEqual(next_day.peak,50000.)
            self.account.equity=47000.
            worst=book.observe(scope,self.terminal,now=self.now+timedelta(days=1,minutes=1))
            with self.assertRaisesRegex(ValueError,'DAILY_LOSS|DRAWDOWN'):worst.check('EURUSD',1.)

    def test_unresolved_send_and_foreign_positions_never_look_like_free_budget(self):
        book=self.setup_risk()
        with self.journal.locked() as scope:
            scope.prepare(self.client,dict(broker=self.request),self.owner);scope.begin_send(self.client)
            with self.assertRaisesRegex(ValueError,'UNRESOLVED_SEND'):book.observe(scope,self.terminal,now=self.now)
            scope.transition(self.client,'REJECTED')
            self.positions=[N(ticket=999,magic=123,symbol='XAUUSD')]
            with self.assertRaisesRegex(ValueError,'FOREIGN_OR_UNRECONCILED'):book.observe(scope,self.terminal,now=self.now)

    def test_native_calculation_failure_or_changed_protection_blocks_entry(self):
        book=self.setup_risk()
        with self.journal.locked() as scope:
            _,p=self.position(scope,'XAUUSD')
            self.sdk.order_calc_profit=lambda *a:None
            with self.assertRaisesRegex(ValueError,'NATIVE_RISK_UNAVAILABLE'):book.observe(scope,self.terminal,now=self.now)
            p.sl=3980.
            with self.assertRaisesRegex(ValueError,'PROTECTION_CHANGED'):book.observe(scope,self.terminal,now=self.now)

    def test_close_of_known_ticket_is_allowed_while_another_symbol_is_uncertain(self):
        self.setup_risk()
        with self.journal.locked() as scope:
            root,p=self.position(scope,'EURUSD',session=self.owner['session_id'])
            scope.prepare(self.client,dict(broker={**self.request,'symbol':'XAUUSD'}),{**self.owner,'session_id':'gold'})
            scope.begin_send(self.client)
            close=dict(position=p.ticket,broker=dict(position=p.ticket,symbol='EURUSD'))
            closing=uuid4().hex
            scope.prepare(closing,close,self.owner,risk_reduction_for=root);scope.begin_send(closing)
            scope.transition(closing,'UNCERTAIN')
            with self.assertRaises(ValueError):scope.prepare(uuid4().hex,close,self.owner,risk_reduction_for=root)
            with self.assertRaises(ValueError):scope.prepare(uuid4().hex,dict(broker=self.request),self.owner)

    def test_shared_daily_entry_cap_counts_both_symbols_and_not_rejected_requests(self):
        book=self.setup_risk()
        with self.journal.locked() as scope:
            for i in range(5):
                client,p=self.position(scope,'EURUSD' if i%2 else 'XAUUSD',ticket=100+i,session=str(i))
                scope.transition(client,'CLOSED');self.positions.remove(p)
            risk=book.observe(scope,self.terminal,now=self.now)
            self.assertEqual(risk.daily_entries,5)
            with self.assertRaisesRegex(ValueError,'DAILY_ENTRY_LIMIT'):risk.check('EURUSD',1.)

    def test_previous_native_account_high_water_is_not_reset_on_migration(self):
        book=self.setup_risk()
        legacy=dict(peak=51000.,day=self.now.date().isoformat(),day_start=50500.)
        text,sha=self.memory._encode(legacy)
        with self.journal.locked() as scope:
            scope.connection.execute("INSERT INTO project_records VALUES('agent_paper_account',%s,%s,%s,clock_timestamp())",('DEMO:'+self.owner['account_id'],text,sha))
            risk=book.observe(scope,self.terminal,now=self.now)
            self.assertEqual(risk.peak,51000.)
            self.assertEqual(risk.day_start,50500.)
