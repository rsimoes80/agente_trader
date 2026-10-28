"""Fresh provisioning must share credentials and preserve existing installations."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from setup_environment import ROOT, configure


class FreshEnvironmentTests(unittest.TestCase):
    def test_two_hosts_and_overwrite_protection(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for role in ('linux', 'windows'):
                root = base / role
                for directory in ('config', 'deploy/vm'):
                    shutil.copytree(ROOT / directory, root / directory)
                config = root / 'config/new-environment.local.json'
                source = (ROOT / 'config/new-environment.example.json' if role == 'linux'
                          else base / 'linux/config/new-environment.local.json')
                shutil.copyfile(source, config)
                configure(root, config, role)
                settings = json.loads(config.read_text())
                if role == 'linux':
                    compose = json.loads((root / 'data/provisioning/compose.json').read_text())
                    self.assertEqual(set(compose['services']), {'db', 'api', 'web'})
                    nginx = (root / 'data/provisioning/nginx.conf').read_text(encoding='utf-8')
                    self.assertNotIn('192.168.97.221', nginx)
                    self.assertNotIn('${MT5_BRIDGE_TOKEN}', nginx)
                    self.assertIn('192.168.1.20:8769', nginx)
                else:
                    self.assertEqual((root / 'data/mt5_bridge.token').read_text().strip(),
                                     settings['bridge_token'])
                    model = json.loads((root / 'data/timestral.json').read_text())
                    self.assertFalse(model['enabled'])
                    self.assertIn(str(root), model['python'])
                before = (root / 'data/database.json').read_bytes()
                with self.assertRaisesRegex(ValueError, 'existente'):
                    configure(root, config, role)
                self.assertEqual(before, (root / 'data/database.json').read_bytes())

    def test_invalid_inputs_do_not_write_runtime_files(self):
        for changes in ({'linux_ip': 'invalid'}, {'web_port': 8770},
                        {'bridge_token': "unsafe'password"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config = root / 'settings.json'
                settings = json.loads((ROOT / 'config/new-environment.example.json').read_text())
                settings.update(changes)
                config.write_text(json.dumps(settings))
                with self.assertRaises(ValueError):
                    configure(root, config, 'linux')
                self.assertFalse((root / 'data').exists())


if __name__ == '__main__':
    unittest.main()
