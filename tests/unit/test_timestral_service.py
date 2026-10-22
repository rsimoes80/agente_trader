import io
import json
import sys
import unittest
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aurelia_fx.forecasting.adapter import ModelUnavailable, TimestralAdapter
from aurelia_fx.forecasting.config import TimestralConfig
from aurelia_fx.forecasting.service import ForecastService

from .test_timestral_core import bars, output


class TimestralServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = TimestralConfig(enabled=True)
        self.repo = MagicMock()
        self.repo.evaluate_available.return_value = 0
        self.repo.has_batch.return_value = False
        self.engine = MagicMock()
        self.engine.forecast.return_value = output()
        self.rows = bars()
        self.now = self.rows[-1].timestamp + timedelta(minutes=5)

    def observe(self, config=None):
        return ForecastService(config or self.config, self.repo, self.engine).observe(
            self.rows, as_of=self.now, scope="live", source_id="test"
        )

    def test_disabled_does_not_touch_database_or_model(self):
        self.assertEqual(
            self.observe(replace(self.config, enabled=False))["status"], "disabled"
        )
        self.assertEqual(self.repo.mock_calls, [])
        self.assertEqual(self.engine.mock_calls, [])

    def test_success_issues_three_and_duplicate_skips_inference(self):
        self.assertEqual(len(self.observe()["predictions"]), 3)
        self.repo.has_batch.return_value = True
        self.assertEqual(self.observe()["predictions"], [])
        self.assertEqual(self.engine.forecast.call_count, 1)

    def test_model_or_database_failure_returns_status_and_no_decision(self):
        self.engine.forecast.side_effect = ModelUnavailable("test-model-failure")
        self.assertEqual(self.observe()["status"], "unavailable")
        self.repo.save.assert_not_called()
        self.engine.forecast.side_effect = None
        self.repo.save.side_effect = RuntimeError("test-database-failure")
        self.assertEqual(self.observe()["status"], "unavailable")

    def test_model_timeout_kills_only_isolated_process(self):
        adapter = TimestralAdapter(self.config)
        process = MagicMock()
        process.pid = 123
        process.poll.return_value = None
        adapter.process = process
        with patch(
            "psutil.Process",
            return_value=SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=100),children=lambda **kw:[],is_running=lambda:True),
        ):
            with self.assertRaisesRegex(ModelUnavailable, "Timeout"):
                adapter._wait(0.02)
        process.kill.assert_called_once()
        self.assertIsNone(adapter.process)

    def test_memory_limit_kills_isolated_process(self):
        adapter = TimestralAdapter(self.config)
        process = MagicMock()
        process.pid = 123
        process.poll.return_value = None
        adapter.process = process
        with patch(
            "psutil.Process",
            return_value=SimpleNamespace(
                memory_info=lambda: SimpleNamespace(rss=10**12),children=lambda **kw:[],is_running=lambda:True
            ),
        ):
            with self.assertRaisesRegex(ModelUnavailable, "memória"):
                adapter._wait(0.02)
        process.kill.assert_called_once()

    def test_persistent_engine_loaded_once_and_start_failure_handled(self):
        process = MagicMock()
        process.pid = 123
        process.poll.return_value = None
        process.stdin = io.StringIO()
        process.stderr = None
        process.stdout = io.StringIO(
            "\n".join(
                json.dumps(v)
                for v in [
                    {"ready": True},
                    {"ok": True, **output()},
                    {"ok": True, **output()},
                ]
            )
            + "\n"
        )
        adapter = TimestralAdapter(replace(self.config, python=sys.executable))
        with (
            patch("subprocess.Popen", return_value=process) as start,
            patch(
                "psutil.Process",
                return_value=SimpleNamespace(
                    memory_info=lambda: SimpleNamespace(rss=100),children=lambda **kw:[],is_running=lambda:True,create_time=lambda:1.
                ),
            ),
        ):
            try:
                adapter.forecast([1.1] * 64)
                adapter.forecast([1.1] * 64)
                self.assertEqual(start.call_count, 1)
            finally:
                adapter.close()
        bad = TimestralAdapter(replace(self.config, python=sys.executable))
        with patch("subprocess.Popen", side_effect=OSError("test-load-failure")):
            with self.assertRaises(ModelUnavailable):
                bad.forecast([1.1] * 64)
