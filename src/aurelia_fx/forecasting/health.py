"""Per-asset inference health. Background probes never mutate trading state."""
from datetime import datetime, timedelta, timezone
import math
import queue
import threading
import time

from .adapter import ModelUnavailable


def stamp(now=None):
    return (now or datetime.now(timezone.utc)).isoformat()


def failure(state, exc, *, configuration, now=None):
    at=now or datetime.now(timezone.utc)
    code=getattr(exc,'code','INVALID_OUTPUT' if isinstance(exc,ValueError) else type(exc).__name__)
    # Only controlled adapter messages are exposed; arbitrary exception strings
    # may contain database URLs or other service credentials.
    message=str(exc) if isinstance(exc,ModelUnavailable) else 'A previsão não pôde ser validada.'
    record=dict(at=stamp(at),code=code,phase=getattr(exc,'phase',None),
        message=message[:220],details=getattr(exc,'details',{}),
        retry_at=stamp(at+timedelta(seconds=getattr(exc,'retry_seconds',60))))
    health=state.setdefault('forecast_health',{})
    health.update(status='WAITING_RESOURCES' if code in {'WAITING_RESOURCES','MEMORY_LIMIT'} else 'UNAVAILABLE',
        configuration=configuration,last_attempt=stamp(at),current_failure=record,last_failure=record)
    if not record['details'].get('retry_pending'):
        health['failure_count']=health.get('failure_count',0)+1
    return record


def success(state, output, *, configuration, now=None, source='engine'):
    health=state.setdefault('forecast_health',{})
    at=stamp(now)
    health.update(configuration=configuration,last_attempt=at,last_result=at)
    if source=='cache':
        # An old cached forecast does not prove that an engine is alive now.
        if health.get('status')!='AVAILABLE':health['status']='CACHE_ONLY'
        return
    health.update(status='AVAILABLE',current_failure=None,last_success=at,
        artifact_sha256=output.get('artifact_sha256'),model=output.get('model'),
        latency_ms=output.get('latency_ms'),last_success_source=source)


def forecast_or_wait(operation, context, decision):
    try:
        return operation(context)[1]
    except ModelUnavailable as exc:
        decision.update(action='WAIT',reason='TIMESTRAL_UNAVAILABLE',forecast_error=dict(
            code=exc.code,phase=exc.phase,message=str(exc),details=exc.details))
        return None


def consume_probe(state,probe,*,configuration):
    checked=probe.poll()
    if not checked or checked['configuration']!=configuration:return False
    if checked['error'] is not None:
        failure(state,checked['error'],configuration=configuration)
    else:
        success(state,checked['output'],configuration=configuration,source='healthcheck')
    return True


class ForecastProbe:
    """One bounded in-flight check; consume its result on the owner thread.

    Successful probes repeat after five minutes; failures after their retry
    interval. Config changes are checked by the caller before accepting results.
    The adapter/pool serializes physical inference for all consumers.
    """
    def __init__(self,operation,*,clock=time.monotonic):
        self.operation=operation;self.clock=clock;self.next_at=0.
        self.thread=None;self.results=queue.Queue();self.closed=False

    def request(self,values,*,configuration,signal_at):
        if self.closed or self.clock()<self.next_at or self.thread and self.thread.is_alive():return False
        frozen=tuple(values)
        self.next_at=self.clock()+300
        self.thread=threading.Thread(target=self._run,args=(frozen,configuration,signal_at),
            name='timestral-health',daemon=True)
        self.thread.start();return True

    @property
    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def _run(self,values,configuration,signal_at):
        output=None;error=None
        try:
            output=self.operation(list(values))
            rows=output['quantiles']
            if len(rows)!=12 or any(len(row)!=3 or not all(math.isfinite(v) and v>0 for v in row)
                or not row[0]<=row[1]<=row[2] for row in rows):
                raise ValueError('INVALID_FORECAST_QUANTILES')
        except Exception as exc:
            error=exc
        self.results.put(dict(configuration=configuration,signal_at=signal_at,output=output,error=error))

    def poll(self):
        try:result=self.results.get_nowait()
        except queue.Empty:return None
        if result['error'] is not None:self.next_at=self.clock()+getattr(result['error'],'retry_seconds',60)
        return result

    def close(self):
        self.closed=True
