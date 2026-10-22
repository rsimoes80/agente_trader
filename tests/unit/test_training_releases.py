import json,tempfile,unittest
from pathlib import Path
from aurelia_fx.training.proof import file_hash
from aurelia_fx.training.releases import activate,rollback,resolve,eligible
from aurelia_fx.forecasting.config import TimestralConfig

class TrainingReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run='fixture-release';self.folder=self.root/'data/training/runs'/self.run
        (self.folder/'candidate').mkdir(parents=True)
        (self.folder/'candidate/model.safetensors').write_bytes(b'unit-test-fixture-not-real-weights')
        self.digest=file_hash(self.folder/'candidate/model.safetensors')
        self.report=dict(source_model='mistralai/Timestral-5M',selection=dict(candidate_sha256=self.digest),partitions={p:dict(gate=dict(passed=True)) for p in ('validation','test')})
        self.financial=dict(gate=dict(passed=True))
        self.future=dict(gate=dict(passed=True),days=7,closed_trades_per_arm=[20,20],protocol_id='fixture-protocol',independent_future_data=True,candidate_sha256=self.digest)
        self.config=self.root/'data/timestral.json';self.original=dict(enabled=True,model='mistralai/Timestral-209M',revision='original-fixture')
        self.config.write_text(json.dumps(self.original))
        self.save()
    def save(self):
        for name,payload in (('forecast-report.json',self.report),('simulation-report.json',self.financial),('prospective-report.json',self.future)):
            (self.folder/name).write_text(json.dumps(payload))

    def test_activation_and_rollback_only_change_isolated_config(self):
        release=activate(self.root,self.run);current=json.loads(self.config.read_text())
        self.assertEqual(current['local_artifact_sha256'],self.digest)
        self.assertEqual(resolve(self.root,release,self.digest),(self.folder/'candidate').resolve())
        restored=rollback(self.root,self.run);self.assertEqual(restored,self.original)
        self.assertEqual(json.loads(self.config.read_text()),self.original)
        with self.assertRaises(ValueError):rollback(self.root,self.run)

    def test_failed_forecasts_or_missing_future_never_switch_model(self):
        self.report['partitions']['test']['gate']['passed']=False;self.save()
        before=self.config.read_bytes()
        with self.assertRaisesRegex(ValueError,'FORECAST_GATE_FAILED'):activate(self.root,self.run)
        self.assertEqual(before,self.config.read_bytes())
        self.report['partitions']['test']['gate']['passed']=True;self.save()
        (self.folder/'prospective-report.json').unlink()
        with self.assertRaisesRegex(ValueError,'PROSPECTIVE_EVIDENCE_REQUIRED'):activate(self.root,self.run)
        self.assertEqual(before,self.config.read_bytes())

    def test_tampered_evidence_and_weights_refused(self):
        release=activate(self.root,self.run)
        (self.folder/'candidate/model.safetensors').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'artifact changed'):resolve(self.root,release,self.digest)

    def test_repeated_activation_and_crash_recovery_preserve_original_backup(self):
        from unittest.mock import patch
        from aurelia_fx.training.releases import atomic_json
        def interrupted(path,value):
            if Path(path).resolve()==self.config.resolve():raise OSError('fixture interruption before config switch')
            atomic_json(path,value)
        with patch('aurelia_fx.training.releases.atomic_json',side_effect=interrupted),self.assertRaises(OSError):activate(self.root,self.run)
        self.assertEqual(json.loads(self.config.read_text()),self.original)
        release=activate(self.root,self.run)
        self.assertEqual(activate(self.root,self.run),release)
        self.assertEqual(rollback(self.root,self.run),self.original)

    def test_path_escape_and_candidate_mismatch_refused(self):
        with self.assertRaises(ValueError):activate(self.root,'../../foreign')
        self.future['candidate_sha256']='a'*64
        self.assertIn('PROSPECTIVE_CANDIDATE_MISMATCH',eligible(self.report,self.financial,self.future))

    def test_default_fingerprint_is_backward_compatible(self):
        import dataclasses,hashlib
        config=TimestralConfig();old=dataclasses.asdict(config)
        for key in ('python','cache_dir','enabled','timeout_seconds','load_timeout_seconds','memory_mb','local_release','local_artifact_sha256'):old.pop(key)
        expected=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()
        self.assertEqual(config.fingerprint,expected)
        with self.assertRaises(ValueError):TimestralConfig(local_release='unbound')
