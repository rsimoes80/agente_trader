"""Install the user-level book research worker; never change the trading session."""
import argparse
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specialists',nargs='+',default=['pullback','pring'])
    parser.add_argument('--interval',type=int,default=900)
    args=parser.parse_args()
    import sys
    sys.path.insert(0,str(ROOT/'src'))
    from aurelia_fx.book_profiles import BY_ID
    if any(s not in BY_ID for s in args.specialists):parser.error('Unknown specialist')
    if args.interval<300:parser.error('Minimum interval is 300 seconds')
    if len(set(args.specialists))!=len(args.specialists):parser.error('Repeated specialist')
    for required in (ROOT/'.venv/bin/python',ROOT/'data/database.json',ROOT/'data/references_cache/learning-library/inventory.json'):
        if not required.exists():raise SystemExit('Missing prerequisite: '+str(required))
    command=[str(ROOT/'.venv/bin/python'),str(ROOT/'run_book_specialists.py'),'--watch','--interval',str(args.interval),'--specialists',*args.specialists]
    # systemd ExecStart uses double-quoted arguments, not shell single-quote semantics.
    def systemd_argument(value):return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    unit='''[Unit]
Description=Source-grounded book specialists (asynchronous research, no orders)
After=agente-trader-literature-model.service agente-trader-observation.service
[Service]
Type=simple
WorkingDirectory={cwd}
ExecStart={command}
Environment=PYTHONUNBUFFERED=1
Environment=AURELIA_MT5_READ_ONLY=1
Restart=on-failure
RestartSec=60
UMask=0077
[Install]
WantedBy=default.target
'''.format(cwd=str(ROOT).replace('%','%%'),command=' '.join(systemd_argument(x) for x in command))
    directory=Path.home()/'.config/systemd/user';directory.mkdir(parents=True,exist_ok=True)
    (directory/'agente-trader-book-specialists.service').write_text(unit)
    subprocess.run(['systemd-analyze','--user','verify',str(directory/'agente-trader-book-specialists.service')],check=True)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','agente-trader-book-specialists.service'],check=True)
    print('Installed research specialists: '+', '.join(args.specialists))


if __name__=='__main__':main()
