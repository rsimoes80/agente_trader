"""Read-only learning evidence. Configuration, saved weights and use are distinct."""
import math
import re
from datetime import datetime,timezone


def model_view(agent,worker):
    symbol=agent.get('symbol','EURUSD');profile_id=agent.get('profile_id')
    runtime=agent.get('model_runtime') or {}
    valid=(runtime.get('symbol')==symbol and runtime.get('profile_id')==profile_id
           and runtime.get('session_id')==agent.get('session_id'))
    selected=runtime.get('selected') if valid else None
    used=runtime.get('last_result') if valid else None
    heartbeat=worker.get('heartbeat') or {}
    current=bool(worker.get('available') and valid and runtime.get('worker_id')==heartbeat.get('worker_id'))
    matches=bool(selected and used and used.get('configuration')==selected.get('configuration')
                 and used.get('worker_id')==runtime.get('worker_id') and used.get('artifact_sha256'))
    return dict(symbol=symbol,profile_id=profile_id,selected=selected,last_result=used,
        worker_available=bool(worker.get('available')),current_worker=current,
        result_matches_selected=matches,
        status='CONFIRMED_RESULT' if current and matches else 'CONFIGURED' if selected and current else 'LAST_RECORDED' if selected else 'UNKNOWN',
        note=('Último modelo utilizado confirmado; a data indica o uso do resultado, não residência contínua na RAM.' if current and matches else
              'Modelo configurado; aguardando uma previsão desta versão.' if selected and current else
              'Último registro salvo. O serviço atual ainda não confirmou esta versão.' if selected else
              'Aguardando o serviço informar o modelo. Não é possível deduzi-lo pelo estado do treino.'))


REASONS={
 'PINBALL_IMPROVEMENT_BELOW_2_PERCENT':'A redução do erro de previsão ficou abaixo dos 2% exigidos.',
 'PAIRED_DAY_EVIDENCE_INCONCLUSIVE':'A comparação por dias não demonstrou melhora estatística.',
 'FORECAST_SAMPLE_INSUFFICIENT':'Há menos de 200 previsões avaliadas.',
 'FINANCIAL_SAMPLE_INSUFFICIENT':'Há menos de 20 operações simuladas encerradas por versão.',
 'NET_PROFIT_NOT_POSITIVE':'O resultado líquido do candidato não foi positivo.',
 'NET_PROFIT_BELOW_SOURCE_OR_UNRESOLVED':'O resultado líquido não superou o original ou não pôde ser confirmado.',
 'DRAWDOWN_ABOVE_SOURCE':'A queda máxima do candidato foi maior que a do original.',
 'EXPOSURE_UNRESOLVED':'Restou exposição simulada sem resolução confirmada.',
 'FORECAST_PREFILTER_FAILED':'A previsão foi reprovada; a simulação financeira foi dispensada.',
 'INSTRUMENT_EVIDENCE_MISMATCH':'As evidências não pertencem ao mesmo ativo e perfil.',
 'PROSPECTIVE_EVIDENCE_REQUIRED':'Falta validação com dados futuros independentes.',
 'PROSPECTIVE_SAMPLE_INSUFFICIENT':'A amostra futura ainda não atingiu o mínimo.',
 'ASSET_PROSPECTIVE_SAMPLE_INSUFFICIENT':'Faltam dias, previsões ou operações futuras com cobertura confirmada.',
 'HOST_RAM_LOW':'Treino pausado por recursos; checkpoint preservado para retomada.',
 'WORKER_RAM_LIMIT':'O processo atingiu seu limite de memória; esta tentativa requer revisão.',
 'TIME_BUDGET':'A tentativa atingiu o limite de tempo; consulte a retomada registrada.',
 'LEGACY_RESOURCE_LIMIT':'A tentativa anterior foi interrompida por limite de recursos.',
}


def reason_text(code):
    if code in REASONS:return REASONS[code]
    match=re.fullmatch(r'(MAE_DEGRADED|DIRECTION_DEGRADED|INTERVAL_COVERAGE_OUTSIDE_GATE)_(3|6|12)',code)
    if match:
        label={'MAE_DEGRADED':'O erro médio piorou além do limite',
               'DIRECTION_DEGRADED':'O acerto de direção caiu além do limite',
               'INTERVAL_COVERAGE_OUTSIDE_GATE':'A cobertura do intervalo ficou fora da faixa exigida'}[match[1]]
        return label+' no horizonte de '+str(int(match[2])*5)+' minutos.'
    return 'Critério registrado: '+code


