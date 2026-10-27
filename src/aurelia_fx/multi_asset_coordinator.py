"""Independent durable asset workers, bounded resources and aggregate liveness.

The injected worker owns its analysis/reconciliation loop. This coordinator does
not infer positions, approve strategies or start sessions by selecting a symbol.
"""
from dataclasses import dataclass,field
import threading
import time

from .instruments import symbol_name


@dataclass
class Slot:
    symbol: str
    stop: threading.Event=field(default_factory=threading.Event)
    thread: threading.Thread | None=None
    progressed_at: float=0.
    retry_at: float=0.
    failures: int=0
    error: str | None=None


class MultiAssetCoordinator:
    def __init__(self,selected,serve,*,max_workers=8,stall_seconds=600,now=time.monotonic):
        if not 1<=max_workers<=32 or stall_seconds<30:raise ValueError('Invalid coordinator resource limits.')
        self.selected=selected;self.serve=serve;self.max_workers=max_workers
        self.stall_seconds=stall_seconds;self.now=now;self.slots={};self.queued=[]
        self.lock=threading.RLock();self.closed=False

    def _progress(self,slot):
        with self.lock:
            if self.slots.get(slot.symbol) is slot:slot.progressed_at=self.now()

    def _serve(self,slot):
        try:
            self.serve(slot.symbol,slot.stop,lambda:self._progress(slot))
        except Exception as exc:
            with self.lock:slot.error=type(exc).__name__
        finally:
            with self.lock:
                if not slot.stop.is_set():
                    slot.failures+=1
                    slot.retry_at=self.now()+min(300,10*2**min(slot.failures-1,5))

    def poll(self):
        wanted=list(dict.fromkeys(symbol_name(s) for s in self.selected()))
        with self.lock:
            if self.closed:raise RuntimeError('Coordinator is closed.')
            for symbol,slot in list(self.slots.items()):
                if symbol not in wanted:
                    slot.stop.set()
                    if not slot.thread.is_alive():self.slots.pop(symbol)
            alive=sum(s.thread.is_alive() for s in self.slots.values())
            self.queued=[]
            for symbol in wanted:
                slot=self.slots.get(symbol)
                if slot and slot.thread.is_alive():continue
                if slot and self.now()<slot.retry_at:continue
                if alive>=self.max_workers:self.queued.append(symbol);continue
                # Never reuse a cancellation event or overlap two generations.
                slot=Slot(symbol,progressed_at=self.now(),failures=slot.failures if slot else 0)
                self.slots[symbol]=slot
                slot.thread=threading.Thread(target=self._serve,args=(slot,),name='asset:'+symbol,daemon=True)
                slot.thread.start();alive+=1
            return self.status()

    def status(self):
        with self.lock:
            workers={symbol:dict(alive=s.thread.is_alive(),stopping=s.stop.is_set(),
                       progress_age_seconds=max(0.,self.now()-s.progressed_at),error=s.error,
                       failures=s.failures,retry_in_seconds=max(0.,s.retry_at-self.now()))
                     for symbol,s in self.slots.items()}
            healthy=all(not s.thread.is_alive() or self.now()-s.progressed_at<self.stall_seconds for s in self.slots.values())
            return dict(healthy=healthy,workers=workers,queued=list(self.queued),max_workers=self.max_workers)

    def close(self,timeout=10):
        with self.lock:
            self.closed=True;slots=list(self.slots.values())
            for slot in slots:slot.stop.set()
        deadline=time.monotonic()+timeout
        for slot in slots:slot.thread.join(max(0.,deadline-time.monotonic()))
        return all(not slot.thread.is_alive() for slot in slots)
