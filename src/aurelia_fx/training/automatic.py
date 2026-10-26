"""Daily autonomous model research, driven by new data and the existing queue."""
from datetime import datetime,timedelta,timezone
import json
from uuid import uuid4
from .repository import ACTIVE,LOCK
from aurelia_fx.historical.core import utc

def status(memory):
    with memory.pool.connection() as c:
        row=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_automatic_training' ORDER BY recorded_at DESC LIMIT 1").fetchone()
    if not row:return dict(enabled=True,status='WAITING_AGENT',message='Treino automatico aguarda o agente iniciado.')
    result=json.loads(row['payload_json'])
    if memory._encode(result)[1]!=row['payload_sha256']:raise ValueError('Automatic training state changed')
    if result.get('run_id'):
        with memory.pool.connection() as c:
            latest=c.execute("SELECT payload_json,payload_sha256 FROM project_records WHERE record_type='agent_training_lab_state' ORDER BY recorded_at DESC LIMIT 1").fetchone()
        run=json.loads(latest['payload_json']) if latest else {}
        if latest and memory._encode(run)[1]!=latest['payload_sha256']:raise ValueError('Automatic training result integrity failure')
        if run.get('run_id')==result['run_id'] and run['status'] in ACTIVE:
            result={**result,'status':run['status'],'message':'Pesquisa automática: '+run.get('message',run['status'])}
        if run.get('run_id')==result['run_id'] and run['status'] not in ACTIVE:
            result={**result,'last_result_status':run['status'],'status':'WAITING_NEW_DATA',
                'message':('Último treino interrompido. Não há treino em execução nessa tentativa. ' if run['status']=='FAILED' else 'Último ciclo encerrado. ')+
                    'Próxima pesquisa automática exige 288 candles novos e intervalo de 24 horas. O botão Antecipar treino solicita uma nova tentativa.'}
    return result

def schedule(repo,agent,fetch,now=None):
    now=utc(now or datetime.now(timezone.utc));old=status(repo.memory)
    if agent.get('desired')!='running' or agent.get('mode') not in {'demo','paper'}:return repo.latest()
    if repo.latest()['status'] in ACTIVE|{'AWAITING_PROSPECTIVE'}:return repo.latest()
    if old.get('last_attempt') and now-utc(old['last_attempt'])<timedelta(hours=24):return repo.latest()
    from aurelia_fx.historical.repository import HistoricalRepository
    from aurelia_fx.historical.collector import collect
    outcome={**old,'enabled':True,'last_attempt':now.isoformat()}
    try:
        archive=HistoricalRepository(repo.memory)
        baseline=collect(archive,fetch,days=30,full=False)
        if baseline['clock_id']!=(agent.get('history') or {}).get('clock_id'):raise ValueError('SOURCE_MISMATCH')
        previous=old.get('last_dataset_last_candle') or (repo.latest().get('dataset') or {}).get('source_as_of')
        added=archive.candles(clock_id=baseline['clock_id'],timeframe='M5',start=utc(previous)+timedelta(minutes=5) if previous else utc(baseline['start']),as_of=utc(baseline['as_of']))
        outcome['new_candles']=len(added)
        if len(added)<288:
            outcome.update(status='WAITING_NEW_DATA',message='Aguardando 288 candles M5 novos; passagem do tempo sem mercado nao conta.')
        else:
            # A serial queue prevents duplicate training. This identifies autonomous data policy.
            from .protocol import RECIPES
            trial=old.get('trial_number',0);recipe=list(RECIPES)[trial%len(RECIPES)]
            state=repo.command('START',str(uuid4()))
            state=repo.publish(state['run_id'],automatic=True,dataset_policy='rolling',training_recipe=recipe,message='Novo ciclo automatico com historico atualizado.')
            outcome.update(status='QUEUED',run_id=state['run_id'],trial_number=trial+1,recipe=recipe,last_dataset_as_of=baseline['as_of'],last_dataset_last_candle=baseline['timeframes']['M5']['last'],message='Retreino automatico solicitado com dados novos.')
    except (ValueError,RuntimeError,OSError) as exc:
        outcome.update(status='WAITING_SOURCE',message=str(exc)[:160])
        # Transient source failures retry after 15 minutes, not a whole day.
        outcome['last_attempt']=(now-timedelta(hours=23,minutes=45)).isoformat()
    repo.memory.record_project_data('agent_automatic_training',str(uuid4()),outcome)
    return repo.latest()