def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def metric(label,source,candidate,unit,*,lower=True):
    valid=number(source) and number(candidate)
    delta=candidate-source if valid else None
    change='UNAVAILABLE' if not valid else 'UNCHANGED' if abs(delta)<1e-12 else 'IMPROVED' if (delta<0)==lower else 'WORSE'
    return dict(label=label,source=source if number(source) else None,candidate=candidate if number(candidate) else None,
                delta=delta,unit=unit,change=change)


def evolution(state,agent,worker,history=()):
    from .scope import identity
    scope=identity(state) if state.get('run_id') else dict(symbol=state.get('symbol','EURUSD'),profile_id=state.get('profile_id') or agent.get('profile_id'))
    runtime=model_view(agent,worker)
    if agent.get('symbol','EURUSD')!=scope['symbol']:raise ValueError('MODEL_PANEL_SYMBOL_MISMATCH')
    report=state.get('forecast_report') or {};selection=report.get('selection') or state.get('selection') or {}
    test=(report.get('partitions') or {}).get('test') or {}
    financial=state.get('financial_report') or {};arms=financial.get('arms') or {}
    source=test.get('source') or {};candidate=test.get('candidate') or {}
    unit='unidades de '+str((state.get('dataset') or {}).get('price_unit')) if (state.get('dataset') or {}).get('price_unit') else 'pips'
    comparisons=[]
    if test:
        comparisons.append(metric('Erro de previsão (perda quantílica)',source.get('mean_pinball_pips'),candidate.get('mean_pinball_pips'),unit))
        for h in ('3','6','12'):
            a=(source.get('horizons') or {}).get(h) or {};b=(candidate.get('horizons') or {}).get(h) or {}
            comparisons.append(metric('Erro médio · '+str(int(h)*5)+' min',a.get('mae_pips'),b.get('mae_pips'),unit))
        a=(source.get('horizons') or {}).get('12') or {};b=(candidate.get('horizons') or {}).get('12') or {}
        comparisons.append(metric('Acerto de direção · 60 min',a.get('direction_accuracy_pct'),b.get('direction_accuracy_pct'),'%',lower=False))
    if arms:
        a=arms.get('source') or {};b=arms.get('candidate') or {}
        comparisons.extend((metric('Resultado líquido após custos',a.get('net_pnl'),b.get('net_pnl'),'USD',lower=False),
                            metric('Queda máxima (drawdown)',a.get('max_close_equity_drawdown_pct'),b.get('max_close_equity_drawdown_pct'),'%')))
    reasons=[];seen=set()
    def add(code,phase):
        key=(code,phase)
        if key not in seen:
            seen.add(key);reasons.append(dict(code=code,phase=phase,message=reason_text(code)))
    for phase,part in (report.get('partitions') or {}).items():
        for code in (part.get('gate') or {}).get('reasons',[]):add(code,phase)
    for code in (financial.get('gate') or {}).get('reasons',[]):add(code,'simulation')
    for code in (state.get('decision') or {}).get('reasons',[]):
        if not any(k[0]==code for k in seen):add(code,'decision')
    if state.get('resource_reason') and state.get('status') in {'WAITING_RESOURCES','FAILED'}:add(state['resource_reason'],'execution')
    update=state.get('weight_update') or report.get('weight_update')
    epochs=report.get('epochs') or []
    legacy=not update and (any(e.get('epoch',0)>0 for e in epochs) or (state.get('saved_checkpoint') or {}).get('stage')=='training')
    weights=dict(status='SAVED_UPDATE' if update else 'LEGACY_REPORT' if legacy else 'NOT_RECORDED',
        update=update,selected_epoch=selection.get('selected_epoch'),
        candidate_changed=selection.get('candidate_weights_changed'),sealed_at=selection.get('sealed_at'),
        message=('Ajuste salvo em checkpoint; isso não significa aprovação ou aplicação.' if update else
                 'Há registro de épocas concluídas, sem data exata do ajuste no formato atual.' if legacy else
                 'Ainda não há ajuste de pesos salvo registrado nesta execução. Preparar contextos não ajusta os pesos.'))
    if selection.get('selected_epoch')==0:
        weights['message']+=' A seleção manteve a época zero: o candidato usa os pesos originais.'
    elif update and update.get('changed_from_source') is False:
        weights['message']+=' O checkpoint não apresentou diferença numérica em relação à base.'
    digest=selection.get('candidate_sha256');used=runtime.get('last_result') or {};selected=runtime.get('selected') or {}
    same_profile=scope['profile_id']==agent.get('profile_id')
    applied=bool(digest and same_profile and runtime['current_worker'] and runtime['result_matches_selected']
                 and used.get('artifact_sha256')==digest and selected.get('artifact_sha256')==digest)
    status=state.get('status','NOT_STARTED')
    application=('IN_USE' if applied else 'APPROVED_PENDING_USE' if status=='PROMOTED' else
                 'NOT_APPROVED' if status in {'NOT_APPROVED','FAILED','CANCELLED'} else
                 'NO_CANDIDATE' if status=='NOT_STARTED' else 'PENDING_EVALUATION')
    title=('Candidato em uso confirmado' if applied else 'Aprovado; aguardando confirmação de uso' if status=='PROMOTED' else
           'Candidato rejeitado; modelo atual mantido' if status=='NOT_APPROVED' else
           'Aguardando validação futura' if status=='AWAITING_PROSPECTIVE' else
           'Treino interrompido; sem aprovação' if status=='FAILED' else
           'Aguardando retomada do treino' if status=='WAITING_RESOURCES' else
           'Treino cancelado' if status=='CANCELLED' else 'Avaliação ainda não concluída')
    dataset=state.get('dataset') or {}
    return dict(model=runtime,weights=weights,comparisons=comparisons,reasons=reasons,
        decision=dict(status=status,title=title,application=application,message=state.get('message'),
            retry_not_before=state.get('retry_not_before'),prospective=state.get('study_summary'),criteria=state.get('study_protocol')),
        comparison_basis='Original Timestral-5M versus candidato Timestral-5M no mesmo período separado. A comparação com o modelo ativo exige o estudo futuro.',
        trace=dict(**scope,run_id=state.get('run_id'),protocol_id=state.get('protocol_id'),dataset_id=dataset.get('dataset_id'),
            source_clock_id=dataset.get('source_clock_id'),source_start=dataset.get('source_start'),source_as_of=dataset.get('source_as_of'),
            partitions=dataset.get('counts'),boundaries=dataset.get('boundaries'),array_sha256=dataset.get('array_sha256'),
            source_model=report.get('source_model'),source_revision=report.get('source_revision'),source_sha256=report.get('source_sha256'),
            candidate_sha256=digest,configuration=selected.get('configuration'),release=state.get('release'),
            last_model_result=used,weight_update=update),
        history=list(history))


