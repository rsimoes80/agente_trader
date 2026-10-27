"""Single-job training queue and immutable progress in the project PostgreSQL."""
from datetime import datetime,timezone
import json
from uuid import uuid4

LOCK=70616081
RUN_LOCK=70616080
ACTIVE={'QUEUED','DATASET','WAITING_RESOURCES','TRAINING','VALIDATING','SIMULATING','SHADOW','AWAITING_PROSPECTIVE'}


class Cancelled(RuntimeError):pass


class TrainingRepository:
    def __init__(self,memory,symbol='EURUSD'):
        from aurelia_fx.instruments import symbol_name
        self.memory=memory;self.symbol=symbol_name(symbol)

    def record_type(self,kind):
        return kind if self.symbol=='EURUSD' else kind+':'+self.symbol

    def latest(self,c=None):
        if c is None:
            with self.memory.pool.connection() as connection:return self.latest(connection)
        row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type=%s ORDER BY recorded_at DESC LIMIT 1",(self.record_type('agent_training_lab_state'),)).fetchone()
        if not row:return dict(symbol=self.symbol,status='NOT_STARTED',stage='environment',message='Laboratorio pronto para treino com '+self.symbol+'.')
        d=json.loads(row['payload_json'])
        if self.memory._encode(d)[1]!=row['payload_sha256']:raise ValueError('Training state integrity failure')
        if d.get('symbol','EURUSD')!=self.symbol:raise ValueError('Training state instrument mismatch')
        return d

    def append(self,c,state):
        if state.get('symbol',self.symbol)!=self.symbol:raise ValueError('Training instrument mismatch')
        state={**state,'symbol':self.symbol,'updated_at':datetime.now(timezone.utc).isoformat(),'sequence':state.get('sequence',0)+1}
        text,digest=self.memory._encode(state)
        c.execute("INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at) VALUES(%s,%s,%s,%s,clock_timestamp())",(self.record_type('agent_training_lab_state'),str(uuid4()),text,digest))
        return state

    def summary(self):
        from .runtime import learning_summary
        with self.memory.pool.connection() as c:
            state=self.latest(c)
            row=c.execute("SELECT EXTRACT(EPOCH FROM(clock_timestamp()-recorded_at)) AS age FROM project_records WHERE record_type=%s ORDER BY recorded_at DESC LIMIT 1",(self.record_type('agent_training_lab_state'),)).fetchone()
            runtime=c.execute("SELECT payload_json,payload_sha256,EXTRACT(EPOCH FROM(clock_timestamp()-recorded_at)) AS age FROM project_records WHERE record_type=%s ORDER BY recorded_at DESC LIMIT 1",(self.record_type('agent_training_runtime'),)).fetchone()
            history=c.execute("""SELECT * FROM (
                SELECT DISTINCT ON(payload_json::jsonb->>'run_id')
                    payload_json::jsonb->>'run_id' AS run_id,payload_json::jsonb->>'status' AS status,
                    payload_json::jsonb->>'updated_at' AS updated_at,
                    payload_json::jsonb->'weight_update' AS weight_update,
                    payload_json::jsonb#>'{forecast_report,selection}' AS selection,
                    payload_json::jsonb#>>'{dataset,dataset_id}' AS dataset_id,
                    payload_json::jsonb#>>'{forecast_report,partitions,test,gate,pinball_improvement_pct}' AS improvement,
                    recorded_at FROM project_records
                WHERE record_type=%s AND COALESCE(payload_json::jsonb->>'profile_id','')=COALESCE(%s,'')
                AND payload_json::jsonb->>'run_id' IS NOT NULL
                ORDER BY payload_json::jsonb->>'run_id',recorded_at DESC
                ) runs ORDER BY recorded_at DESC LIMIT 5""",(self.record_type('agent_training_lab_state'),state.get('profile_id'))).fetchall()
        resources=json.loads(runtime['payload_json']) if runtime else None
        if runtime and self.memory._encode(resources)[1]!=runtime['payload_sha256']:raise ValueError('Training runtime integrity failure')
        if resources:resources={**resources,'received_age_seconds':float(runtime['age']),
            'matches_run':resources.get('run_id')==state.get('run_id')}
        from aurelia_fx.operation_control import OperationControl
        from .visibility import evolution
        control=OperationControl(self.memory,self.symbol)
        history=[{k:v for k,v in dict(r).items() if k!='recorded_at'} for r in history]
        return {**state,'received_age_seconds':float(row['age']) if row else None,
            'runtime':resources,'learning_summary':learning_summary(state),
            'evolution':evolution({**state,'symbol':self.symbol},control.status(),control.worker_status(),history)}

    def command(self,action,key):
        if action not in {'START','CANCEL'} or not isinstance(key,str) or not 16<=len(key)<=128:raise ValueError('Invalid training command')
        with self.memory.pool.connection() as c,c.transaction():
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            old=c.execute("SELECT payload_json FROM project_records WHERE record_type=%s AND record_key=%s LIMIT 1",(self.record_type('agent_training_lab_command'),key)).fetchone()
            if old:
                old=json.loads(old['payload_json'])
                if old['action']!=action:raise ValueError('Command key already used')
                return old['state']
            state=self.latest(c)
            if action=='START':
                if state['status'] not in ACTIVE:
                    scope={}
                    if self.symbol!='EURUSD':
                        from .scope import agent_profile
                        from aurelia_fx.operation_control import OperationControl
                        profile=agent_profile(self.memory,self.symbol)
                        agent=OperationControl(self.memory,self.symbol).status()
                        scope=dict(profile_id=profile.fingerprint,research_profile=profile.as_dict(),source_clock_id=agent['history']['clock_id'])
                    state=self.append(c,dict(run_id=str(uuid4()),status='QUEUED',stage='dataset',cancel_requested=False,
                        created_at=datetime.now(timezone.utc).isoformat(),dataset_policy='rolling',**scope,message='Treino de '+self.symbol+' solicitado. Aguardando o servico Windows.',live_model_changed=False))
            elif state['status'] in ACTIVE:
                state=self.append(c,{**state,'cancel_requested':True,'message':'Cancelamento solicitado somente para o laboratorio.'})
            payload={'action':action,'state':state};text,digest=self.memory._encode(payload)
            c.execute("INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256) VALUES(%s,%s,%s,%s)",(self.record_type('agent_training_lab_command'),key,text,digest))
            return state

    def publish(self,run_id,**changes):
        with self.memory.pool.connection() as c,c.transaction():
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            state=self.latest(c)
            if state.get('run_id')!=run_id or state.get('cancel_requested'):raise Cancelled('Training cancelled')
            if any(k in changes for k in ('completed','partition','epoch','selection','forecast_report','financial_report','weight_update')):
                changes['last_progress_at']=datetime.now(timezone.utc).isoformat()
            return self.append(c,{**state,**changes})

    def check(self,run_id):
        state=self.latest()
        if state.get('run_id')!=run_id or state.get('cancel_requested'):raise Cancelled('Training cancelled')

    def finish_cancel(self,run_id):
        with self.memory.pool.connection() as c,c.transaction():
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,));state=self.latest(c)
            if state.get('run_id')==run_id:self.append(c,{**state,'status':'CANCELLED','message':'Treino cancelado; agente demo preservado.'})
