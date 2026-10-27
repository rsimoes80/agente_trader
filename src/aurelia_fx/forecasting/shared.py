"""One physical inference process shared by independent asset model handles."""
from dataclasses import asdict
import threading

from ..agent_model import fingerprint
from .adapter import TimestralAdapter


class SharedTimestralPool:
    def __init__(self,factory=TimestralAdapter):
        self.factory=factory;self.lock=threading.RLock();self.refs={}
        self.active=None;self.active_key=None;self.closed=False

    def acquire(self,config):
        key=fingerprint(asdict(config))
        with self.lock:
            if self.closed:raise RuntimeError('Inference pool is closed.')
            self.refs[key]=self.refs.get(key,0)+1
        return ModelHandle(self,config,key)

    def call(self,handle,method,*args):
        with self.lock:
            if self.closed or handle.closed:raise RuntimeError('Inference handle is closed.')
            if self.active_key!=handle.key:
                if self.active:self.active.close()
                self.active=None;self.active_key=None
                self.active=self.factory(handle.config);self.active_key=handle.key
            return getattr(self.active,method)(*args)

    def release(self,handle):
        with self.lock:
            if handle.closed:return
            handle.closed=True;self.refs[handle.key]-=1
            if not self.refs[handle.key]:
                del self.refs[handle.key]
                if self.active_key==handle.key:
                    self.active.close();self.active=None;self.active_key=None

    def close(self):
        with self.lock:
            self.closed=True
            if self.active:self.active.close()
            self.active=None;self.active_key=None


class ModelHandle:
    def __init__(self,pool,config,key):
        self.pool=pool;self.config=config;self.key=key;self.closed=False
    def warmup(self):return self.pool.call(self,'warmup')
    def forecast(self,values):return self.pool.call(self,'forecast',values)
    def forecast_batch(self,values):return self.pool.call(self,'forecast_batch',values)
    def close(self):self.pool.release(self)


POOL=SharedTimestralPool()
