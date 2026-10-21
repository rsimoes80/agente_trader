import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from unittest.mock import patch
from contextlib import nullcontext, ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys

from run_agent import guarded_fetch, RecoverableSourceError, retry_due


class AgentSourceRetryTests(unittest.TestCase):
    def test_only_transient_source_errors_are_retried(self):
        with self.assertRaises(RecoverableSourceError):
            guarded_fetch(Mock(side_effect=RuntimeError("MT5 offline")), "EURUSD", "M5", 100)
        with self.assertRaises(ValueError):
            guarded_fetch(Mock(side_effect=ValueError("Unknown symbol")), "EURUSD", "M5", 100)
        self.assertEqual(guarded_fetch(lambda *args: "fixture"), "fixture")

    def test_retry_waits_for_deadline_and_honors_pause_or_stop(self):
        now = datetime.now(timezone.utc)
        state = dict(state="WAITING_SOURCE", desired="running", retry_after=(now+timedelta(seconds=10)).isoformat())
        self.assertFalse(retry_due(state, now))
        self.assertTrue(retry_due(state, now+timedelta(seconds=10)))
        for desired in ("paused", "stopped"):
            self.assertFalse(retry_due({**state,"desired":desired},now+timedelta(minutes=1)))
        self.assertFalse(retry_due({**state,"state":"ERROR"},now+timedelta(minutes=1)))

    def test_worker_retries_source_without_creating_another_session(self):
        import run_agent
        state = dict(session_id="fixture-session",state="QUEUED",desired="running",generation=1)
        transitions=[]
        class Stop:
            count=0
            def is_set(self):return self.count>=4
            def wait(self, *args):self.count+=1
            def set(self):self.count=4
        def publish(session_id, **changes):
            self.assertEqual(session_id,"fixture-session")
            state.update({k:v for k,v in changes.items() if not k.startswith("expected_")})
            transitions.append(state["state"])
            return dict(state)
        control=SimpleNamespace(status=lambda:dict(state),publish=publish,heartbeat=Mock())
        lease=Mock();lease.closed=False
        lease.execute.return_value.fetchone.return_value={"acquired":True}
        memory=SimpleNamespace(pool=SimpleNamespace(connection=lambda:nullcontext(lease)),close=Mock())
        attempts=[]
        def prepare(*args):
            attempts.append(args[2]["session_id"])
            if len(attempts)==1:raise RecoverableSourceError("fixture MT5 offline")
            publish("fixture-session",state="TRAINING_BLOCKED")
        with TemporaryDirectory() as directory, ExitStack() as patches:
            root=Path(directory);(root/"data").mkdir()
            patches.enter_context(patch.dict(sys.modules,{"mt5_provider":SimpleNamespace(fetch_history=Mock())}))
            for name,value in {"ROOT":root,"open_memory":lambda:memory,"OperationControl":lambda m:control,
                               "HistoricalRepository":Mock(),"prepare":prepare,
                               "retry_due":lambda s:s["state"]=="WAITING_SOURCE"}.items():
                patches.enter_context(patch.object(run_agent,name,value))
            patches.enter_context(patch.object(run_agent.threading,"Event",Stop))
            patches.enter_context(patch.object(run_agent.signal,"signal"))
            self.assertEqual(run_agent.main(),0)
            self.assertFalse((root/"data/agent.pid").exists())
        self.assertEqual(attempts,["fixture-session","fixture-session"])
        self.assertEqual(transitions,["QUEUED","WAITING_SOURCE","QUEUED","TRAINING_BLOCKED"])
        self.assertEqual(state["desired"],"running")
        memory.close.assert_called_once()
