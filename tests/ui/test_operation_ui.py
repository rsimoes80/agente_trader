"""Browser contract tests, intercepted API; no production commands or approvals."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("AURELIA_TEST_BROWSER") == "1", "Browser opt-in")
class OperationBrowserTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(
            executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
        self.addCleanup(self.browser.close)
        self.page = self.browser.new_page()
        self.addCleanup(self.page.unroute_all,behavior='ignoreErrors')
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.commands = []
        self.now = datetime.now(timezone.utc)
        self.clock = self.now.replace(second=0, microsecond=0) - timedelta(minutes=self.now.minute % 5)
        self.state = dict(state="STOPPED", desired="stopped", stage="connection", message="Escolha o lote e inicie.",
                          lot="0.01", updated_at=self.now.isoformat(), session_id="browser-fixture", training=None)
        self.authenticated = False
        self.last_report = None
        self.chart_online=True
        self.chart_hang=False
        self.held_routes=[]
        self.page.route("**/*", self.route)

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.startswith("/api/diagnostics/agent"):
            if path.endswith("/login"):
                self.authenticated = True
            elif path.endswith("/command"):
                self.commands.append(route.request.post_data_json)
                self.assertEqual(route.request.headers["x-diagnostics-csrf"], "browser-fixture-csrf")
                self.state.update(state="QUEUED", desired="running", lot=self.commands[-1].get("lot", "0.01"))
            route.fulfill(json=dict(ok=True, state=self.state, authenticated=self.authenticated,
                                    last_training_report=self.last_report,
                                    csrf="browser-fixture-csrf", worker=dict(available=True)))
        elif path == "/api/mt5/chart":
            if self.chart_hang:
                self.held_routes.append(route)
                return
            if not self.chart_online:
                route.fulfill(status=503,json=dict(ok=False,error='fixture bridge offline'))
                return
            rows = [dict(timestamp=(self.clock - timedelta(minutes=5*i)).isoformat(),
                         open=1.1, high=1.101, low=1.099, close=1.1005) for i in range(119, -1, -1)]
            route.fulfill(json=dict(ok=True, candles=rows, source_clock=dict(clock_id="browser-clock"),
                                    quote=dict(bid=1.1005, ask=1.1006, time=self.now.isoformat())))
        elif path in ("/", "/operation.css", "/operation.js"):
            filename = "operation.html" if path == "/" else path[1:]
            mime = {".html":"text/html", ".js":"application/javascript", ".css":"text/css"}[Path(filename).suffix]
            route.fulfill(body=(ROOT / "static" / filename).read_text(encoding="utf-8"), content_type=mime)
        else:
            route.fulfill(status=404, body="fixture")

    def test_start_needs_no_credential_and_uses_selected_lot(self):
        self.page.goto("http://127.0.0.1:37771/")
        self.page.locator("#state-title").filter(has_text="Agente parado").wait_for()
        self.page.locator("#lot").fill("0.02")
        self.assertEqual(self.page.locator("#access-form").count(),0)
        self.assertEqual(self.page.locator("#password").count(),0)
        self.page.locator("#start").click()
        self.page.wait_for_function("document.getElementById('state-title').textContent==='Início solicitado'")
        self.assertEqual(self.commands, [dict(action="START", mode="demo", lot="0.02")])
        self.assertTrue(self.page.locator("#lot").is_disabled())
        self.state.update(state="WAITING_SOURCE", desired="running", message="Aguardando MT5; nova tentativa automática.")
        self.page.wait_for_function("document.getElementById('state-title').textContent==='Aguardando conexão com o MT5'")
        self.assertTrue(self.page.locator("#pause").is_enabled())
        self.assertTrue(self.page.locator("#stop").is_enabled())
        self.assertEqual(self.errors, [])

    def test_chart_survives_bridge_failure_reload_and_recovers_automatically(self):
        self.page.goto('http://127.0.0.1:37771/')
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('Preço do MT5')")
        self.chart_online=False
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('reconectando')")
        self.assertIn('desatualizada',self.page.locator('#quote').inner_text())
        self.page.reload()
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('preservado')")
        self.assertTrue(self.page.evaluate("""() => {const c=document.getElementById('chart');const p=c.getContext('2d').getImageData(0,0,c.width,c.height).data;for(let i=0;i<p.length;i+=4){if(p[i]===73 && p[i+1]===214 && p[i+2]===164)return true;}return false;}"""))
        self.chart_online=True
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('Preço do MT5')")
        self.assertNotIn('desatualizada',self.page.locator('#quote').inner_text())
        self.assertEqual(self.errors,[])

    def test_chart_request_timeout_does_not_block_future_refresh(self):
        self.page.goto('http://127.0.0.1:37771/')
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('Preço do MT5')")
        self.page.evaluate("const normalTimeout=window.setTimeout.bind(window);window.setTimeout=(fn,delay,...args)=>normalTimeout(fn,delay===12000?150:delay,...args)")
        self.chart_hang=True
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('reconectando')")
        self.chart_hang=False
        for route in self.held_routes:route.abort()
        self.held_routes.clear()
        self.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        self.page.wait_for_function("document.getElementById('chart-message').textContent.includes('Preço do MT5')")
        self.assertEqual(self.errors,[])

    def test_mobile_forecast_expiry_source_identity_and_position_levels(self):
        self.page.set_viewport_size(dict(width=390, height=844))
        self.last_report=dict(report_id="fixture-report",samples=120,candidate_version="fixture-model",
                              training_period=dict(days=180),operational_validation_samples=0,
                              reason="INSUFFICIENT_OPERATIONAL_VALIDATION_SAMPLES")
        forecast=dict(symbol="EURUSD", timeframe="M5", clock_id="browser-clock", reference_at=self.clock.isoformat(),
                      valid_until=(self.clock+timedelta(minutes=5)).isoformat(), reference_price=1.1005,
                      points=[dict(at=(self.clock+timedelta(minutes=5*(i+1))).isoformat(),low=1.099,median=1.101,high=1.102) for i in range(12)])
        self.state.update(state="POSITION_OPEN", desired="running", stage="analysis", history=dict(clock_id="browser-clock",bars={},start=self.now.isoformat(),end=self.now.isoformat()),
                          position=dict(side="long",lot="0.01",entry=1.1005,stop=1.098,target=1.105,entry_at=self.now.isoformat()),
                          last_decision=dict(action="BUY", reason="fixture", at=self.now.isoformat(),candle=self.clock.isoformat(),forecast=forecast))
        self.page.goto("http://127.0.0.1:37771/")
        self.page.wait_for_function("document.getElementById('forecast-note').textContent.includes('estimativa avaliada')")
        self.assertIn("Compra", self.page.locator("#position").inner_text())
        self.assertIn("120 experiências encerradas",self.page.locator("#last-research").inner_text())
        self.assertIn("0 oportunidades",self.page.locator("#last-research").inner_text())
        self.assertFalse(self.page.evaluate("document.documentElement.scrollWidth > innerWidth"))
        self.page.evaluate("window.dispatchEvent(new Event('resize'))")
        forecast["clock_id"]="other-clock"
        self.page.set_viewport_size(dict(width=391,height=844))
        # Backend update is pulled by the normal five-second status poll.
        self.page.wait_for_function("document.getElementById('forecast-note').textContent.includes('outra fonte')")
        self.assertTrue(self.page.locator("#forecast-note").inner_text().startswith("A previsão"))
        forecast["clock_id"]="browser-clock"; forecast["valid_until"]=(self.now-timedelta(minutes=1)).isoformat()
        self.page.wait_for_timeout(5100)
        self.assertIn("antiga", self.page.locator("#forecast-note").inner_text())
        self.assertEqual(self.errors, [])

    def test_autonomous_cycle_shows_learning_without_login_or_manual_approval(self):
        self.state.update(state="ANALYZING",desired="running",execution_profile="autonomous_paper",
            training=dict(status="autonomous_research"),
            autonomy=dict(historical_samples=20,hypotheses=[dict(name="Hipótese de teste",n=1,wins=0,losses=1,net_pnl=-2)],
                          last_result=dict(net_pnl=-2)))
        self.page.goto("http://127.0.0.1:37771/")
        self.page.locator("#autonomous-learning").wait_for()
        self.assertIn("20",self.page.locator("#autonomy-info").inner_text())
        self.assertIn("Hipótese de teste",self.page.locator("#hypotheses-table").inner_text())
        self.assertIn("outra hipótese",self.page.locator("#last-learning").inner_text())
        self.assertFalse(self.page.locator("#approve").is_visible())
        self.assertEqual(self.page.locator("#password").count(),0)
        self.assertEqual(self.errors,[])
