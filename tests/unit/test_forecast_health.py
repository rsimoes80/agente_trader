import copy
import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aurelia_fx.forecasting.adapter import ModelUnavailable, TimestralAdapter
from aurelia_fx.forecasting.config import TimestralConfig
from aurelia_fx.forecasting.health import ForecastProbe, failure, success, forecast_or_wait, consume_probe
from aurelia_fx.learning_evolution import collection_health


class ForecastHealthTests(unittest.TestCase):
    def test_engine_success_recovers_current_failure_without_erasing_history(self):
        state={};other={}
        failure(state,ModelUnavailable('Memória insuficiente',code='WAITING_RESOURCES',phase='LOADING_WEIGHTS'),configuration='euro')
        previous=copy.deepcopy(state['forecast_health']['last_failure'])
        success(state,{},configuration='euro',source='cache')
        self.assertEqual(state['forecast_health']['status'],'CACHE_ONLY')
        self.assertEqual(state['forecast_health']['current_failure'],previous)
        success(other,{'model':'gold'},configuration='gold',source='healthcheck')
        self.assertEqual(state['forecast_health']['status'],'CACHE_ONLY')
        success(state,{'model':'euro'},configuration='euro',source='healthcheck')
        h=state['forecast_health']
        self.assertEqual(h['status'],'AVAILABLE');self.assertIsNone(h['current_failure'])
        self.assertEqual(h['last_failure'],previous);self.assertEqual(h['failure_count'],1)

    def test_arbitrary_exception_text_is_not_exposed(self):
        record=failure({},RuntimeError('postgresql://secret:password@host/db'),configuration='a')
        self.assertNotIn('password',str(record));self.assertEqual(record['code'],'RuntimeError')

    def test_failure_becomes_wait_without_fabricating_a_forecast(self):
        decision={'action':'WAIT'}
        def call(context):raise ModelUnavailable('Timeout',code='LOAD_TIMEOUT',phase='IMPORTING_TORCH')
        self.assertIsNone(forecast_or_wait(call,[1.],decision))
        self.assertEqual(decision['action'],'WAIT')
        self.assertEqual(decision['reason'],'TIMESTRAL_UNAVAILABLE')
        self.assertEqual(decision['forecast_error']['code'],'LOAD_TIMEOUT')

    def test_probe_is_nonblocking_and_preserves_the_frozen_input(self):
        gate=threading.Event();entered=threading.Event();seen=[]
        def operation(values):
            entered.set();gate.wait(2);seen.extend(values)
            return {'quantiles':[[1.,2.,3.]]*12}
        probe=ForecastProbe(operation);values=[1.,2.]
        try:
            self.assertTrue(probe.request(values,configuration='a',signal_at='now'))
            self.assertTrue(entered.wait(1));values.append(4.)
            self.assertFalse(probe.request(values,configuration='a',signal_at='now'))
            self.assertIsNone(probe.poll())
        finally:gate.set();probe.thread.join(3);probe.close()
        result=probe.poll();self.assertIsNone(result['error']);self.assertEqual(seen,[1.,2.])
        self.assertFalse(probe.request(values,configuration='a',signal_at='now'))

    def test_probe_rejects_invalid_quantiles_and_retries_after_failure(self):
        now=[0.]
        probe=ForecastProbe(lambda values:{'quantiles':[[1.,float('nan'),3.]]*12},clock=lambda:now[0])
        self.assertTrue(probe.request([1.],configuration='a',signal_at='now'))
        probe.thread.join(2);result=probe.poll()
        self.assertIsInstance(result['error'],ValueError)
        now[0]=59.;self.assertFalse(probe.request([1.],configuration='a',signal_at='now'))
        now[0]=61.;self.assertTrue(probe.request([1.],configuration='a',signal_at='now'))
        probe.thread.join(2);probe.close()

    def test_resource_failure_has_measured_details(self):
        a=TimestralAdapter(TimestralConfig(enabled=True));p=MagicMock();p.pid=123;p.poll.return_value=None
        a.process=p;a.phase='IMPORTING_TORCH'
        process=SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=20*1024**2),
            children=lambda **kwargs:[],is_running=lambda:True)
        with patch('psutil.Process',return_value=process),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=64*1024**2)):
            with self.assertRaises(ModelUnavailable) as caught:a._wait(.1)
        e=caught.exception
        self.assertEqual(e.code,'WAITING_RESOURCES');self.assertEqual(e.phase,'IMPORTING_TORCH')
        self.assertEqual(e.details['available_mb'],64);p.kill.assert_called_once()

    def test_cooldown_prevents_launch_storm_without_extending_the_retry(self):
        a=TimestralAdapter(TimestralConfig(enabled=True))
        with patch('aurelia_fx.forecasting.adapter.time.monotonic',return_value=100),patch.object(a,'_start',side_effect=ModelUnavailable('Timeout',code='LOAD_TIMEOUT')):
            with self.assertRaises(ModelUnavailable):a.forecast([1.]*64)
        self.assertEqual(a.retry_at,130)
        with patch('aurelia_fx.forecasting.adapter.time.monotonic',return_value=110),patch('subprocess.Popen') as launch:
            with self.assertRaises(ModelUnavailable) as caught:a.forecast([1.]*64)
        launch.assert_not_called();self.assertEqual(a.retry_at,130)
        self.assertTrue(caught.exception.details['retry_pending'])

    def test_engine_progress_does_not_count_as_ready_or_a_prediction(self):
        a=TimestralAdapter(TimestralConfig(enabled=True));p=MagicMock();p.pid=123;a.process=p
        a.responses.put({'progress':True,'phase':'LOADING_WEIGHTS'})
        a.responses.put({'ready':True})
        process=SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=20),children=lambda **kwargs:[],is_running=lambda:True)
        with patch('psutil.Process',return_value=process),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2*1024**3)):
            self.assertEqual(a._wait(.1),{'ready':True})
        self.assertEqual(a.phase,'LOADING_WEIGHTS')

    def test_only_first_inference_uses_the_cold_loading_budget(self):
        a=TimestralAdapter(TimestralConfig(enabled=True));a.process=MagicMock()
        with patch.object(a,'_start'),patch.object(a,'_wait',return_value={'ok':True}) as wait:
            a.forecast([1.]*64);a.forecast([1.]*64)
        self.assertEqual([args.args[0] for args in wait.call_args_list],[180,45])

    def test_owner_consumes_only_results_for_the_current_configuration(self):
        state={};probe=MagicMock()
        result=dict(configuration='old',error=None,output={'model':'old'})
        probe.poll.return_value=result
        self.assertFalse(consume_probe(state,probe,configuration='current'));self.assertEqual(state,{})
        result.update(configuration='current',output={'model':'current'})
        self.assertTrue(consume_probe(state,probe,configuration='current'))
        self.assertEqual(state['forecast_health']['model'],'current')
        self.assertEqual(state['forecast_health']['status'],'AVAILABLE')

    def test_worker_starts_and_publishes_model_checks_during_warmup_without_orders(self):
        import ast
        from pathlib import Path
        tree=ast.parse((Path(__file__).resolve().parents[2]/'src/aurelia_fx/agent_live.py').read_text(encoding='utf8'))
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_paper')
        warmup=next(n for n in ast.walk(function) if isinstance(n,ast.For) and
            isinstance(n.iter,ast.Call) and isinstance(n.iter.func,ast.Name) and n.iter.func.id=='enumerate')
        calls=[n for n in ast.walk(function) if isinstance(n,ast.Call)]
        first=min(n.lineno for n in calls if isinstance(n.func,ast.Name) and n.func.id=='request_probe')
        self.assertLess(first,warmup.lineno)
        warm_calls=[n for n in ast.walk(warmup) if isinstance(n,ast.Call)]
        self.assertTrue(any(isinstance(n.func,ast.Attribute) and n.func.attr=='consume_probe' for n in warm_calls))
        self.assertTrue(any(isinstance(n,ast.keyword) and n.arg=='autonomy' for n in ast.walk(warmup)))
        self.assertFalse(any(isinstance(n.func,ast.Attribute) and n.func.attr=='open' and
            isinstance(n.func.value,ast.Name) and n.func.value.id=='account' for n in warm_calls))

    def test_historical_errors_do_not_remain_an_active_alert_after_recovery(self):
        now=datetime(2026,10,27,15,tzinfo=timezone.utc)
        state=dict(desired='running',state='ANALYSIS_WARMUP',autonomy={'continual':{
            'forecast_health':{'status':'AVAILABLE'},'exploratory':{'forecast_errors':12}}})
        self.assertEqual(collection_health(state,{'available':True},now)['alerts'],[])
        state['autonomy']['continual']['forecast_health']={}
        alerts=collection_health(state,{'available':True},now)['alerts']
        self.assertIn('históricas',alerts[0]);self.assertIn('12',alerts[0])

    def test_low_memory_is_detected_before_starting_an_engine(self):
        import sys
        a=TimestralAdapter(TimestralConfig(enabled=True,python=sys.executable))
        with patch('psutil.virtual_memory',return_value=SimpleNamespace(available=9*1024**2)),patch('subprocess.Popen') as launch:
            with self.assertRaises(ModelUnavailable) as caught:a.forecast([1.]*64)
        self.assertEqual(caught.exception.code,'WAITING_RESOURCES')
        self.assertEqual(caught.exception.phase,'MEMORY_ADMISSION');launch.assert_not_called()

    def test_loading_progress_extends_inactivity_budget_but_remains_bounded(self):
        now=[0.];a=TimestralAdapter(TimestralConfig(enabled=True));a.process=MagicMock();a.process.pid=123
        responses=iter([{'progress':True,'phase':'IMPORTING_TORCH'},
            {'progress':True,'phase':'VERIFYING_ARTIFACT','bytes_read':16,'total_bytes':32},
            {'progress':True,'phase':'VERIFYING_ARTIFACT','bytes_read':32,'total_bytes':32}, {'ready':True}])
        def get(**kwargs):now[0]+=.015;return next(responses)
        a.responses=SimpleNamespace(get=get)
        process=SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=20),children=lambda **kwargs:[],is_running=lambda:True)
        with patch('aurelia_fx.forecasting.adapter.time.monotonic',side_effect=lambda:now[0]),patch('psutil.Process',return_value=process),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2*1024**3)):
            self.assertEqual(a._wait(.02,startup=True),{'ready':True})
        self.assertGreater(now[0],.02);self.assertEqual(a.progress['bytes_read'],32)

    def test_repeated_progress_cannot_keep_loading_alive_forever(self):
        for advancing in (False,True):
            now=[0.];a=TimestralAdapter(TimestralConfig(enabled=True));a.process=MagicMock();a.process.pid=123
            def get(**kwargs):
                now[0]+=.015
                return dict(progress=True,phase='VERIFYING_ARTIFACT',bytes_read=int(now[0]*1000) if advancing else 1,total_bytes=100000)
            a.responses=SimpleNamespace(get=get)
            process=SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=20),children=lambda **kwargs:[],is_running=lambda:True)
            with patch('aurelia_fx.forecasting.adapter.time.monotonic',side_effect=lambda:now[0]),patch('psutil.Process',return_value=process),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=2*1024**3)),patch.object(a,'close'):
                with self.assertRaises(ModelUnavailable) as caught:a._wait(.02,startup=True)
            self.assertEqual(caught.exception.code,'LOAD_TIMEOUT');self.assertLess(now[0],.12)
            if not advancing:self.assertLess(now[0],.08)

    def test_full_checksum_reports_progress_and_rejects_a_changed_file(self):
        import hashlib,tempfile
        from pathlib import Path
        from aurelia_fx.forecasting.loading import artifact_sha256
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'weights';data=bytes(range(256))*163;path.write_bytes(data);events=[]
            result=artifact_sha256(path,lambda n,total:events.append((n,total)),block_size=1024,progress_bytes=4000)
            self.assertEqual(result,hashlib.sha256(data).hexdigest())
            self.assertEqual(events[-1],(len(data),len(data)))
            self.assertTrue(all(a[0]<b[0] for a,b in zip(events,events[1:])))
            changed=[]
            def mutate(n,total):
                if not changed:
                    changed.append(True)
                    with path.open('ab') as out:out.write(b'x')
            with self.assertRaisesRegex(ValueError,'ARTIFACT_CHANGED'):
                artifact_sha256(path,mutate,block_size=1024,progress_bytes=4000)

    def test_progress_is_telemetry_and_never_means_a_successful_prediction(self):
        probe=MagicMock();probe.poll.return_value=None;probe.busy=True
        probe.progress={'phase':'VERIFYING_ARTIFACT','bytes_read':16,'total_bytes':32};state={}
        self.assertFalse(consume_probe(state,probe,configuration='a'))
        self.assertEqual(state['forecast_health']['progress']['bytes_read'],16)
        self.assertNotEqual(state['forecast_health'].get('status'),'AVAILABLE')


if __name__=='__main__':unittest.main()
