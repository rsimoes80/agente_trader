"""Bounded CPU training worker; reads a PostgreSQL queue without sending orders."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))

def worker(repo,state):
    import psutil
    psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS if os.name=='nt' else 10)
    from aurelia_fx.training.trainer import train
    run_id=state['run_id'];output=ROOT/'data/training/runs'/run_id
    progress=lambda **kw:repo.publish(run_id,**kw)
    report_path=output/'forecast-report.json'
    if not report_path.exists() and (output/'selection.json').exists():
        raise RuntimeError('Sealed candidate without complete report: review artifacts before resuming; never retrain after test access')
    report=json.loads(report_path.read_text()) if report_path.exists() else train(ROOT,ROOT/state['dataset_directory'],output,progress,lambda:repo.check(run_id))
    if not report.get('evaluation_path'):
        from aurelia_fx.training.evaluation import evaluate
        report=evaluate(ROOT,ROOT/state['dataset_directory'],output,progress,lambda:repo.check(run_id))
    repo.publish(run_id,status='SIMULATING',stage='simulation',forecast_report=report,
        artifact_directory=str(output.relative_to(ROOT)),message='Previsoes avaliadas. Preparando simulacao com custos.')
    from aurelia_fx.training.simulation import simulate
    financial_path=output/'simulation-report.json'
    financial=json.loads(financial_path.read_text()) if financial_path.exists() else simulate(ROOT,ROOT/state['dataset_directory'],output,progress,lambda:repo.check(run_id))
    from aurelia_fx.training.archive_control import compare
    control=compare(repo.memory,ROOT,ROOT/state['dataset_directory'],output,lambda:repo.check(run_id))
    forecast_pass=all(p['gate']['passed'] for p in report['partitions'].values())
    reasons=[*report['partitions']['validation']['gate']['reasons'],*report['partitions']['test']['gate']['reasons'],*financial['gate']['reasons']]
    status='AWAITING_PROSPECTIVE' if forecast_pass and financial['gate']['passed'] else 'NOT_APPROVED'
    decision=dict(status=status,reasons=sorted(set(reasons)),approved=False,live_model_changed=False,
        prospective=dict(status='NOT_STARTED',min_days=7,min_closed_trades_per_arm=20))
    (output/'decision.json').write_text(json.dumps(decision,indent=2))
    repo.publish(run_id,status=status,stage='decision',financial_report=financial,archive_control=control,decision=decision,
        message='Avaliacao concluida. Candidato nao promovido; consulte os criterios.' if reasons else 'Criterios retrospectivos atendidos. Falta validacao prospectiva independente.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--once',action='store_true')
    parser.add_argument('--run-id',help=argparse.SUPPRESS)
    parser.add_argument('--retry',action='store_true',help='Explicitly resume a failed run, without changing its protocol')
    parser.add_argument('--verify',action='store_true',help='Recheck sealed reports and secondary control; never retrain a completed run')
    args=parser.parse_args()
    from aurelia_fx.storage import open_memory
    from aurelia_fx.training.repository import TrainingRepository,ACTIVE,RUN_LOCK,Cancelled
    memory=open_memory();repo=TrainingRepository(memory)
    try:
        state=repo.latest()
        if args.worker:
            if state.get('run_id')!=args.run_id:raise RuntimeError('Training worker fenced by a newer run')
            repo.check(args.run_id);worker(repo,state);return
        import psutil
        from run_training_proof import stop_owned
        with memory.pool.connection() as lease:
            if not lease.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(RUN_LOCK,)).fetchone()['acquired']:return
            state=repo.latest()
            if args.verify and state['status'] in {'NOT_APPROVED','AWAITING_PROSPECTIVE'}:
                run_folder=ROOT/'data/training/runs'/state['run_id']
                if not all((run_folder/name).exists() for name in ('forecast-report.json','simulation-report.json','selection.json')):
                    raise RuntimeError('Completed artifacts missing; verification cannot retrain')
                state=repo.publish(state['run_id'],status='VALIDATING',stage='validation',message='Verificando artefatos congelados e controle secundario.')
            if args.retry and state['status'] in {'FAILED','CANCELLED'}:
                from aurelia_fx.training.repository import LOCK
                with memory.pool.connection() as c,c.transaction():
                    c.execute('SELECT pg_advisory_xact_lock(%s)',(LOCK,))
                    state=repo.append(c,{**state,'status':'WAITING_RESOURCES','cancel_requested':False,
                        'stage':'training','message':'Retomando o mesmo protocolo apos correcao tecnica.'})
            if state['status'] not in ACTIVE:return
            run_id=state['run_id']
            if state.get('cancel_requested'):repo.finish_cancel(run_id);return
            if not state.get('dataset_directory'):
                from aurelia_fx.training.dataset import export
                repo.publish(run_id,status='DATASET',stage='dataset',message='Exportando historico congelado.')
                folder,manifest=export(memory,ROOT,progress=lambda **kw:repo.publish(run_id,**kw))
                state=repo.publish(run_id,dataset_directory=str(folder.relative_to(ROOT)),dataset=manifest)
            from aurelia_fx.training.protocol import register
            protocol_id=register(memory,run_id,state['dataset']['dataset_id'])
            if psutil.virtual_memory().available<384*1024**2:
                repo.publish(run_id,status='WAITING_RESOURCES',stage='training',protocol_id=protocol_id,
                    message='Aguardando pelo menos 384 MB de RAM livre. O agente continua independente.')
                return
            output=ROOT/'data/training/runs'/run_id;output.mkdir(parents=True,exist_ok=True)
            repo.publish(run_id,status='TRAINING',stage='features',protocol_id=protocol_id,message='Iniciando prova CPU com dados reais.')
            env={**os.environ,'HF_HOME':str(ROOT/'data/training/hf-home'),'HF_XET_CACHE':str(ROOT/'data/training/cache/xet')}
            with (output/'worker.log').open('w',encoding='utf-8') as log:
                child=subprocess.Popen([str(ROOT/'.venv-training/Scripts/python.exe'),'-u',str(Path(__file__).resolve()),'--worker','--run-id',run_id],
                    cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            birth=psutil.Process(child.pid).create_time();started=time.monotonic();peak=0
            try:
                while child.poll() is None:
                    repo.check(run_id)
                    try:
                        process=psutil.Process(child.pid)
                        rss=sum(p.memory_info().rss for p in [process,*process.children(recursive=True)] if p.is_running())
                    except psutil.NoSuchProcess:rss=0
                    peak=max(peak,rss)
                    if rss>768*1024**2 or psutil.virtual_memory().available<128*1024**2 or time.monotonic()-started>7200:
                        stop_owned(child,birth);raise RuntimeError('RESOURCE_LIMIT: isolated worker stopped; trading unchanged')
                    time.sleep(1)
                if child.wait(timeout=15)!=0:raise RuntimeError('WORKER_FAILED: inspect the run worker.log')
                with memory.pool.connection() as c:
                    previous=c.execute("SELECT MAX((payload_json::jsonb->'resources'->>'peak_process_tree_rss_mb')::float8) AS peak FROM project_records WHERE record_type='agent_training_lab_state' AND payload_json::jsonb->>'run_id'=%s",(run_id,)).fetchone()['peak'] or 0
                repo.publish(run_id,resources=dict(peak_process_tree_rss_mb=max(previous,round(peak/1024**2,1)),
                    last_attempt_peak_mb=round(peak/1024**2,1),wall_seconds=round(time.monotonic()-started,2)))
            except Cancelled:
                if child.poll() is None:stop_owned(child,birth)
                repo.finish_cancel(run_id)
            except Exception as exc:repo.publish(run_id,status='FAILED',message=str(exc)[:200],stage='error')
            finally:
                if child.poll() is None:stop_owned(child,birth)
    finally:memory.close()

if __name__=='__main__':main()
