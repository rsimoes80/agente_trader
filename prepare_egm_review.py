"""Freeze one existing market case and sources for a read-only EGM pilot."""
import argparse,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.egm_review import prepare,verify
    from aurelia_fx.storage import database_url
    import psycopg
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-id')
    parser.add_argument('--verify',type=Path)
    args=parser.parse_args()
    if args.verify:
        manifest=verify(args.verify);print(json.dumps(dict(status='INPUTS_VERIFIED',case_id=manifest['case_id'])));return
    with psycopg.connect(database_url()) as connection:
        with connection.transaction():
            connection.execute('SET TRANSACTION READ ONLY')
            row=connection.execute("""SELECT payload_json FROM project_records
                WHERE record_type='book_market_case' AND (%s::text IS NULL OR record_key=%s)
                ORDER BY recorded_at DESC LIMIT 1""",(args.case_id,args.case_id)).fetchone()
    if row is None:raise SystemExit('NO_EXISTING_MARKET_CASE')
    folder=prepare(ROOT,json.loads(row[0]));verify(folder)
    print(json.dumps(dict(status='PREPARED_NOT_REVIEWED',folder=str(folder),trading_authority=False)))


if __name__=='__main__':main()
