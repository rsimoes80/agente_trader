"""Read-only diagnostics from the actual autonomous worker journal."""
import json


def decisions(memory,session_id,*,limit=50,offset=0):
    limit=max(1,min(100,int(limit)));offset=max(0,min(100000,int(offset)))
    if not session_id:return []
    with memory.pool.connection() as c:
        rows=c.execute("""SELECT payload_json,payload_sha256 FROM project_records
            WHERE record_type IN ('agent_demo_event','agent_paper_event')
            AND payload_json::jsonb->>'session_id'=%s
            AND payload_json::jsonb->>'status'='decision'
            ORDER BY recorded_at DESC LIMIT %s OFFSET %s""",(session_id,limit,offset)).fetchall()
    result=[]
    for row in rows:
        data=json.loads(row['payload_json'])
        if memory._encode(data)[1]!=row['payload_sha256']:
            raise ValueError('Registro de decisão inconsistente.')
        result.append(data)
    return result
