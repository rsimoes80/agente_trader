import io
import unittest
import subprocess
import sys
import time
import socket
from types import SimpleNamespace
from unittest.mock import Mock

from run_agent_supervisor import ProgressClock,supervise_once,reap_verified_orphan,ROOT
from run_agent import recovery_changes,retry_due,autonomous_session
from datetime import datetime,timedelta,timezone


class SupervisorTests(unittest.TestCase):
    def test_orphan_recovery_requires_stale_receipt_and_exact_process_identity(self):
        heartbeat=dict(pid=123,host=socket.gethostname(),process_created_at=123.5)
        worker=Mock()
        worker.create_time.return_value=123.5
        worker.cwd.return_value=str(ROOT)
        worker.cmdline.return_value=[sys.executable,str(ROOT/'run_agent.py')]
        worker.children.return_value=[]
        factory=Mock(return_value=worker)
        self.assertFalse(reap_verified_orphan(heartbeat,599,600,process_factory=factory))
        factory.assert_not_called()
        self.assertFalse(reap_verified_orphan({**heartbeat,'host':'other-host'},700,600,process_factory=factory))
        self.assertFalse(reap_verified_orphan({**heartbeat,'process_created_at':124},700,600,process_factory=factory))
        worker.kill.assert_not_called()
        worker.cmdline.return_value=[sys.executable,'unrelated_project.py']
        self.assertFalse(reap_verified_orphan(heartbeat,700,600,process_factory=factory))
        worker.kill.assert_not_called()
        worker.cmdline.return_value=[sys.executable,str(ROOT/'run_agent.py')]
        self.assertTrue(reap_verified_orphan(heartbeat,700,600,process_factory=factory))
        worker.kill.assert_called_once()

    def test_real_unresponsive_fixture_process_is_terminated(self):
        created=[]
        def popen(_args,**kwargs):
            process=subprocess.Popen([sys.executable,'-u','-c','import time; time.sleep(30)'],**kwargs)
            created.append(process)
            return process
        try:
            self.assertEqual(supervise_once(limit=.2,popen=popen,sleep=lambda _:time.sleep(.05)),'stalled')
            self.assertIsNotNone(created[0].poll())
        finally:
            for process in created:
                if process.poll() is None:process.kill();process.wait(timeout=10)

    def test_progress_uses_monotonic_deadline_not_wall_clock_or_log_noise(self):
        now=[0.0];clock=ProgressClock(lambda:now[0])
        now[0]=599
        self.assertFalse(clock.stalled(600))
        self.assertFalse(clock.observe('ordinary log message'))
        now[0]=600
        self.assertTrue(clock.stalled(600))
        self.assertTrue(clock.observe('AFX_AGENT_PROGRESS:fixture'))
        self.assertFalse(clock.stalled(600))

    def test_stalled_child_is_recycled_without_changing_session_commands(self):
        now=[0.0]
        child=SimpleNamespace(stdout=io.StringIO(''),returncode=None,pid=123)
        child.poll=lambda:child.returncode
        popen=Mock(return_value=child)
        def kill(process):
            self.assertIs(process,child);child.returncode=-1
        self.assertEqual(supervise_once(limit=4,popen=popen,
            clock_factory=lambda:ProgressClock(lambda:now[0]),
            sleep=lambda seconds:now.__setitem__(0,now[0]+seconds),kill=kill),'stalled')
        self.assertEqual(popen.call_args.kwargs['env']['AURELIA_AGENT_SUPERVISED'],'1')
        self.assertEqual(child.returncode,-1)

    def test_exited_child_returns_to_restart_loop(self):
        child=SimpleNamespace(stdout=io.StringIO(''),returncode=1,poll=lambda:1)
        kill=Mock()
        self.assertEqual(supervise_once(limit=4,popen=Mock(return_value=child),kill=kill),'exited')
        kill.assert_not_called()

    def test_recovery_preserves_intent_and_never_expires_the_session(self):
        now=datetime.now(timezone.utc)
        state=dict(session_id='fixture',mode='demo',desired='running',generation=4)
        self.assertTrue(autonomous_session(state))
        for _ in range(50):
            changes=recovery_changes(state,TimeoutError(),now=now)
            self.assertNotIn('session_id',changes)
            self.assertNotIn('desired',changes)
            self.assertNotIn('generation',changes)
            state.update(changes)
            self.assertTrue(retry_due(state,now+timedelta(minutes=6)))
        self.assertEqual(state['recovery_attempts'],50)
        self.assertEqual(state['session_id'],'fixture')
        self.assertEqual(state['desired'],'running')
        self.assertFalse(retry_due({**state,'desired':'paused'},now+timedelta(days=365)))
        self.assertFalse(retry_due({**state,'desired':'stopped'},now+timedelta(days=365)))
