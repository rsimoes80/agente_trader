"""Switching out of paper preserves frozen weights and custom safety settings."""
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
import install_linux_workers as installer


def fixture(tmp_path,monkeypatch):
    root=tmp_path/'repo';home=tmp_path/'home'
    for name in ('.venv/bin/python','.venv-training/bin/python','data/database.json'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
    config=root/'config';config.mkdir()
    settings=dict(paper_test=True,entry_policy='daytrade-h1-confirmed-v1',bridge_token='fixture-token',windows_ip='192.168.1.2',bridge_port=8769)
    (config/'new-environment.local.json').write_text(json.dumps(settings))
    (config/'multi_asset.example.json').write_text('{}')
    units=home/'.config/systemd/user';units.mkdir(parents=True)
    monkeypatch.setattr(installer,'ROOT',root)
    monkeypatch.setattr(Path,'home',lambda:home)
    monkeypatch.setattr('sys.argv',['install_linux_workers.py','--demo-execution'])
    run=Mock();monkeypatch.setattr(installer.subprocess,'run',run)
    return root,units,run


def test_demo_switch_unblocks_transport_without_unfreezing_weights(tmp_path,monkeypatch):
    root,units,run=fixture(tmp_path,monkeypatch)
    drop=units/'agente-trader-agent.service.d/paper-test.conf';drop.parent.mkdir()
    drop.write_text('[Service]\nEnvironment=AURELIA_MT5_READ_ONLY=1\n')
    installer.main()
    settings=json.loads((root/'config/new-environment.local.json').read_text())
    assert settings['paper_test'] is False and settings['freeze_weights'] is True
    assert 'AURELIA_MT5_READ_ONLY=0' in (units/'agente-trader-agent.service').read_text()
    assert not drop.exists()
    enabled=[c.args[0] for c in run.call_args_list if '--now' in c.args[0] and 'enable' in c.args[0]]
    assert all('agente-trader-training.timer' not in command for command in enabled)


def test_custom_drop_in_is_preserved_and_service_is_not_overwritten(tmp_path,monkeypatch):
    root,units,run=fixture(tmp_path,monkeypatch)
    drop=units/'agente-trader-agent.service.d/paper-test.conf';drop.parent.mkdir()
    drop.write_text('[Service]\nEnvironment=CUSTOM_SAFETY=1\n')
    service=units/'agente-trader-agent.service';service.write_text('original')
    with pytest.raises(RuntimeError,match='personalizado'):installer.main()
    assert service.read_text()=='original'
    assert 'CUSTOM_SAFETY' in drop.read_text()
    assert json.loads((root/'config/new-environment.local.json').read_text())['paper_test'] is True
