"""Portable coordinator settings; no credentials or account authority here."""
import json
import os
from pathlib import Path


def load_settings(root,*,environ=None):
    environ=os.environ if environ is None else environ
    path=Path(root)/'data/multi_asset.json'
    settings=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if not isinstance(settings,dict):raise ValueError('Invalid multi-asset settings.')
    result={**dict(schema_version=1,enabled=False,max_workers=8),**settings}
    if result['schema_version']!=1 or type(result['enabled']) is not bool or type(result['max_workers']) is not int or not 1<=result['max_workers']<=32:
        raise ValueError('Invalid multi-asset settings.')
    override=environ.get('AGENTE_TRADER_MULTI_ASSET')
    if override is not None:
        if override not in {'0','1'}:raise ValueError('AGENTE_TRADER_MULTI_ASSET must be 0 or 1.')
        result['enabled']=override=='1'
    return result
