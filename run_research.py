"""Explicit historical research command. Never authorizes or sends broker orders."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))


def main():
    from aurelia_fx.storage import open_memory
    from aurelia_fx.operation_control import validate_lot
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.agent_history import collect_training_history
    from aurelia_fx.agent_research import build_samples
    from aurelia_fx.agent_validation import validate
    from aurelia_fx.forecasting.config import load_config
    from aurelia_fx.forecasting.adapter import TimestralAdapter
    from mt5_provider import fetch_history
    parser=argparse.ArgumentParser(description='Pesquisa histórica separada da operação demo; sem envio de ordens.')
    parser.add_argument('--days',type=int,default=60,help='60 a 365 dias, incluindo 30 dias de aquecimento')
    parser.add_argument('--lot',default='0.01')
    args=parser.parse_args()
    if not 60<=args.days<=365:parser.error('--days deve estar entre 60 e 365')
    config=load_config();memory=open_memory();adapter=TimestralAdapter(config)
    def progress(**data):print(json.dumps(data,ensure_ascii=True),flush=True)
    try:
        with memory.pool.connection() as lease:
            if not lease.execute('SELECT pg_try_advisory_lock(70616070) AS acquired').fetchone()['acquired']:
                raise RuntimeError('Pesquisa histórica já em execução.')
            try:
                repo=HistoricalRepository(memory)
                source=fetch_history('EURUSD','M5',100,include_current=False)
                contract=source['symbol_contract'];lot=validate_lot(args.lot,contract)
                baseline=collect_training_history(repo,fetch_history,days=args.days,expected_clock_id=source['source_clock']['clock_id'])
                if baseline['status']!='ready':raise RuntimeError('Arquivo histórico ainda sem cobertura suficiente.')
                frozen,rows=repo.frozen_candles(baseline,record_type='agent_training_history')
                dataset,partitions,candles=build_samples(memory,rows,baseline=frozen,lot=lot,contract=contract,
                    forecast_config=config,adapter=adapter,progress=progress,check=lambda:None)
                report=validate(memory,dataset,partitions,candles,lot=lot,contract=contract,progress=progress,check=lambda:None)
                print(json.dumps(report,ensure_ascii=True))
            finally:lease.execute('SELECT pg_advisory_unlock(70616070)')
    finally:adapter.close();memory.close()


if __name__=='__main__':main()
