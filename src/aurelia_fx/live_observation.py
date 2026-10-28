"""Market-data-only bridge facade for the independent live observer."""
from .bridge_transport import BridgeClient
from datetime import datetime,timezone
import json


class ReadOnlyBridgeClient(BridgeClient):
    OPERATIONS = frozenset({'status','fetch_history','instrument_catalog','inspect_instrument'})

    def call(self, operation, *args, **kwargs):
        if operation not in self.OPERATIONS:
            raise ValueError('LIVE_OBSERVATION_READ_ONLY')
        return super().call(operation, *args, **kwargs)


def observation_status(memory, *, now=None):
    now=now or datetime.now(timezone.utc)
    with memory.pool.connection() as c:
        row=c.execute("SELECT payload_json,recorded_at FROM project_records WHERE record_type='live_observation_status' AND record_key='EURUSD' ORDER BY recorded_at DESC LIMIT 1").fetchone()
    if row is None:return dict(status='NOT_STARTED',orders_enabled=False)
    status=json.loads(row['payload_json'])
    age=max(0,(now-row['recorded_at']).total_seconds())
    if age>120:status['status']='STALE'
    return dict(status,orders_enabled=False,heartbeat_age_seconds=round(age,1))