def select_model(account,config,*,symbol,profile_id,worker_id,now=None):
    stamp=(now or datetime.now(timezone.utc)).isoformat()
    old=account.data.get('model_runtime') or {}
    last=old.get('last_result') if old.get('symbol')==symbol and old.get('profile_id')==profile_id and old.get('session_id')==account.data['session_id'] else None
    selected=dict(model=config.model,revision=config.revision,configuration=config.fingerprint,
                  artifact_sha256=config.local_artifact_sha256 or None,release=config.local_release or None,selected_at=stamp)
    account.data['model_runtime']=dict(symbol=symbol,profile_id=profile_id,session_id=account.data['session_id'],
        worker_id=worker_id,selected=selected,last_result=last)


def use_result(account,config,output,*,now=None):
    runtime=account.data.get('model_runtime')
    if runtime is None:return
    if not output.get('model') or not re.fullmatch(r'[0-9a-f]{64}',output.get('artifact_sha256','')):return
    evidence=output.get('execution_evidence') or {}
    runtime['last_result']=dict(model=output.get('model'),revision=output.get('revision'),
        artifact_sha256=output.get('artifact_sha256'),sdk_revision=output.get('sdk_revision'),
        configuration=config.fingerprint,used_at=(now or datetime.now(timezone.utc)).isoformat(),
        computed_at=evidence.get('computed_at'),source=evidence.get('source','engine'),cache_key=evidence.get('cache_key'),worker_id=runtime['worker_id'])
