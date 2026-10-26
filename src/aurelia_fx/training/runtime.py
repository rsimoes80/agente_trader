"""Windows training telemetry and bounded retry policy; no broker controls."""
from datetime import datetime,timedelta,timezone
from uuid import uuid4
from aurelia_fx.historical.core import utc

MIN_START_MB=384
MIN_FREE_MB=128
MAX_WORKER_MB=768
MAX_SECONDS=7200
RETRY_SECONDS=900
MAX_RESOURCE_RETRIES=3


def sample(memory, state, *, worker_rss_mb=None, elapsed_seconds=None, available_mb=None):
    if available_mb is None:
        import psutil
        available_mb=psutil.virtual_memory().available/1024**2
    data=dict(at=datetime.now(timezone.utc).isoformat(),run_id=state.get('run_id'),
        host_role='windows_training_runner',available_mb=round(available_mb,1),
        minimum_start_mb=MIN_START_MB,minimum_free_mb=MIN_FREE_MB,maximum_worker_mb=MAX_WORKER_MB,
        maximum_seconds=MAX_SECONDS,worker_rss_mb=worker_rss_mb,elapsed_seconds=elapsed_seconds,
        shortage_mb=round(max(0,MIN_START_MB-available_mb),1))
    memory.record_project_data('agent_training_runtime',str(uuid4()),data)
    return data


def resource_reason(rss_mb, available_mb, elapsed):
    if rss_mb>MAX_WORKER_MB:return 'WORKER_RAM_LIMIT'
    if available_mb<MIN_FREE_MB:return 'HOST_RAM_LOW'
    if elapsed>MAX_SECONDS:return 'TIME_BUDGET'
    return None


def deferred(state, reason, now=None):
    now=utc(now or datetime.now(timezone.utc));retries=state.get('resource_retries',0)+1
    retry=reason in {'HOST_RAM_LOW','TIME_BUDGET','LEGACY_RESOURCE_LIMIT'} and retries<=MAX_RESOURCE_RETRIES
    return dict(status='WAITING_RESOURCES' if retry else 'FAILED',stage=state.get('stage','training'),
        resource_retries=retries,resource_reason=reason,
        retry_not_before=(now+timedelta(seconds=RETRY_SECONDS)).isoformat() if retry else None,
        message=('Treino suspenso por recursos. A fila tentará retomar o checkpoint após 15 minutos; negociação preservada.'
            if retry else 'Treino interrompido: limite do processo ou tentativas excedidas. Revisão técnica necessária; não será reiniciado em ciclo.'))


def learning_summary(state):
    from .protocol import RECIPES
    report=state.get('forecast_report') or {};test=(report.get('partitions') or {}).get('test') or {}
    sim=state.get('financial_report') or {};arms=sim.get('arms') or {}
    decision=state.get('decision') or {}
    return dict(recipe=state.get('training_recipe','conservative'),
        settings=report.get('training_settings') or RECIPES.get(state.get('training_recipe','conservative')),
        scope='Ajuste da saída do Timestral-5M; não é treinamento do robô inteiro.',
        forecast_improvement_pct=(test.get('gate') or {}).get('pinball_improvement_pct'),
        source_net=(arms.get('source') or {}).get('net_pnl'),candidate_net=(arms.get('candidate') or {}).get('net_pnl'),
        financial_status=sim.get('status'),reasons=decision.get('reasons',[]),
        conclusion=('Interrompido antes da conclusão: não há evidência de melhora.' if state.get('status')=='FAILED' else
                    'Treino cancelado; esta tentativa não será retomada automaticamente.' if state.get('status')=='CANCELLED' else
                    'Aguardando recursos; resultado ainda não concluído.' if state.get('status')=='WAITING_RESOURCES' else
                    'Candidato não aprovado; modelo atual mantido.' if state.get('status')=='NOT_APPROVED' else
                    'Critérios retrospectivos atendidos; falta avaliação futura.' if state.get('status')=='AWAITING_PROSPECTIVE' else
                    'Troca registrada após validação.' if state.get('status')=='PROMOTED' else
                    'Experimento ainda sem conclusão.'),
        live_model_changed=bool(state.get('live_model_changed',False)))
