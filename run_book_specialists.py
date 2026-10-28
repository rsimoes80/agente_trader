"""Build book skills and run source-grounded research specialists, without orders."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import signal
import sys
import threading
import time

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def latest_cards(memory):
    with memory.pool.connection() as connection:
        rows=connection.execute("""SELECT DISTINCT ON (record_key) payload_json FROM project_records
            WHERE record_type='literature_technique_card' ORDER BY record_key,recorded_at DESC""").fetchall()
    return [json.loads(row['payload_json']) for row in rows]


def main():
    from aurelia_fx.book_profiles import BY_ID
    from aurelia_fx.book_skills import build_skills, load_skill, private_write, digest
    from aurelia_fx.book_specialists import analyze, coordinate, validate_case, VERSION, MODEL_SPEC
    from aurelia_fx.storage import open_memory
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-only',action='store_true')
    parser.add_argument('--case',type=Path,help='Frozen historical/research case JSON')
    parser.add_argument('--specialists',nargs='+',choices=tuple(BY_ID),default=['pullback','pring'])
    parser.add_argument('--watch',action='store_true')
    parser.add_argument('--interval',type=int,default=900)
    args=parser.parse_args()
    if args.interval<300:parser.error('Research interval must be at least 300 seconds')
    if len(set(args.specialists))!=len(args.specialists):parser.error('Repeated specialist')
    if args.watch and args.case:parser.error('Use --case for a single replay, not --watch')
    memory=open_memory();stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    try:
        while not stop.is_set():
            manifests=build_skills(latest_cards(memory))
            if args.build_only:
                print(json.dumps([dict(specialist_id=m['specialist_id'],status=m['status'],source_cards=m['source_cards'],skill_version=m['skill_version']) for m in manifests]));return
            if args.case:case=json.loads(args.case.read_text())
            else:
                with memory.pool.connection() as connection:
                    row=connection.execute("""SELECT payload_json FROM project_records WHERE record_type='book_market_case'
                        ORDER BY recorded_at DESC LIMIT 1""").fetchone()
                case=json.loads(row['payload_json']) if row else None
            if case is None:
                print(json.dumps(dict(status='AWAITING_MARKET_CASE',orders_enabled=False)),flush=True)
                if not args.watch:return
                stop.wait(args.interval);continue
            validate_case(case)
            skills=[load_skill(BY_ID[key],max_cards=MODEL_SPEC['max_cards']) for key in args.specialists]
            identity=VERSION+':'+digest(MODEL_SPEC)+':'+case['case_id']+':'+':'.join(s['manifest']['skill_version'] for s in skills)
            with memory.pool.connection() as connection:
                exists=connection.execute("SELECT 1 FROM project_records WHERE record_type='book_council_analysis' AND record_key=%s LIMIT 1",(identity,)).fetchone()
            if not exists:
                started_at=datetime.now(timezone.utc);started=time.monotonic()
                reports=[]
                for skill in skills:
                    if stop.is_set():return
                    specialist_started=time.monotonic()
                    try:
                        report=analyze(skill,case)
                    except Exception as exc:
                        # Never log source content or model output on schema failures.
                        code=str(exc) if isinstance(exc,ValueError) and str(exc).replace('_','').isupper() else type(exc).__name__
                        report=dict(specialist_id=skill['profile'].id,case_id=case['case_id'],skill_version=skill['manifest']['skill_version'],
                                    status='analysis_failed',error_code=code,findings=[],trading_authority=False)
                    report['processing_seconds']=round(time.monotonic()-specialist_started,3)
                    memory.record_project_data('book_specialist_analysis',identity+':'+skill['profile'].id,report)
                    reports.append(report)
                    print(json.dumps(dict(specialist_id=report['specialist_id'],status=report['status'],findings=len(report['findings']))),flush=True)
                result=coordinate(case,reports)
                result['completed_at']=datetime.now(timezone.utc).isoformat()
                result['started_at']=started_at.isoformat()
                result['processing_seconds']=round(time.monotonic()-started,3)
                result['data_age_at_completion_seconds']=(datetime.now(timezone.utc)-datetime.fromisoformat(case['as_of'])).total_seconds()
                result['purpose']='historical_replay' if args.case else 'asynchronous_live_research'
                memory.record_project_data('book_council_analysis',identity,result)
                private_write(ROOT/'data/reports/book-specialists/latest.json',json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps(dict(status=result['status'],analysis_id=result['analysis_id'],missing_stages=result['missing_stages'],orders_enabled=False)),flush=True)
            if not args.watch:return
            stop.wait(args.interval)
    finally:
        memory.close()


if __name__=='__main__':main()
