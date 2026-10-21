"""Rollback-only synthetic approvals and paper ledger atomicity in isolated schemas."""

import copy
import json
import os
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

from aurelia_fx.agent_live import checkpoint, claim, commit, management_tick
from aurelia_fx.agent_model import PROTOCOL, fingerprint, fit_model
from aurelia_fx.agent_paper import PaperAccount
from aurelia_fx.agent_registry import approved_version
from aurelia_fx.agent_strategy import SPEC_HASH
from aurelia_fx.experience_memory import ExperienceMemory
from aurelia_fx.operation_control import OperationControl
from aurelia_fx.storage import database_url

from .test_agent_model import fixtures
from . import test_agent_paper as paper_fixtures


@unittest.skipUnless(
    os.environ.get("TIMESTRAL_TEST_POSTGRES") == "1", "PostgreSQL opt-in"
)
class AgentRegistryTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row

        self.c = psycopg.connect(database_url(), autocommit=True, row_factory=dict_row)
        self.addCleanup(self.c.close)
        self.c.execute("BEGIN")
        self.addCleanup(self.c.execute, "ROLLBACK")
        schema = "registry_test_" + uuid4().hex
        self.c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        self.c.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema))
        )
        self.c.execute("""CREATE TABLE project_records(record_type TEXT,record_key TEXT,
            payload_json TEXT,payload_sha256 TEXT,recorded_at TIMESTAMPTZ DEFAULT clock_timestamp())""")
        self.memory = SimpleNamespace(
            pool=SimpleNamespace(connection=lambda: nullcontext(self.c)),
            _encode=ExperienceMemory._encode,
        )
        self.control = OperationControl(self.memory)
        self.state = self.control.command(
            dict(action="START", lot="0.01"), uuid4().hex, actor="synthetic-test"
        )

    def record(self, kind, key, payload):
        text, digest = self.memory._encode(payload)
        self.c.execute(
            "INSERT INTO project_records(record_type,record_key,payload_json,payload_sha256) VALUES(%s,%s,%s,%s)",
            (kind, key, text, digest),
        )

    def validated_report(self):
        model = fit_model(fixtures())
        self.record("agent_model_candidate", model["model_id"], model)
        result = dict(
            closed_trades=30,
            net_pnl=100,
            expectancy=100 / 30,
            profit_factor=1.5,
            max_close_equity_drawdown_pct=1,
            censored_trades=0,
            unresolved_position=False,
        )
        report = dict(
            status="validated_pending_approval",
            spec_hash=SPEC_HASH,
            protocol=copy.deepcopy(PROTOCOL),
            final_accessed=True,
            threshold=0.55,
            walk_forward=[{}, {}],
            partitions=dict(development=200, validation=50, final=50),
            validation=dict(
                thresholds=[dict(threshold=0.55, result=result)],
                probability=dict(brier_improvement=0.1),
            ),
            final=dict(
                combined=result,
                technical=dict(net_pnl=50),
                timestral=dict(net_pnl=40),
                probability=dict(brier_improvement=0.1),
            ),
            training_period=dict(end=datetime.now(timezone.utc).isoformat()),
            candidate_version=model["model_id"],
            lot="0.01",
            clock_id="synthetic-clock",
            model_configuration="fixture-config",
        )
        report["report_id"] = fingerprint(report)
        self.record("agent_training_report", report["report_id"], report)
        self.control.publish(
            self.state["session_id"],
            state="AWAITING_APPROVAL",
            history=dict(clock_id="synthetic-clock"),
            training=report,
        )
        return report

    def test_approval_is_explicit_idempotent_and_bound_to_exact_model(self):
        report = self.validated_report()
        self.assertIsNone(
            approved_version(
                self.memory,
                lot="0.01",
                clock_id="synthetic-clock",
                configuration="fixture-config",
            )
        )
        request = dict(action="APPROVE", report_id=report["report_id"])
        key = uuid4().hex
        result = self.control.command(request, key, actor="synthetic-test")
        self.assertEqual(result["state"], "QUEUED")
        self.assertEqual(
            result, self.control.command(request, key, actor="synthetic-test")
        )
        loaded = approved_version(
            self.memory,
            lot="0.01",
            clock_id="synthetic-clock",
            configuration="fixture-config",
        )
        self.assertEqual(loaded["model"]["model_id"], report["candidate_version"])
        self.assertIsNone(
            approved_version(
                self.memory,
                lot="0.02",
                clock_id="synthetic-clock",
                configuration="fixture-config",
            )
        )

    def test_rejected_or_mismatched_report_cannot_be_approved(self):
        self.validated_report()
        with self.assertRaises(ValueError):
            self.control.command(
                dict(action="APPROVE", report_id="wrong"),
                uuid4().hex,
                actor="synthetic-test",
            )

    def test_previous_report_must_belong_to_a_run_of_the_current_session(self):
        report = dict(run_id="fixture-run",report_id="fixture-report",lot="0.01")
        self.record("agent_training_report","fixture-report",report)
        self.assertIsNone(self.control.latest_training_report(self.control.status()))
        self.control.publish(self.state["session_id"],training=dict(run_id="fixture-run"))
        self.record("agent_training_report","unrelated-report",dict(run_id="other-run",lot="0.01"))
        self.assertEqual(self.control.latest_training_report(self.control.status()),report)

    def test_autonomous_seed_excludes_validation_and_final_labels(self):
        from aurelia_fx.autonomous_lab import AutonomousLab
        from aurelia_fx.agent_strategy import SPEC
        now=datetime.now(timezone.utc)
        features=dict(h1_direction_known=1,forecast_3_atr=0.2,forecast_6_atr=0.1)
        ids=[]
        for label,exit_at in (("development",now-timedelta(days=3)),("validation",now-timedelta(hours=12))):
            ids.append(label)
            self.record("agent_training_sample",label,dict(sample_id=label,features=features,
                snapshot=dict(regime="TRANSITION",session=["london"]),exit_at=exit_at.isoformat(),
                net_pnl=5,result_in_r=2))
        manifest=dict(strategy=SPEC,model_configuration="fixture",clock_id="clock",
                      as_of=(now-timedelta(hours=1)).isoformat(),training_days=335,
                      boundaries=[(now-timedelta(days=1)).isoformat()])
        self.record("agent_training_dataset","run",dict(run_id="run",manifest=manifest,sample_ids=ids))
        lab=AutonomousLab("fixture")
        seed=lab.seed(self.memory,clock_id="clock",configuration="fixture",as_of=now)
        self.assertEqual(seed["historical_samples"],1)
        self.assertEqual(seed["seed_scope"],"development_only_overlapping_counterfactuals")
        self.assertEqual(lab.seed(self.memory,clock_id="other",configuration="fixture",as_of=now)["historical_samples"],0)

    def test_paper_state_checkpoint_and_events_commit_together_and_owner_is_fenced(
        self,
    ):
        account = PaperAccount(
            self.state["session_id"],
            "0.01",
            dict(contract_size=100000, currency_profit="USD"),
            "fixture-model",
            "clock",
        )
        account.event("fixture", datetime.now(timezone.utc).isoformat())
        self.assertFalse(commit(self.control, account, "unclaimed"))
        self.assertIsNone(checkpoint(self.control, self.state["session_id"]))
        claim(self.control, self.state["session_id"], "worker")
        self.assertTrue(commit(self.control, account, "worker"))
        self.assertEqual(
            checkpoint(self.control, self.state["session_id"])["balance"], 10000
        )
        self.assertEqual(
            self.c.execute(
                "SELECT count(*) AS n FROM project_records WHERE record_type='agent_paper_event'"
            ).fetchone()["n"],
            1,
        )
        self.assertEqual(account.events, [])
        stored = self.c.execute(
            "SELECT payload_json FROM project_records WHERE record_type='agent_paper_account'"
        ).fetchone()
        self.assertEqual(
            json.loads(stored["payload_json"])["session_id"], self.state["session_id"]
        )

    def open_fixture(self):
        fixture = paper_fixtures.PaperAccountTests()
        fixture.setUp()
        contract = fixture.contract
        account = PaperAccount(self.state["session_id"], "0.01", contract,
                               "fixture-model", "clock")
        fixture.open(account)
        self.control.publish(self.state["session_id"], symbol_contract=contract)
        claim(self.control, self.state["session_id"], "worker")
        self.assertTrue(commit(self.control, account, "worker", generation=1))
        return fixture, account

    def test_restart_paused_keeps_position_and_source_failure_does_not_erase_it(self):
        fixture, account = self.open_fixture()
        self.control.command(dict(action="PAUSE"), uuid4().hex, actor="fixture")
        with patch("aurelia_fx.agent_live.observed_quote", return_value=fixture.quote(10)):
            self.assertTrue(management_tick(self.control, lambda *a, **k: {},
                                           self.control.status(), "restarted-worker"))
        self.assertEqual(self.control.status()["state"], "PAUSED")
        self.assertIsNotNone(checkpoint(self.control, self.state["session_id"])["position"])
        def unavailable(*args, **kwargs):
            raise RuntimeError("fixture source offline")
        with self.assertRaises(RuntimeError):
            management_tick(self.control, unavailable, self.control.status(), "restarted-worker")
        self.assertIsNotNone(self.control.status()["position"])
        with self.assertRaises(ValueError):
            self.control.command(dict(action="START", lot="0.01"), uuid4().hex, actor="fixture")

    def test_stop_arriving_during_fetch_closes_at_new_observed_quote(self):
        fixture, account = self.open_fixture()
        before = self.control.status()
        def fetch(*args, **kwargs):
            self.control.command(dict(action="STOP"), uuid4().hex, actor="fixture")
            return {}
        with patch("aurelia_fx.agent_live.observed_quote", return_value=fixture.quote(10)):
            self.assertFalse(management_tick(self.control, fetch, before, "restarted-worker"))
        state = self.control.status()
        self.assertEqual(state["state"], "STOPPED")
        self.assertIsNone(state["position"])
        self.assertEqual(state["account"]["closed_trades"], 1)
        self.assertLess(state["account"]["balance"], 10000)

    def test_pause_fences_uncommitted_entry_but_not_existing_position_management(self):
        fixture = paper_fixtures.PaperAccountTests(); fixture.setUp()
        account = PaperAccount(self.state["session_id"], "0.01", fixture.contract,
                               "fixture-model", "clock")
        claim(self.control, self.state["session_id"], "worker")
        fixture.open(account)
        self.control.command(dict(action="PAUSE"), uuid4().hex, actor="fixture")
        self.assertFalse(commit(self.control, account, "worker", generation=1))
        self.assertIsNone(checkpoint(self.control, self.state["session_id"]))

    def test_single_user_http_commands_need_no_credential_but_require_csrf(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from http.cookiejar import CookieJar
        import diagnostic_server
        from aurelia_fx.operator_session import OperatorSessions

        class QuietHandler(diagnostic_server.Handler):
            def log_message(self, *args): pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        server.app = SimpleNamespace(operation=self.control, operator_token="fixture-access",
                                     operator_sessions=OperatorSessions("fixture-access"))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}/api/diagnostics/agent"
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        initial = json.load(client.open(base))
        self.assertTrue(initial["authenticated"])
        self.assertEqual(initial["access_mode"],"single_user")

        def post(path, payload, csrf=initial["csrf"]):
            req = urllib.request.Request(base+path, json.dumps(payload).encode(),
                    headers={"Content-Type":"application/json", "X-Diagnostics-CSRF":csrf,
                             "Origin":"http://127.0.0.1:8770", "Idempotency-Key":uuid4().hex})
            return json.load(client.open(req))

        with self.assertRaises(urllib.error.HTTPError) as csrf:
            post("/command", dict(action="PAUSE"), csrf="wrong")
        self.assertEqual(csrf.exception.code, 403)
        csrf.exception.close()
        self.assertEqual(post("/command", dict(action="PAUSE"))["state"]["desired"], "paused")
        self.assertTrue(json.load(client.open(base))["authenticated"])

    def test_paper_loop_opens_once_manages_and_persists_actual_observed_exit(self):
        self.check_loop()

    def test_autonomous_loop_executes_and_learns_without_validated_model(self):
        self.check_loop(research=True)

    def check_loop(self, research=False):
        from contextlib import ExitStack
        from aurelia_fx.agent_live import run_paper
        from aurelia_fx.domain import Candidate
        fixture = paper_fixtures.PaperAccountTests(); fixture.setUp()
        fixture.start = datetime.now(timezone.utc)-timedelta(seconds=10)
        fixture.setup.update(signal_at=fixture.start.isoformat(), candidate=Candidate(
            "long", 1.1, 1.098, 1.105, fixture.start+timedelta(minutes=5), ("fixture",)))
        fixture.setup["snapshot"]["regime"]="UNKNOWN"
        fixture.setup["production_eligible"]=not research
        self.control.publish(self.state["session_id"], symbol_contract=fixture.contract,history=dict(clock_id="clock"))
        state = self.control.status()
        candle_at = fixture.start-timedelta(minutes=5)
        row = dict(timestamp=candle_at.isoformat(), spread_pips=1)
        context = [SimpleNamespace(timestamp=candle_at, close=1.1)]
        session = SimpleNamespace(last=None, history=context,
            aggregator=SimpleNamespace(history={"D1":[]}),
            update=lambda *a, **k: SimpleNamespace(snapshot_id="fixture-snapshot"))
        repo = SimpleNamespace(candles=lambda **k: [], latest=lambda **k: {})
        version = dict(model=dict(model_id="fixture-model"), report=dict(threshold=0.55),
                       approval=dict(clock_id="clock",valid_until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
        config = SimpleNamespace(fingerprint="fixture-config")
        from aurelia_fx.autonomous_lab import AutonomousLab
        policy=AutonomousLab(config.fingerprint) if research else None

        class StopAfterTwoCycles:
            count = 0
            def is_set(self): return self.count >= 2
            def wait(self, *args): self.count += 1

        class Sessions:
            def __init__(self, *args): pass
            def identify(self, *args): return SimpleNamespace(active_sessions=("london",))

        quotes = [fixture.quote(10),fixture.quote(11),fixture.quote(15,bid=1.1051,ask=1.1052)]
        for quote in quotes:
            quote["at"] = quote["observed_at"]
        with ExitStack() as patches:
            patches.enter_context(patch.object(self.control, "heartbeat"))
            for name, value in {
                "intelligence_session":lambda:session, "readiness":lambda *a,**k:None,
                "closed_rows":lambda *a,**k:[row], "propose_pullback":lambda *a,**k:(fixture.setup,None),
                "prepare":lambda *a,**k:context, "cached_forecast":lambda *a:("cache",dict(quantiles=[[1.09,1.1,1.11]]*12)),
                "attach_forecast":lambda *a:dict(h1_direction_known=0,forecast_3_atr=0.1,forecast_6_atr=0.2), "predict":lambda *a:0.8, "SessionEngine":Sessions,
            }.items():
                patches.enter_context(patch("aurelia_fx.agent_live."+name, value))
            patches.enter_context(patch("aurelia_fx.agent_live.observed_quote", side_effect=quotes))
            adapter = patches.enter_context(patch("aurelia_fx.agent_live.TimestralAdapter"))
            run_paper(self.control, repo, state, None if research else version, lambda *a,**k:dict(candles=[row]),
                      config, "worker", StopAfterTwoCycles(), self.c,research_policy=policy)
            adapter.return_value.close.assert_called_once()
        stored = checkpoint(self.control,self.state["session_id"])
        self.assertIsNone(stored["position"])
        self.assertEqual(stored["daily_entries"], 1)
        self.assertEqual(stored["closed_trades"], 1)
        self.assertAlmostEqual(stored["balance"], 10004.89)
        events = self.c.execute("SELECT payload_json FROM project_records WHERE record_type='agent_paper_event'").fetchall()
        self.assertEqual(sorted(json.loads(e["payload_json"])["status"] for e in events),["closed","decision","opened"])
        if research:
            self.assertEqual(sum(r["wins"] for r in self.control.status()["autonomy"]["hypotheses"]),1)
            self.assertTrue(stored["research_mode"])
