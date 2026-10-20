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
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.commands = []
        self.now = datetime.now(timezone.utc)
        self.clock = self.now.replace(second=0, microsecond=0) - timedelta(minutes=self.now.minute % 5)
        self.state = dict(state="STOPPED", desired="stopped", stage="connection", message="Escolha o lote e inicie.",
                          lot="0.01", updated_at=self.now.isoformat(), session_id="browser-fixture", training=None)
        self.authenticated = False
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
                                    csrf="browser-fixture-csrf", worker=dict(available=True)))
        elif path == "/api/mt5/chart":
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

    def test_login_then_start_uses_selected_lot_and_backend_state(self):
        self.page.goto("http://127.0.0.1:37771/")
        self.page.locator("#state-title").filter(has_text="Agente parado").wait_for()
        self.page.locator("#lot").fill("0.02")
        self.page.locator("#start").click()
        self.assertTrue(self.page.locator("#access-form").is_visible())
        self.assertEqual(self.commands, [])
        self.page.locator("#password").fill("synthetic-fixture-only")
        self.page.locator("#access-form button").click()
        self.page.wait_for_function("document.getElementById('access-toggle').textContent==='Sair'")
        self.assertEqual(self.page.locator("#password").input_value(), "")
        self.page.locator("#start").click()
        self.page.wait_for_function("document.getElementById('state-title').textContent==='Início solicitado'")
        self.assertEqual(self.commands, [dict(action="START", mode="paper", lot="0.02")])
        self.assertTrue(self.page.locator("#lot").is_disabled())
        self.state.update(state="WAITING_SOURCE", desired="running", message="Aguardando MT5; nova tentativa automática.")
        self.page.wait_for_function("document.getElementById('state-title').textContent==='Aguardando conexão com o MT5'")
        self.assertTrue(self.page.locator("#pause").is_enabled())
        self.assertTrue(self.page.locator("#stop").is_enabled())
        self.assertEqual(self.errors, [])

    def test_mobile_forecast_expiry_source_identity_and_position_levels(self):
        self.page.set_viewport_size(dict(width=390, height=844))
        forecast=dict(symbol="EURUSD", timeframe="M5", clock_id="browser-clock", reference_at=self.clock.isoformat(),
                      valid_until=(self.clock+timedelta(minutes=5)).isoformat(), reference_price=1.1005,
                      points=[dict(at=(self.clock+timedelta(minutes=5*(i+1))).isoformat(),low=1.099,median=1.101,high=1.102) for i in range(12)])
        self.state.update(state="POSITION_OPEN", desired="running", stage="analysis", history=dict(clock_id="browser-clock",bars={},start=self.now.isoformat(),end=self.now.isoformat()),
                          position=dict(side="long",lot="0.01",entry=1.1005,stop=1.098,target=1.105,entry_at=self.now.isoformat()),
                          last_decision=dict(action="BUY", reason="fixture", at=self.now.isoformat(),candle=self.clock.isoformat(),forecast=forecast))
        self.page.goto("http://127.0.0.1:37771/")
        self.page.wait_for_function("document.getElementById('forecast-note').textContent.includes('estimativa avaliada')")
        self.assertIn("Compra", self.page.locator("#position").inner_text())
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
