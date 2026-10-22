import os
import unittest
from unittest.mock import Mock,patch


@unittest.skipUnless(os.environ.get('AURELIA_TEST_TRAINING')=='1','Isolated training environment opt-in')
class TrainingRunnerTests(unittest.TestCase):
    def test_shutdown_includes_windows_launcher_descendants(self):
        from run_training_proof import stop_owned
        child=Mock(pid=123);child.poll.return_value=None
        root=Mock();root.create_time.return_value=100
        descendant=Mock();root.children.return_value=[descendant]
        with patch('psutil.Process',return_value=root):stop_owned(child,100)
        descendant.kill.assert_called_once();root.kill.assert_called_once()
        child.wait.assert_called_once_with(timeout=15)

    def test_shutdown_does_not_kill_reused_pid(self):
        from run_training_proof import stop_owned
        child=Mock(pid=123);child.poll.return_value=None
        root=Mock();root.create_time.return_value=200
        with patch('psutil.Process',return_value=root),self.assertRaises(RuntimeError):stop_owned(child,100)
        root.kill.assert_not_called()
