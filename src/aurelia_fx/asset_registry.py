"""Durable user instrument selection. Contract snapshots come from the bridge."""
from datetime import datetime,timezone
import json
import re

from .agent_model import fingerprint
from .instruments import symbol_name,InstrumentContract
from .operation_control import OperationControl,LOCK,validate_lot


class AssetRegistry:
    def __init__(self,memory):self.memory=memory

    def list(self,connection=None):
        if connection is None:
            with self.memory.pool.connection() as c:return self.list(c)
        rows=connection.execute("""SELECT DISTINCT ON(record_key) payload_json,payload_sha256
            FROM project_records WHERE record_type='asset_configuration'
            ORDER BY record_key,recorded_at DESC,payload_sha256 DESC""").fetchall()
        result=[]
        for row in rows:
            data=json.loads(row['payload_json'])
            if self.memory._encode(data)[1]!=row['payload_sha256']:raise ValueError('Configuração de ativo corrompida.')
            result.append(data)
        if not any(r['symbol']=='EURUSD' for r in result):
            legacy=OperationControl(self.memory).latest(connection)
            result.append(dict(symbol='EURUSD',lot=legacy.get('lot') or '0.01',selected=True,
                               instrument_id=None,contract=None,legacy=True))
        return sorted(result,key=lambda r:r['symbol'])

    def get(self,symbol,connection=None):
        return next((r for r in self.list(connection) if r['symbol']==symbol),None)

    def remember_session_lot(self,state):
        symbol=state.get('symbol','EURUSD');lot=validate_lot(state['lot'])
        with self.memory.pool.connection() as c,c.transaction():
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            current=OperationControl(self.memory,symbol).latest(c);old=self.get(symbol,c)
            if current.get('session_id')!=state.get('session_id') or current.get('desired')!='running' or current.get('lot')!=lot or not old or not old.get('selected'):return
            validate_lot(lot,old.get('contract'))
            if old.get('lot')==lot:return
            data={**old,'lot':lot,'updated_at':datetime.now(timezone.utc).isoformat()}
            text,sha=self.memory._encode(data)
            c.execute("INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at) VALUES('asset_configuration',%s,%s,%s,clock_timestamp())",(symbol,text,sha))

    def command(self,payload,key,inspect):
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{16,128}',key):raise ValueError('Comando sem identificador válido.')
        symbol=symbol_name(payload.get('symbol'));action=payload.get('action')
        if action not in {'SELECT','REMOVE'}:raise ValueError('Ação de configuração inválida.')
        request=dict(action=action,symbol=symbol,lot=validate_lot(payload.get('lot')) if action=='SELECT' else None)
        digest=fingerprint(request)
        # Inspect outside the DB transaction: IPC must not hold the command lock.
        with self.memory.pool.connection() as c:
            cached=c.execute("SELECT payload_json FROM project_records WHERE record_type='asset_configuration_command' AND record_key=%s LIMIT 1",(key,)).fetchone()
        if cached:
            old=json.loads(cached['payload_json'])
            if old['fingerprint']!=digest:raise ValueError('Identificador já usado por outra configuração.')
            return old['result']
        snapshot=inspect(symbol) if action=='SELECT' else None
        if snapshot:
            data=snapshot['contract'];fields={k:v for k,v in data.items() if k!='instrument_id'}
            contract=InstrumentContract(**fields)
            if contract.symbol!=symbol:raise ValueError('A ponte retornou outro ativo.')
            if data.get('instrument_id')!=contract.key:raise ValueError('Identidade do contrato inválida.')
            validate_lot(request['lot'],data)
        with self.memory.pool.connection() as c,c.transaction():
            c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
            cached=c.execute("SELECT payload_json FROM project_records WHERE record_type='asset_configuration_command' AND record_key=%s LIMIT 1",(key,)).fetchone()
            if cached:
                old=json.loads(cached['payload_json'])
                if old['fingerprint']!=digest:raise ValueError('Identificador já utilizado.')
                return old['result']
            state=OperationControl(self.memory,symbol).latest(c)
            old=self.get(symbol,c)
            if state.get('position') or state.get('pending_execution') or state.get('desired') in {'running','paused'}:
                if action=='REMOVE' or request['lot']!=state.get('lot') or (old and old.get('instrument_id') and snapshot['contract']['instrument_id']!=old['instrument_id']):
                    raise ValueError('Pare este ativo e conclua a reconciliação antes de alterar sua configuração.')
            if action=='REMOVE':
                if old is None:raise ValueError('Ativo não configurado.')
                result={**old,'selected':False}
            else:
                result=dict(symbol=symbol,lot=request['lot'],selected=True,legacy=False,
                    instrument_id=snapshot['contract']['instrument_id'],contract=snapshot['contract'],
                    discovery_status=snapshot['status'],economics=snapshot.get('economics'),
                    account_currency=snapshot.get('account_currency'),commission=snapshot.get('commission'))
            result['updated_at']=datetime.now(timezone.utc).isoformat()
            text,sha=self.memory._encode(result)
            c.execute("INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256,recorded_at) VALUES('asset_configuration',%s,%s,%s,clock_timestamp())",(symbol,text,sha))
            encoded,sha=self.memory._encode(dict(fingerprint=digest,request=request,result=result))
            c.execute("INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256) VALUES('asset_configuration_command',%s,%s,%s)",(key,encoded,sha))
            return result
