"""Fair per-asset queues; the runner holds the single global heavy-work lease."""
from datetime import datetime,timezone
from .repository import TrainingRepository,ACTIVE
from aurelia_fx.historical.core import utc


def symbols(memory):
    from aurelia_fx.asset_registry import AssetRegistry
    selected=[a['symbol'] for a in AssetRegistry(memory).list() if a.get('selected')]
    # Existing queued jobs remain visible/cancellable after asset selection changes.
    with memory.pool.connection() as c:
        rows=c.execute("SELECT DISTINCT record_type FROM project_records WHERE record_type LIKE 'agent_training_lab_state:%'").fetchall()
    return list(dict.fromkeys(['EURUSD',*selected,*[r['record_type'].split(':',1)[1] for r in rows]]))


def choose(memory,*,now=None):
    now=utc(now or datetime.now(timezone.utc));pending=[]
    for symbol in symbols(memory):
        repo=TrainingRepository(memory,symbol);s=repo.latest()
        if s.get('cancel_requested') and s['status'] in ACTIVE:
            repo.finish_cancel(s['run_id']);continue
        if s['status'] not in ACTIVE-{'AWAITING_PROSPECTIVE'}:continue
        if s.get('retry_not_before') and utc(s['retry_not_before'])>now:continue
        # A deferred run yields its slot; otherwise a large job can starve others.
        order=s.get('retry_not_before') or s.get('created_at') or s.get('updated_at')
        pending.append((utc(order) if order else now,symbol))
    return min(pending)[1] if pending else None


def schedule_selected(memory,fetch):
    from .automatic import schedule
    from aurelia_fx.asset_registry import AssetRegistry
    from aurelia_fx.operation_control import OperationControl
    for asset in AssetRegistry(memory).list():
        if not asset.get('selected'):continue
        symbol=asset['symbol'];repo=TrainingRepository(memory,symbol)
        if repo.latest()['status'] in ACTIVE:continue
        schedule(repo,OperationControl(memory,symbol).status(),fetch)
