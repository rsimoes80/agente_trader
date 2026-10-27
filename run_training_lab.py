"""Bounded CPU training worker; reads a PostgreSQL queue without sending orders."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))

def worker(repo,state):
    import psutil
    psutil.Process().nice(psutil.IDLE_PRIORITY_CLASS if os.name=='nt' else 10)
    from aurelia_fx.training.trainer import train
    from aurelia_fx.training.scope import assert_same,identity
    scope=identity(state)
    assert_same(state,state['dataset'])
    run_id=state['run_id'];output=ROOT/'data/training/runs'/run_id
    progress=lambda **kw:repo.publish(run_id,**kw)
    report_path=output/'forecast-report.json'
    sealed=(output/'selection.json').exists()
    if not report_path.exists() and sealed and not (output/'sealed-report-seed.json').exists():
        raise RuntimeError('Sealed candidate without complete report: review artifacts before resuming; never retrain after test access')
    if report_path.exists():report=json.loads(report_path.read_text())
    elif sealed:report={}
    else:report=train(ROOT,ROOT/state['dataset_directory'],output,progress,lambda:repo.check(run_id),recipe=state.get('training_recipe','conservative'))
    if not report.get('evaluation_path'):
        from aurelia_fx.training.evaluation import evaluate
        report=evaluate(ROOT,ROOT/state['dataset_directory'],output,progress,lambda:repo.check(run_id))
    if state.get('automatic') and not all(p['gate']['passed'] for p in report['partitions'].values()):
        reasons=sorted({r for p in report['partitions'].values() for r in p['gate']['reasons']})
        decision=dict(status='NOT_APPROVED',approved=False,reasons=reasons,live_model_changed=False)
        financial=dict(**scope,status='SKIPPED_FORECAST_PREFILTER',gate=dict(passed=False,reasons=['FORECAST_PREFILTER_FAILED']),orders_sent=0)
        (output/'simulation-report.json').write_text(json.dumps(financial,indent=2))
        (output/'decision.json').write_text(json.dumps(decision,indent=2))
        repo.publish(run_id,status='NOT_APPROVED',stage='decision',forecast_report=report,financial_report=financial,
            decision=decision,total=None,completed=None,artifact_directory=str(output.relative_to(ROOT)),
            message='Ciclo automatico concluido: previsao nao superou a triagem. Memoria preservada; proxima receita com dados novos.')
        return
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
    study_protocol=state.get('study_protocol')
    if status=='AWAITING_PROSPECTIVE' and not study_protocol:
        from datetime import datetime,timezone
        study_protocol=dict(**scope,registered_at=datetime.now(timezone.utc).isoformat(),candidate_sha256=report['selection']['candidate_sha256'],
            min_days=7,min_forecasts=200,min_closed_trades_per_arm=20,minimum_distinct_days=20,max_days=45,
            compare_active_model=True,orders_sent=0,auto_promote=True)
        repo.memory.record_project_data(repo.record_type('agent_model_study_protocol'),run_id,study_protocol)
    (output/'decision.json').write_text(json.dumps(decision,indent=2))
    repo.publish(run_id,status=status,stage='prospective' if status=='AWAITING_PROSPECTIVE' else 'decision',total=None,completed=None,financial_report=financial,archive_control=control,decision=decision,study_protocol=study_protocol,
        message='Avaliacao concluida. Candidato nao promovido; consulte os criterios.' if reasons else 'Criterios retrospectivos atendidos. Falta validacao prospectiva independente.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker',action='store_true');parser.add_argument('--once',action='store_true')
    parser.add_argument('--run-id',help=argparse.SUPPRESS)
    parser.add_argument('--symbol',help='Instrument queue; omitted selects the oldest eligible asset job')
    parser.add_argument('--retry',action='store_true',help='Explicitly resume a failed run, without changing its protocol')
    parser.add_argument('--verify',action='store_true',help='Recheck sealed reports and secondary control; never retrain a completed run')
    args=parser.parse_args()
    from aurelia_fx.storage import open_memory
    from aurelia_fx.training.repository import TrainingRepository,ACTIVE,RUN_LOCK,Cancelled
    memory=open_memory();repo=TrainingRepository(memory,args.symbol or 'EURUSD');state={}
    try:
        state=repo.latest()
        if args.worker:
            if state.get('run_id')!=args.run_id:raise RuntimeError('Training worker fenced by a newer run')
            repo.check(args.run_id);worker(repo,state);return
        import psutil
        from run_training_proof import stop_owned
        from aurelia_fx.training.runtime import sample,resource_reason,deferred,MIN_START_MB
        with memory.pool.connection() as lease:
            if not lease.execute('SELECT pg_try_advisory_lock(%s) AS acquired',(RUN_LOCK,)).fetchone()['acquired']:return
            if not args.symbol and not args.retry and not args.verify:
                from aurelia_fx.training.queue import schedule_selected,choose
                from mt5_provider import fetch_history
                schedule_selected(memory,fetch_history)
                symbol=choose(memory)
                if symbol is None:
                    from aurelia_fx.training.queue import symbols
                    for name in symbols(memory):
                        snapshot=TrainingRepository(memory,name).latest()
                        sample(memory,snapshot)
                        if snapshot.get('cancel_requested') and snapshot.get('run_id'):TrainingRepository(memory,name).finish_cancel(snapshot['run_id'])
                    return
                repo=TrainingRepository(memory,symbol)
            state=repo.latest()
            sample(memory,state)
            if state['status']=='FAILED' and str(state.get('message','')).startswith('RESOURCE_LIMIT'):
                state=repo.publish(state['run_id'],**deferred(state,'LEGACY_RESOURCE_LIMIT'))
            if state['status']=='AWAITING_PROSPECTIVE':
                if state.get('cancel_requested'):repo.finish_cancel(state['run_id'])
                return  # The live worker drives forward observations.
            if not args.retry and not args.verify and state['status'] not in ACTIVE|{'AWAITING_PROSPECTIVE'}:
                from aurelia_fx.training.automatic import schedule
                from aurelia_fx.operation_control import OperationControl
                from mt5_provider import fetch_history
                state=schedule(repo,OperationControl(memory,repo.symbol).status(),fetch_history)
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
            from aurelia_fx.historical.core import utc
            from datetime import datetime,timezone
            if state.get('retry_not_before') and datetime.now(timezone.utc)<utc(state['retry_not_before']):return
            if psutil.virtual_memory().available<MIN_START_MB*1024**2:
                repo.publish(run_id,status='WAITING_RESOURCES',message='Aguardando pelo menos 384 MB de RAM livre. Checkpoint preservado; a fila verifica novamente automaticamente.')
                return
            if not state.get('dataset_directory'):
                from aurelia_fx.training.dataset import export,export_rolling
                repo.publish(run_id,status='DATASET',stage='dataset',message='Exportando historico congelado.')
                from aurelia_fx.training.scope import profile_for
                profile=profile_for(state)
                if profile:
                    from aurelia_fx.training.dataset import export_asset
                    from mt5_provider import fetch_history
                    folder,manifest=export_asset(memory,ROOT,profile,fetch_history,
                        progress=lambda **kw:repo.publish(run_id,**kw),check=lambda:repo.check(run_id))
                    if manifest['source_clock_id']!=state['source_clock_id']:raise ValueError('TRAINING_SOURCE_CLOCK_MISMATCH')
                else:
                    exporter=export_rolling if state.get('dataset_policy')=='rolling' else export
                    folder,manifest=exporter(memory,ROOT,progress=lambda **kw:repo.publish(run_id,**kw))
                state=repo.publish(run_id,dataset_directory=str(folder.relative_to(ROOT)),dataset=manifest)
            from aurelia_fx.training.protocol import register
            from aurelia_fx.training.scope import identity,assert_same
            assert_same(state,state['dataset'])
            protocol_id=state.get('protocol_id') or register(memory,run_id,state['dataset']['dataset_id'],state.get('training_recipe','conservative'),scope=identity(state))
            if psutil.virtual_memory().available<MIN_START_MB*1024**2:
                repo.publish(run_id,status='WAITING_RESOURCES',stage='training',protocol_id=protocol_id,
                    message='Aguardando pelo menos 384 MB de RAM livre. O agente continua independente.')
                return
            output=ROOT/'data/training/runs'/run_id;output.mkdir(parents=True,exist_ok=True)
            repo.publish(run_id,status='TRAINING',stage='features',protocol_id=protocol_id,retry_not_before=None,completed=None,total=None,message='Iniciando ou retomando prova CPU com dados reais.')
            env={**os.environ,'HF_HOME':str(ROOT/'data/training/hf-home'),'HF_XET_CACHE':str(ROOT/'data/training/cache/xet')}
            with (output/'worker.log').open('a',encoding='utf-8') as log:
                child=subprocess.Popen([str(ROOT/'.venv-training/Scripts/python.exe'),'-u',str(Path(__file__).resolve()),'--worker','--run-id',run_id,'--symbol',repo.symbol],
                    cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            birth=psutil.Process(child.pid).create_time();started=time.monotonic();peak=0;last_runtime=0
            try:
                while child.poll() is None:
                    repo.check(run_id)
                    try:
                        process=psutil.Process(child.pid)
                        rss=sum(p.memory_info().rss for p in [process,*process.children(recursive=True)] if p.is_running())
                    except psutil.NoSuchProcess:rss=0
                    peak=max(peak,rss)
                    elapsed=time.monotonic()-started;available=psutil.virtual_memory().available/1024**2
                    if elapsed-last_runtime>=15 or not last_runtime:
                        sample(memory,state,worker_rss_mb=round(rss/1024**2,1),elapsed_seconds=round(elapsed,1),available_mb=available);last_runtime=max(elapsed,.001)
                    reason=resource_reason(rss/1024**2,available,elapsed)
                    if reason:
                        stop_owned(child,birth)
                        current=repo.latest()
                        repo.publish(run_id,**deferred(current,reason),resources=dict(last_attempt_peak_mb=round(peak/1024**2,1),wall_seconds=round(elapsed,1)))
                        sample(memory,current)
                        return
                    time.sleep(1)
                if child.wait(timeout=15)!=0:raise RuntimeError('WORKER_FAILED: inspect the run worker.log')
                sample(memory,repo.latest())
                with memory.pool.connection() as c:
                    previous=c.execute("SELECT MAX((payload_json::jsonb->'resources'->>'peak_process_tree_rss_mb')::float8) AS peak FROM project_records WHERE record_type=%s AND payload_json::jsonb->>'run_id'=%s",(repo.record_type('agent_training_lab_state'),run_id)).fetchone()['peak'] or 0
                repo.publish(run_id,resources=dict(peak_process_tree_rss_mb=max(previous,round(peak/1024**2,1)),
                    last_attempt_peak_mb=round(peak/1024**2,1),wall_seconds=round(time.monotonic()-started,2)))
            except Cancelled:
                if child.poll() is None:stop_owned(child,birth)
                repo.finish_cancel(run_id)
            except Exception as exc:repo.publish(run_id,status='FAILED',message=str(exc)[:200],stage='error')
            finally:
                if child.poll() is None:stop_owned(child,birth)
    except Cancelled:
        if state.get('run_id'):repo.finish_cancel(state['run_id'])
    except Exception as exc:
        if state.get('run_id') and state.get('status') in ACTIVE:
            try:repo.publish(state['run_id'],status='FAILED',stage='error',message=type(exc).__name__+': '+str(exc)[:160])
            except Cancelled:repo.finish_cancel(state['run_id'])
        raise
    finally:memory.close()

if __name__=='__main__':main()
