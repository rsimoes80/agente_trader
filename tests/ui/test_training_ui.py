"""Training UI contract tests. Every endpoint intercepted; no real commands."""
import os,unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[2]

@unittest.skipUnless(os.environ.get('AURELIA_TEST_BROWSER')=='1','Browser opt-in')
class TrainingBrowserTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start();self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
        self.addCleanup(self.browser.close);self.page=self.browser.new_page()
        self.addCleanup(self.page.unroute_all,behavior='ignoreErrors')
        self.errors=[];self.commands=[];self.offline=False
        self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.state=dict(status='NOT_STARTED',stage='dataset',message='Pronto',live_model_changed=False)
        self.page.route('**/*',self.route)

    def route(self,route):
        path=urlparse(route.request.url).path
        if path=='/api/diagnostics/training':
            if self.offline:route.fulfill(status=503,json=dict(ok=False));return
            route.fulfill(json=dict(ok=True,csrf='fixture',state=self.state))
        elif path=='/api/diagnostics/training/command':
            self.commands.append(route.request.post_data_json)
            self.assertEqual(route.request.headers['x-diagnostics-csrf'],'fixture')
            self.assertTrue(route.request.headers['idempotency-key'])
            self.state.update(status='QUEUED',stage='dataset',message='Na fila')
            route.fulfill(json=dict(ok=True,state=self.state))
        elif path in ('/treinamento','/operation.css','/training.css','/training.js'):
            filename='training.html' if path=='/treinamento' else path[1:]
            mime={'.html':'text/html','.css':'text/css','.js':'application/javascript'}[Path(filename).suffix]
            route.fulfill(body=(ROOT/'static'/filename).read_text(encoding='utf-8'),content_type=mime)
        else:
            if path.startswith('/api/'):self.fail('Unexpected API call '+path)
            route.fulfill(status=404,body='fixture')

    def test_start_queues_only_training_without_credentials(self):
        self.page.goto('http://127.0.0.1:37771/treinamento')
        self.page.locator('#start:not([disabled])').wait_for()
        self.assertEqual(self.page.locator('input[type=password]').count(),0)
        self.page.locator('#start').click()
        self.page.wait_for_function("document.querySelector('#status').textContent==='Na fila do computador Windows'")
        self.assertEqual(self.commands,[{'action':'START'}]);self.assertTrue(self.page.locator('#start').is_disabled())
        self.assertEqual(self.errors,[])

    def test_rejection_explains_decision_and_mobile_layout_fits(self):
        self.state.update(status='NOT_APPROVED',stage='decision',decision=dict(approved=False,reasons=['PINBALL_IMPROVEMENT_BELOW_2_PERCENT','FINANCIAL_SAMPLE_INSUFFICIENT']))
        self.page.set_viewport_size(dict(width=390,height=844))
        self.page.goto('http://127.0.0.1:37771/treinamento')
        self.page.locator('#decision').filter(has_text='Modelo atual mantido').wait_for()
        self.assertIn('2%',self.page.locator('#reasons').inner_text())
        self.assertIn('20',self.page.locator('#reasons').inner_text())
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),391)
        self.assertEqual(self.errors,[])

    def test_api_failure_is_visible_and_not_empty_success(self):
        self.offline=True;self.page.goto('http://127.0.0.1:37771/treinamento')
        self.page.locator('#error:not([hidden])').wait_for()
        self.assertTrue(self.page.locator('#start').is_disabled())
        self.assertEqual(self.commands,[]);self.assertEqual(self.errors,[])
