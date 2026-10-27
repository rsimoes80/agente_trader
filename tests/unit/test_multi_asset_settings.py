import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from aurelia_fx.multi_asset_settings import load_settings


class MultiAssetSettingsTests(unittest.TestCase):
    def test_missing_file_preserves_legacy_and_example_enables_coordinator(self):
        with TemporaryDirectory() as d:
            self.assertFalse(load_settings(d,environ={})['enabled'])
            (Path(d)/'data').mkdir()
            (Path(d)/'data/multi_asset.json').write_text(json.dumps(dict(schema_version=1,enabled=True,max_workers=2)))
            self.assertEqual(load_settings(d,environ={})['max_workers'],2)
            self.assertTrue(load_settings(d,environ={})['enabled'])
            self.assertFalse(load_settings(d,environ={'AGENTE_TRADER_MULTI_ASSET':'0'})['enabled'])

    def test_invalid_settings_never_silently_fall_back_to_other_execution_mode(self):
        for value in ({'enabled':'true'},{'max_workers':0},{'max_workers':True},{'schema_version':2}):
            with TemporaryDirectory() as d:
                (Path(d)/'data').mkdir();(Path(d)/'data/multi_asset.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):load_settings(d,environ={})
