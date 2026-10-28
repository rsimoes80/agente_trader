"""Install Linux user services; keep the initial trading session stopped."""
import json
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true',
                        help='Atualizar histórico a cada 15 minutos enquanto a sessão estiver parada')
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise RuntimeError('Execute este instalador no Linux.')
    config = json.loads((ROOT / 'config/new-environment.local.json').read_text())
    for relative in ('.venv/bin/python', '.venv-training/bin/python', 'data/database.json'):
        if not (ROOT / relative).exists():
            raise RuntimeError('Pré-requisito ausente: ' + relative)
    token = ROOT / 'data/mt5_bridge.token'
    if token.exists() and token.read_text().strip() != config['bridge_token']:
        raise RuntimeError('Token existente difere da configuração privada.')
    token.write_text(config['bridge_token'] + '\n'); token.chmod(0o600)
    settings = ROOT / 'data/multi_asset.json'
    if not settings.exists():
        settings.write_text((ROOT / 'config/multi_asset.example.json').read_text())
        settings.chmod(0o600)
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    # WorkingDirectory takes the complete unquoted value; ExecStart parses quotes.
    directory = str(ROOT).replace('%', '%%')
    environment = 'Environment=' + json.dumps(
        f"AURELIA_MT5_BRIDGE_URL=http://{config['windows_ip']}:{config['bridge_port']}") + '\n'
    common = ('[Service]\nType=simple\nWorkingDirectory=' + directory + '\n'
              + environment + 'Environment=PYTHONUNBUFFERED=1\nUMask=0077\n')
    agent = ('[Unit]\nDescription=Agente Trader Linux worker\nAfter=network.target\n'
             + common + 'ExecStart=' + json.dumps(str(ROOT / '.venv/bin/python')) + ' '
             + json.dumps(str(ROOT / 'run_agent.py')) + '\nRestart=on-failure\nRestartSec=10\n'
             '[Install]\nWantedBy=default.target\n')
    training = ('[Unit]\nDescription=Agente Trader Linux training queue\n'
                + common.replace('Type=simple', 'Type=oneshot') + 'ExecStart='
                + json.dumps(str(ROOT / '.venv-training/bin/python')) + ' '
                + json.dumps(str(ROOT / 'run_training_lab.py')) + '\n')
    timer = ('[Unit]\nDescription=Check Agente Trader training queue\n[Timer]\n'
             'OnStartupSec=60\nOnUnitInactiveSec=60\nUnit=agente-trader-training.service\n'
             '[Install]\nWantedBy=timers.target\n')
    generated = {'agente-trader-agent.service': agent,
                 'agente-trader-training.service': training,
                 'agente-trader-training.timer': timer}
    enabled = ['agente-trader-agent.service', 'agente-trader-training.timer']
    if args.history:
        generated['agente-trader-history.service'] = (
            '[Unit]\nDescription=Refresh idle EURUSD historical archive\n'
            + common.replace('Type=simple', 'Type=oneshot') + 'ExecStart='
            + json.dumps(str(ROOT / '.venv/bin/python')) + ' '
            + json.dumps(str(ROOT / 'run_history.py')) + ' --days 30 --idle-only\n')
        generated['agente-trader-history.timer'] = (
            '[Unit]\nDescription=Refresh EURUSD history every fifteen minutes\n[Timer]\n'
            'OnStartupSec=120\nOnUnitInactiveSec=15min\nUnit=agente-trader-history.service\n'
            '[Install]\nWantedBy=timers.target\n')
        enabled.append('agente-trader-history.timer')
    for name, contents in generated.items():
        (units / name).write_text(contents)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', *enabled], check=True)
    print('Agente e fila de treinamento instalados no Linux; nenhuma sessão iniciada.')


if __name__ == '__main__':
    main()
