"""Versioned, fail-closed activation and rollback. No automatic live promotion."""
import json,os,time
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from .proof import file_hash

def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,indent=2),encoding='utf-8')
        for attempt in range(6):
            try:os.replace(temporary,path);break
            except PermissionError:
                if attempt==5:raise
                time.sleep(.05*(attempt+1))
    finally:
        if temporary.exists():temporary.unlink()

def eligible(report,financial,prospective):
    reasons=[]
    if not all(report['partitions'][p]['gate']['passed'] for p in ('validation','test')):reasons.append('FORECAST_GATE_FAILED')
    if not financial['gate']['passed']:reasons.append('FINANCIAL_GATE_FAILED')
    if not prospective or not prospective.get('gate',{}).get('passed'):reasons.append('PROSPECTIVE_EVIDENCE_REQUIRED')
    if prospective:
        if prospective.get('days',0)<7 or min(prospective.get('closed_trades_per_arm',[0]))<20:reasons.append('PROSPECTIVE_SAMPLE_INSUFFICIENT')
        if prospective.get('candidate_sha256')!=report['selection']['candidate_sha256']:reasons.append('PROSPECTIVE_CANDIDATE_MISMATCH')
        if not prospective.get('protocol_id') or not prospective.get('independent_future_data'):reasons.append('PROSPECTIVE_PROTOCOL_REQUIRED')
    return reasons

def activate(root,run_id,config_path=None):
    """Explicit CLI only. Rechecks artifacts; writes backup before switching config."""
    root=Path(root).resolve();folder=(root/'data/training/runs'/run_id).resolve()
    if folder.parent!=root/'data/training/runs':raise ValueError('Invalid run identifier')
    report=json.loads((folder/'forecast-report.json').read_text());financial=json.loads((folder/'simulation-report.json').read_text())
    future=folder/'prospective-report.json';prospective=json.loads(future.read_text()) if future.exists() else None
    reasons=eligible(report,financial,prospective)
    if reasons:raise ValueError('Activation denied: '+', '.join(reasons))
    weights=folder/'candidate/model.safetensors';digest=file_hash(weights)
    if digest!=report['selection']['candidate_sha256']:raise ValueError('Candidate artifact changed')
    release=root/'data/training/releases'/run_id/'release.json'
    payload=dict(run_id=run_id,approved=True,candidate_sha256=digest,
        model_directory=str((folder/'candidate').relative_to(root)),created_at=datetime.now(timezone.utc).isoformat(),
        forecast_report_sha256=file_hash(folder/'forecast-report.json'),financial_report_sha256=file_hash(folder/'simulation-report.json'),
        prospective_report_sha256=file_hash(future))
    config_path=Path(config_path or root/'data/timestral.json')
    old=json.loads(config_path.read_text())
    backup=release.parent/'previous-config.json'
    if release.exists():
        resolve(root,str(release.relative_to(root)),digest)
        if old.get('local_release')==str(release.relative_to(root)) and old.get('local_artifact_sha256')==digest:return str(release.relative_to(root))
        if not backup.exists() or json.loads(backup.read_text())!=old:raise ValueError('Existing release conflicts with current configuration')
        # Recover a crash between writing evidence and switching the configuration.
    else:
        atomic_json(backup,old);atomic_json(release,payload)
    new={**old,'model':report['source_model'],'revision':digest,'local_release':str(release.relative_to(root)),
        'local_artifact_sha256':digest}
    from aurelia_fx.forecasting.config import TimestralConfig
    if 'horizons' in new:new['horizons']=tuple(new['horizons'])
    TimestralConfig(**new);atomic_json(config_path,new)
    return str(release.relative_to(root))

def resolve(root,release_path,digest):
    root=Path(root).resolve();release=(root/release_path).resolve()
    if not release.is_relative_to(root/'data/training/releases'):raise ValueError('Release outside registry')
    payload=json.loads(release.read_text())
    if not payload.get('approved') or payload['candidate_sha256']!=digest:raise ValueError('Unapproved release')
    folder=(root/payload['model_directory']).resolve()
    if not folder.is_relative_to(root/'data/training/runs'):raise ValueError('Model outside training artifacts')
    for filename,key in (('forecast-report.json','forecast_report_sha256'),('simulation-report.json','financial_report_sha256'),('prospective-report.json','prospective_report_sha256')):
        if file_hash(folder.parent/filename)!=payload[key]:raise ValueError('Release evidence changed')
    report=json.loads((folder.parent/'forecast-report.json').read_text());financial=json.loads((folder.parent/'simulation-report.json').read_text());future=json.loads((folder.parent/'prospective-report.json').read_text())
    if eligible(report,financial,future):raise ValueError('Release gates no longer valid')
    if file_hash(folder/'model.safetensors')!=digest:raise ValueError('Model artifact changed')
    return folder

def rollback(root,run_id,config_path=None):
    root=Path(root).resolve();release=(root/'data/training/releases'/run_id).resolve()
    if release.parent!=root/'data/training/releases':raise ValueError('Invalid release identifier')
    config_path=Path(config_path or root/'data/timestral.json');current=json.loads(config_path.read_text())
    if current.get('local_release')!=str((release/'release.json').relative_to(root)):raise ValueError('This release is not active; rollback refused')
    previous=json.loads((release/'previous-config.json').read_text());atomic_json(config_path,previous)
    return previous
