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
    from src.aurelia_fx.entry_trend import POLICIES, STRICT_POLICY_ID
    parser.add_argument('--entry-policy', choices=POLICIES,
                        help='Política de direção dos workers; preservada na configuração privada')
    parser.add_argument('--observe', action='store_true',
                        help='Instalar observação de mercado/modelo sem ordens')
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument('--paper-test', action='store_true',
                        help='Persistir teste paper: ponte somente de leitura e pesos congelados')
    phase.add_argument('--demo-execution', action='store_true',
                       help='Liberar transporte demo somente com todas as sessões paradas')
    args = parser.parse_args()
    if sys.platform != 'linux':
        raise RuntimeError('Execute este instalador no Linux.')
    config = json.loads((ROOT / 'config/new-environment.local.json').read_text())
    paper_test = False if args.demo_execution else args.paper_test or config.get('paper_test', False)
    freeze_weights = paper_test or config.get('freeze_weights', config.get('paper_test', False))
    if type(freeze_weights) is not bool:
        raise ValueError('freeze_weights deve ser booleano.')
    if type(paper_test) is not bool:
        raise ValueError('paper_test deve ser booleano.')
    policy = args.entry_policy or config.get('entry_policy', STRICT_POLICY_ID)
    if policy not in POLICIES:
        raise ValueError('Política de entrada desconhecida.')
    if args.demo_execution or (args.entry_policy and policy != config.get('entry_policy', STRICT_POLICY_ID)):
        # System Python is sufficient for this installer; DB dependencies live in .venv.
        probe = """from src.aurelia_fx.storage import open_memory
from src.aurelia_fx.asset_registry import AssetRegistry
from src.aurelia_fx.operation_control import OperationControl
memory = open_memory()
try:
    for asset in AssetRegistry(memory).list():
        state = OperationControl(memory, asset['symbol']).status()
        if state.get('desired') != 'stopped' or state.get('position') or state.get('pending_execution'):
            raise RuntimeError('Pare e reconcilie todas as sessões antes de mudar a política.')
finally:
    memory.close()
"""
        subprocess.run([str(ROOT / '.venv/bin/python'), '-c', probe], cwd=ROOT, check=True)
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
    environment += 'Environment=' + json.dumps('AURELIA_ENTRY_POLICY=' + policy) + '\n'
    environment += 'Environment=AURELIA_MT5_READ_ONLY=' + ('1' if paper_test else '0') + '\n'
    if config.get('require_literature',False):
        environment += 'Environment=AURELIA_REQUIRE_LITERATURE=1\n'
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
    enabled = ['agente-trader-agent.service']
    if not freeze_weights:enabled.append('agente-trader-training.timer')
    if args.observe:
        if not (ROOT / 'data/timestral.json').exists():
            raise RuntimeError('Configure Timestral antes de iniciar o observador.')
        generated['agente-trader-observation.service'] = (
            '[Unit]\nDescription=Read-only market and model observation\n'
            + common + 'ExecStart=' + json.dumps(str(ROOT / '.venv/bin/python')) + ' '
            + json.dumps(str(ROOT / 'run_live_observation.py'))
            + '\nRestart=on-failure\nRestartSec=15\n[Install]\nWantedBy=default.target\n')
        enabled.append('agente-trader-observation.service')
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
    if args.demo_execution:
        drop_in = units / 'agente-trader-agent.service.d/paper-test.conf'
        if drop_in.exists():
            if drop_in.read_text() != '[Service]\nEnvironment=AURELIA_MT5_READ_ONLY=1\n':
                raise RuntimeError('Drop-in paper personalizado: preservar e revisar antes de liberar demo.')
            drop_in.unlink()
    for name, contents in generated.items():
        (units / name).write_text(contents)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    if freeze_weights:
        subprocess.run(['systemctl','--user','disable','--now','agente-trader-training.timer'],check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', *enabled], check=True)
    if args.entry_policy or args.paper_test or args.demo_execution:
        config.update(entry_policy=policy,paper_test=paper_test,freeze_weights=freeze_weights)
        config_path = ROOT / 'config/new-environment.local.json'
        config_path.write_text(json.dumps(config,indent=2)+'\n')
        config_path.chmod(0o600)
        compose_path = ROOT / 'data/provisioning/compose.json'
        if compose_path.exists():
            compose = json.loads(compose_path.read_text())
            compose['services']['api']['environment']['AURELIA_ENTRY_POLICY'] = policy
            compose['services']['api']['environment']['AURELIA_MT5_READ_ONLY']='1' if paper_test else '0'
            compose_path.write_text(json.dumps(compose,indent=2)+'\n')
            compose_path.chmod(0o600)
    print('Serviços configurados; o instalador não altera o estado da sessão.')


if __name__ == '__main__':
    main()
