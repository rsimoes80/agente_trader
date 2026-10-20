import copy
import json
import threading
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import URLError

from aurelia_fx.diagnostic_observer import DiagnosticObserver
from aurelia_fx.source_clock import SourceClockUnavailable, validate_source_clock

NOW = datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc)


def payload(now=NOW, clock_id="source:broker_wall"):
    end = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
    rows = []
    for i in range(145):
        stamp = end - timedelta(minutes=5 * (144 - i))
        price = 1.1 + (0.0001 if i % 2 else 0)
        rows.append(
            {
                "timestamp": stamp.isoformat(),
                "open": price,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price,
                "volume": 10,
                "spread_pips": 1,
                "source_time_epoch": int(stamp.timestamp()) + 10800,
            }
        )
    return {
        "ok": True,
        "timeframe": "M5",
        "timestamp_semantics": "utc_v1",
        "candles": rows,
        "pip_size": 0.0001,
        "quote": {"bid": 1.1, "ask": 1.1001, "time": now.isoformat()},
        "source_clock": {
            "contract": "mt5-utc-v1",
            "clock_id": clock_id,
            "normalized_to": "UTC",
            "mode": "broker_wall",
            "offset_seconds": 10800,
            "verified_current": True,
            "status": "verified",
            "response_at_utc": now.isoformat(),
            "tick_utc": now.isoformat(),
        },
    }


class Memory:
    def __init__(self):
        self.records = []
        self.snapshots = []
        self.decisions = []
        self.experiences = []
        self.artifacts = []

    def transaction(self):
        return nullcontext()

    def record_project_data(self, kind, key, data):
        self.records.append((kind, key, copy.deepcopy(data)))

    def record_snapshot(self, data, **_):
        self.snapshots.append(copy.deepcopy(data))

    def record_intelligence(self, *_):
        pass

    def record_decision(self, data, **_):
        self.decisions.append(data)

    def record_experience(self, data):
        self.experiences.append(data)

    def record_artifact(self, **data):
        self.artifacts.append(data)


class Repository:
    def __init__(self, memory):
        self.memory = memory

    def query(self, sql, args):
        if "diagnostic_observer_checkpoint" in sql:
            rows = [
                data
                for kind, _, data in self.memory.records
                if kind == "diagnostic_observer_checkpoint"
                and data.get("clock_id") == args[0]
            ]
            return [{"payload_json": json.dumps(rows[-1])}] if rows else []
        return (
            [{"artifact_id": args[0]}]
            if any(row["artifact_id"] == args[0] for row in self.memory.artifacts)
            else []
        )


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, *_):
        return json.dumps(self.data).encode()


class ObserverRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.memory = Memory()
        self.repo = Repository(self.memory)
        self.observer = DiagnosticObserver(
            self.memory, self.repo, "http://fake", threading.Event()
        )
        self.now = NOW
        clock = patch("aurelia_fx.diagnostic_observer.datetime", wraps=datetime)
        mocked = clock.start()
        mocked.now.side_effect = lambda *_: self.now
        self.addCleanup(clock.stop)

    def poll(self, data):
        with patch(
            "aurelia_fx.diagnostic_observer.urlopen", return_value=Response(data)
        ):
            self.observer.poll()

    def test_verified_utc_is_not_shifted_twice_and_checkpoint_has_source(self):
        data = payload()
        self.poll(data)
        self.assertEqual(len(self.memory.snapshots), 1)
        expected = data["candles"][-2]["timestamp"]
        self.assertEqual(self.observer.last_saved, expected)
        self.assertEqual(self.memory.decisions[0].data_timestamp.isoformat(), expected)
        self.assertEqual(self.memory.decisions[0].action.value, "NO_TRADE")
        self.assertEqual(
            self.memory.snapshots[0]["source_clock"]["offset_seconds"], 10800
        )
        checkpoint = [
            v
            for kind, _, v in self.memory.records
            if kind == "diagnostic_observer_checkpoint"
        ][-1]
        self.assertEqual(checkpoint["clock_id"], "source:broker_wall")

    def test_repeated_poll_and_restart_do_not_duplicate_observation(self):
        self.poll(payload())
        self.poll(payload())
        self.assertEqual(len(self.memory.decisions), 1)
        self.observer = DiagnosticObserver(
            self.memory, self.repo, "http://fake", threading.Event()
        )
        self.poll(payload())
        self.assertEqual(len(self.memory.decisions), 1)
        self.now += timedelta(minutes=5)
        self.poll(payload(self.now))
        self.assertEqual(len(self.memory.decisions), 2)

    def test_terminal_unavailable_then_open_recovers_without_process_restart(self):
        with patch(
            "aurelia_fx.diagnostic_observer.urlopen",
            side_effect=URLError("MT5 stopped"),
        ):
            with self.assertRaises(URLError):
                self.observer.poll()
        self.poll(payload())
        self.assertEqual(self.observer.status()["status"], "observing")
        self.assertEqual(len(self.memory.decisions), 1)

    def test_missing_contract_and_future_data_never_write(self):
        for missing in [True, False]:
            data = payload()
            if missing:
                data.pop("source_clock")
            else:
                data["candles"][-1]["timestamp"] = (
                    NOW + timedelta(hours=3)
                ).isoformat()
            with self.assertRaises(SourceClockUnavailable):
                self.poll(data)
        self.assertFalse(self.memory.decisions)

    def test_cached_stale_quote_waits_until_fresh_quote_returns(self):
        data = payload()
        data["source_clock"]["verified_current"] = False
        with self.assertRaises(SourceClockUnavailable):
            self.poll(data)
        self.assertFalse(self.memory.snapshots)
        self.poll(payload())
        self.assertEqual(len(self.memory.snapshots), 1)

    def test_different_source_never_reuses_checkpoint_or_modifies_old_records(self):
        self.poll(payload())
        old = copy.deepcopy(self.memory.snapshots[0])
        old_run = self.observer.run_id
        self.poll(payload(clock_id="different-server:utc"))
        self.assertNotEqual(old_run, self.observer.run_id)
        self.assertEqual(len(self.memory.snapshots), 2)
        self.assertEqual(old, self.memory.snapshots[0])

    def test_unknown_commit_reloads_persistent_checkpoint_on_reconnect(self):
        self.poll(payload())
        self.observer.last_saved = None
        self.observer.require_checkpoint_reload = True
        self.poll(payload())
        self.assertEqual(len(self.memory.decisions), 1)

    def test_host_clock_mismatch_is_not_misclassified_as_broker_timezone(self):
        data = payload()
        data["source_clock"]["response_at_utc"] = (
            NOW - timedelta(minutes=2)
        ).isoformat()
        with self.assertRaises(SourceClockUnavailable) as context:
            self.poll(data)
        self.assertEqual(context.exception.status, "host_clock_mismatch")
        self.assertFalse(self.memory.records)

    def test_metadata_must_contain_aware_timestamps(self):
        data = payload()
        data["source_clock"]["tick_utc"] = "2026-10-20T12:02:00"
        with self.assertRaises(SourceClockUnavailable):
            validate_source_clock(data, NOW)
