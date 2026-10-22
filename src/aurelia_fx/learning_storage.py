"""Content-addressed learning snapshots: avoid copying research history every quote."""
import copy,json

def pack(memory,c,data):
    lab=data.get('lab_state',{})
    for name in ('continual','model_study'):
        if name not in lab:continue
        payload=dict(kind=name,state=lab.pop(name));text,digest=memory._encode(payload)
        c.execute("INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256) VALUES('agent_learning_checkpoint',%s,%s,%s) ON CONFLICT DO NOTHING",(digest,text,digest))
        lab[name+'_ref']=digest
    return data

def hydrate(memory,data):
    if not data:return data
    lab=data.get('lab_state',{})
    for name in ('continual','model_study'):
        key=lab.get(name+'_ref')
        if not key:continue
        with memory.pool.connection() as c:
            row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_learning_checkpoint' AND record_key=%s LIMIT 1",(key,)).fetchone()
        if not row:raise ValueError('Persistent learning snapshot missing')
        payload=json.loads(row['payload_json'])
        if memory._encode(payload)[1]!=key or row['payload_sha256']!=key or payload['kind']!=name:raise ValueError('Persistent learning integrity failure')
        lab[name]=payload['state'];lab.pop(name+'_ref')
    return data
