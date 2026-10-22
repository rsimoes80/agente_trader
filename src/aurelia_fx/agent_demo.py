"""Broker-backed demo account. Never synthesizes fills from chart quotes."""
import copy
from datetime import datetime, timezone

from .agent_paper import PaperAccount
from .agent_model import fingerprint
from .autonomous_lab import learn
from .historical.core import utc


class NativeDemoAccount(PaperAccount):
    def event(self,kind,at,**fields):
        event=dict(session_id=self.data['session_id'],mode='demo',status=kind,
                   at=at,model_id=self.data['model_id'],**fields)
        event['event_id']=fingerprint(event)
        self.events.append(event)
        return event

    def __init__(self, gateway, contract, *, checkpoint=None, previous_account=None):
        auth=gateway.authorization
        super().__init__(auth['session_id'],auth['lot'],contract,auth['protocol_id'],
                         auth['clock_id'],research_mode=True)
        self.gateway=gateway
        self.applied=[]
        self.seen=set()
        self.data.update(execution_mode='demo',account_key='DEMO:'+auth['account_id'],
                         authorization=auth,pending_execution=False,realized_pnl=0,
                         quote_basis='MT5 demo broker positions and deals',broker_equity=None)
        if checkpoint:
            for key in ('session_id','lot','model_id','clock_id','account_key'):
                if checkpoint.get(key)!=self.data[key]:
                    raise ValueError('Checkpoint demo incompatível; exposição preservada para reconciliação.')
            self.data=copy.deepcopy(checkpoint)
        elif previous_account:
            if previous_account.get('position') or previous_account.get('pending_execution'):
                raise ValueError('A sessão demo anterior ainda requer reconciliação.')
            for key in ('lab_state','peak','day_start','day','daily_entries','closed_trades',
                        'wins','losses','realized_today','realized_pnl','last_candle'):
                self.data[key]=copy.deepcopy(previous_account[key])
        else:
            # Actual broker balance initializes the risk reference, never paper USD 10k.
            self.data.update(peak=None,day_start=None)

    def applied_before(self,key):
        if key in self.seen:return True
        with self.gateway.control.memory.pool.connection() as c:
            row=c.execute("SELECT 1 FROM project_records WHERE record_type='agent_demo_applied' AND record_key=%s LIMIT 1",(key,)).fetchone()
        return bool(row)

    def position_view(self,intent,positions=None):
        meta=intent['request']['metadata'];request=intent['request']['broker']
        positions=positions or []
        volume=sum(p.volume for p in positions) if positions else intent['evidence'].get('filled_volume',request['volume'])
        entry=(sum(p.price_open*p.volume for p in positions)/volume if positions
               else intent['evidence'].get('weighted_entry',meta['quoted_entry']))
        return dict(decision_id=intent['client_id'],side=meta['side'],
                    sign=1 if meta['side']=='long' else -1,lot=volume,
                    entry=entry,entry_at=meta['entry_at'],stop=meta['stop'],target=meta['target'],
                    initial_risk=meta['initial_risk'],hypothesis=meta['hypothesis'],
                    coverage_uncertain=False,broker_tickets=[p.ticket for p in positions],
                    broker_position_ids=intent.get('evidence',{}).get('position_ids',[]))

    def sync(self,*,force_close=False):
        result=self.gateway.reconcile(force_close=force_close)
        now=datetime.now(timezone.utc).isoformat();day=utc(now).date().isoformat()
        self.data.update(balance=result['balance'],broker_equity=result['equity'],
                         trading_enabled=result.get('trading_enabled',False))
        self.data['peak']=max(self.data.get('peak') or result['equity'],result['equity'])
        if self.data['day']!=day:
            self.data.update(day=day,day_start=result['equity'],daily_entries=0,realized_today=0)
        self.data.update(position=None,pending_execution=False)
        for intent in result['intents']:
            if intent['owner']['session_id']!=self.data['session_id']:
                # Never silently attribute another session's exposure/reward.
                if intent['status']!='CLOSED':self.data['pending_execution']=True
                continue
            status=intent['status'];positions=intent.get('observed_positions',[])
            if status not in ('CLOSED','CONFIRMED'):
                self.data['pending_execution']=True
            if positions:
                self.data['position']=self.position_view(intent,positions)
            if positions or status=='CLOSED':
                key=intent['client_id']+':opened'
                if not self.applied_before(key):
                    self.data['daily_entries']+=int(utc(intent['created_at']).date().isoformat()==day)
                    self.event('opened',now,position=self.position_view(intent,positions),native=True)
                    self.seen.add(key);self.applied.append(key)
            if status=='CLOSED':
                key=intent['client_id']+':closed'
                if self.applied_before(key):continue
                pnl=intent['evidence']['net_pnl'];position=self.position_view(intent)
                risk=position['initial_risk'];reward=pnl/risk
                learn(self.data['lab_state'],position,pnl,reward)
                self.data['closed_trades']+=1;self.data['wins']+=int(pnl>0);self.data['losses']+=int(pnl<0)
                self.data['realized_pnl']+=pnl
                # Close observed today; raw broker timestamps retained in deal evidence.
                self.data['realized_today']+=pnl
                self.event('closed',now,position=position,net_pnl=pnl,result_in_r=reward,
                           learning_eligible=False,research_reward_eligible=True,
                           reward_scope='mt5_demo_broker_deals',deal_tickets=intent['evidence']['deal_tickets'])
                self.seen.add(key);self.applied.append(key)
        # Unknown/foreign exposure blocks entry, without closing foreign positions.
        own={t for p in [self.data['position']] if p for t in p['broker_tickets']}
        if result['orders'] or any(p.ticket not in own for p in result['positions']):
            self.data['pending_execution']=True
        return result

    def mark(self,quote,*,force_close=None):
        self.sync(force_close=bool(force_close))
        self.data['last_quote']=quote

    def open(self,setup,features,probability,quote,*,active_sessions,hypothesis):
        from .entry_trend import entry_blocker
        blocker=entry_blocker(setup.get('snapshot'),setup['candidate'].side)
        if blocker:return dict(approved=False,reasons=[blocker])
        if self.data['position'] or self.data['pending_execution']:
            return dict(approved=False,reasons=['DEMO_RECONCILIATION_REQUIRED'])
        if not hypothesis or hypothesis['protocol_id']!=self.data['model_id']:
            raise ValueError('Hipótese demo incompatível com o protocolo ativo.')
        state=self.gateway.control.status()
        intent=self.gateway.enter(setup,hypothesis,features,self.data['lot'],self.data,state['generation'])
        self.sync()
        return dict(approved=bool(self.data['position']),reasons=[] if self.data['position'] else
                    ['DEMO_BROKER_REJECTED' if intent['status']=='REJECTED' else 'DEMO_AWAITING_BROKER_CONFIRMATION'])

    def summary(self):
        result=super().summary()
        result.update(mode='demo',equity=self.data['broker_equity'],
                      realized_pnl=self.data['realized_pnl'],
                      unrealized_pnl=(self.data['broker_equity'] or self.data['balance'])-self.data['balance'],
                      pending_execution=self.data['pending_execution'])
        return result

    def equity(self,quote):
        return self.data['broker_equity'] if self.data['broker_equity'] is not None else self.data['balance']
