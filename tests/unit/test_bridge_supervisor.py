import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from run_bridge_supervisor import supervise_once


class BridgeSupervisorTests(unittest.TestCase):
    def process(self):
        child=SimpleNamespace(pid=123,returncode=None)
        child.poll=lambda:child.returncode
        return child

    def test_stalled_bridge_restarts_after_deadline(self):
        now=[0];child=self.process();kill=Mock(side_effect=lambda _:setattr(child,'returncode',-1))
        self.assertEqual(supervise_once(probe=lambda:False,find=lambda:None,popen=Mock(return_value=child),
            now=lambda:now[0],sleep=lambda seconds:now.__setitem__(0,now[0]+seconds),kill=kill,limit=10),'stalled')
        kill.assert_called_once_with(child)

    def test_existing_bridge_is_adopted_without_spawning_duplicate(self):
        now=[0];child=self.process();spawn=Mock();kill=Mock()
        def sleep(seconds):
            now[0]+=seconds
            if now[0]>=20:child.returncode=0
        self.assertEqual(supervise_once(probe=lambda:True,find=lambda:child,popen=spawn,
            now=lambda:now[0],sleep=sleep,kill=kill,limit=10),'exited')
        spawn.assert_not_called();kill.assert_not_called()

    def test_unverified_healthy_listener_is_never_killed_or_duplicated(self):
        spawn=Mock();kill=Mock()
        self.assertEqual(supervise_once(probe=lambda:True,find=lambda:None,popen=spawn,kill=kill),'external_healthy')
        spawn.assert_not_called();kill.assert_not_called()

    def test_intermittent_health_failures_recover_without_restart(self):
        now=[0];child=self.process();kill=Mock()
        def sleep(seconds):
            now[0]+=seconds
            if now[0]>=30:child.returncode=0
        self.assertEqual(supervise_once(probe=lambda:now[0]%10==0,find=lambda:child,
            now=lambda:now[0],sleep=sleep,kill=kill,limit=15),'exited')
        kill.assert_not_called()
