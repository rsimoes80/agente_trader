"""Install the project's latest-record index without blocking journal writes.

Run before deploying to an existing large database. Fresh databases also get
this index through the normal schema initializer. No records are removed.
"""
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    import psycopg
    from psycopg.rows import dict_row
    from aurelia_fx.storage import database_url
    from aurelia_fx.agent_model import fingerprint
    index='ix_project_records_type_recorded'
    query="SELECT payload_json FROM public.project_records WHERE record_type='agent_operation_state' ORDER BY recorded_at DESC LIMIT 1"
    with psycopg.connect(database_url(),autocommit=True,row_factory=dict_row) as c:
        identity=c.execute("SELECT current_database() db,current_user role,pg_get_userbyid(relowner) owner FROM pg_class WHERE oid='public.project_records'::regclass").fetchone()
        if identity['db']!='agente_trader' or identity['role']!=identity['owner']:
            raise ValueError('Index migration requires ownership of the isolated project database table')
        def plan():
            d=c.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query).fetchone()['QUERY PLAN'][0]
            return dict(execution_ms=d['Execution Time'],plan=d['Plan'])
        before=plan()
        c.execute("SET statement_timeout='300s'")
        c.execute("SET lock_timeout='5s'")
        started=time.perf_counter()
        # Autocommit is required: PostgreSQL forbids concurrent index builds in a transaction.
        c.execute('CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_project_records_type_recorded ON public.project_records(record_type,recorded_at DESC)')
        installed=c.execute("SELECT indisvalid,indisready,indrelid='public.project_records'::regclass AS correct_table,pg_relation_size(indexrelid) bytes,pg_get_indexdef(indexrelid) definition FROM pg_index WHERE indexrelid='public.ix_project_records_type_recorded'::regclass").fetchone()
        if not installed['indisvalid'] or not installed['indisready']:
            raise ValueError('Index is incomplete; inspect the interrupted build before retrying')
        if not installed['correct_table'] or not installed['definition'].endswith('(record_type, recorded_at DESC)'):
            raise ValueError('Existing index has another definition; no automatic replacement allowed')
        after=plan()
        result=dict(index=index,creation_seconds=time.perf_counter()-started,installed=dict(installed),
                    before=before,after=after,records_deleted=0,writes_allowed_during_build=True)
        result['id']=fingerprint(result)
        text=json.dumps(result,sort_keys=True,allow_nan=False)
        import hashlib
        c.execute("INSERT INTO public.project_records(record_type,record_key,payload_json,payload_sha256,recorded_at) VALUES('agent_runtime_index_verification',%s,%s,%s,clock_timestamp()) ON CONFLICT DO NOTHING",
                  (result['id'],text,hashlib.sha256(text.encode()).hexdigest()))
        (ROOT/'data/reports'/('runtime-index-'+result['id'][:12]+'.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(dict(id=result['id'],index=index,bytes=installed['bytes'],before_ms=before['execution_ms'],after_ms=after['execution_ms'])))


if __name__=='__main__':main()
