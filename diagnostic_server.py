"""Single-user operation API and read-only diagnostics of the actual agent."""
from __future__ import annotations
import hmac
import json
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import secrets
import signal
import sys
import threading
from urllib.parse import parse_qs,urlparse

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))
from aurelia_fx.storage import open_memory
from aurelia_fx.operation_control import OperationControl
from aurelia_fx.agent_diagnostics import decisions
from aurelia_fx.forecasting.repository import ForecastRepository
from aurelia_fx.historical.repository import HistoricalRepository
from aurelia_fx.training.repository import TrainingRepository
from aurelia_fx.asset_registry import AssetRegistry
from aurelia_fx.instruments import symbol_name

CSRF=secrets.token_urlsafe(32)
ALLOWED_ORIGINS={'http://192.168.97.221:8097','http://127.0.0.1:8770','http://localhost:8770'}
STATIC={'/operacao':'operation.html','/operation.css':'operation.css','/operation.js':'operation.js',
        '/diagnostico':'diagnostics.html','/diagnostico/':'diagnostics.html',
        '/diagnostics.css':'diagnostics.css','/diagnostics.js':'diagnostics.js',
        '/timestral.css':'timestral.css','/timestral-panel.js':'timestral-panel.js',
        '/history.css':'history.css','/history-panel.js':'history-panel.js',
        '/treinamento':'training.html','/treinamento/':'training.html',
        '/training.css':'training.css','/training.js':'training.js'}

class Application:
    def __init__(self):
        self.memory=open_memory()
        self.operation=OperationControl(self.memory)
        self.forecasts=ForecastRepository(self.memory)
        self.history=HistoricalRepository(self.memory)
        self.training=TrainingRepository(self.memory)
        self.assets=AssetRegistry(self.memory)


def inspect_remote_instrument(symbol):
    import urllib.request
    from urllib.parse import urlencode
    url='http://192.168.97.221:8097/api/mt5/instrument?'+urlencode({'symbol':symbol})
    with urllib.request.urlopen(url,timeout=8) as response:data=json.load(response)
    if data.get('ok') is not True:raise ValueError('Não foi possível verificar o contrato do ativo.')
    return data


def instrument_execution_ready(symbol,worker):
    heartbeat=worker.get('heartbeat') or {}
    return symbol=='EURUSD' or bool(worker.get('available') and heartbeat.get('symbol')==symbol and heartbeat.get('engine_version')=='multi-instrument-v1')

class Handler(BaseHTTPRequestHandler):
    server_version='AgenteTraderIA/2.0'
    sys_version=''
    def setup(self):
        super().setup()
        self.connection.settimeout(10)
    def log_message(self,fmt,*args):print(self.command,urlparse(self.path).path,flush=True)
    def send(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass
    def do_GET(self):
        path=urlparse(self.path).path
        args={k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()}
        try:
            if path in STATIC:
                target=ROOT/'static'/STATIC[path];body=target.read_bytes()
                mime={'.html':'text/html','.css':'text/css','.js':'application/javascript'}[target.suffix]
                self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8')
                self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-cache')
                self.end_headers();self.wfile.write(body);return
            app=self.server.app
            if path=='/api/diagnostics/training':
                from aurelia_fx.training.automatic import status as automatic_status
                self.send(200,dict(ok=True,csrf=CSRF,state=app.training.summary(),automatic=automatic_status(app.memory)));return
            if path=='/api/diagnostics/agent':
                from aurelia_fx.learning_evolution import collection_health
                symbol=symbol_name(args.get('symbol','EURUSD'));control=OperationControl(app.memory,symbol)
                state=control.status();worker=control.worker_status()
                self.send(200,dict(ok=True,csrf=CSRF,state=state,
                    worker=worker,collection_health=collection_health(state,worker),
                    execution_ready=instrument_execution_ready(symbol,worker),
                    asset=app.assets.get(symbol),authenticated=True,access_mode='single_user'));return
            if path=='/api/diagnostics/instruments':
                instruments=[]
                for asset in app.assets.list():
                    if not asset.get('selected'):continue
                    control=OperationControl(app.memory,asset['symbol']);state=control.status();worker=control.worker_status()
                    instruments.append({**asset,'state':state['state'],'desired':state['desired'],
                        'has_exposure':bool(state.get('position') or state.get('pending_execution')),
                        'execution_ready':instrument_execution_ready(asset['symbol'],worker)})
                self.send(200,dict(ok=True,csrf=CSRF,instruments=instruments));return
            if path=='/api/diagnostics/decisions':
                state=OperationControl(app.memory,symbol_name(args.get('symbol','EURUSD'))).status()
                self.send(200,dict(ok=True,session_id=state.get('session_id'),
                    decisions=decisions(app.memory,state.get('session_id'),limit=args.get('limit',50),offset=args.get('offset',0))));return
            if path=='/api/diagnostics/history':
                symbol=symbol_name(args.get('symbol','EURUSD'))
                self.send(200,dict(ok=True,**HistoricalRepository(app.memory,symbol).summary()));return
            if path=='/api/diagnostics/timestral':
                self.send(200,dict(ok=True,**app.forecasts.summary(scope=args.get('scope','live'),source_id=args.get('source_id'))));return
            if path=='/health':
                self.send(200,dict(ok=True,service='Agente Trader - IA operation API',worker=app.operation.worker_status()));return
            self.send(404,dict(ok=False,error='Rota inexistente.'))
        except (ValueError,TypeError,KeyError):self.send(400,dict(ok=False,error='Consulta invalida.'))
        except Exception:self.send(503,dict(ok=False,error='Servico temporariamente indisponivel; nova tentativa automatica.'))
    def do_POST(self):
        try:
            path=urlparse(self.path).path
            if path not in {'/api/diagnostics/agent/command','/api/diagnostics/training/command','/api/diagnostics/instruments/command'}:
                self.send(404,dict(ok=False,error='Rota inexistente.'));return
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16000 or self.headers.get('Content-Type','').split(';')[0]!='application/json':
                raise ValueError('Invalid JSON request')
            body=self.rfile.read(length)
            origin=self.headers.get('Origin')
            if (origin and origin not in ALLOWED_ORIGINS) or not hmac.compare_digest(self.headers.get('X-Diagnostics-CSRF',''),CSRF):
                self.send(403,dict(ok=False,error='Recarregue o painel para renovar a conexao.'));return
            payload=json.loads(body)
            if not isinstance(payload,dict):raise ValueError('Object required')
            if path=='/api/diagnostics/training/command':
                state=self.server.app.training.command(payload.get('action'),self.headers.get('Idempotency-Key',''))
            elif path=='/api/diagnostics/instruments/command':
                state=self.server.app.assets.command(payload,self.headers.get('Idempotency-Key',''),inspect_remote_instrument)
            else:
                symbol=symbol_name(payload.get('symbol','EURUSD'));control=OperationControl(self.server.app.memory,symbol)
                if payload.get('action')=='START':
                    configured=self.server.app.assets.get(symbol)
                    if not configured or not configured.get('selected'):raise ValueError('Configure este ativo primeiro.')
                    from aurelia_fx.operation_control import validate_lot
                    validate_lot(payload.get('lot'),configured.get('contract'))
                if symbol!='EURUSD':
                    configured=self.server.app.assets.get(symbol)
                    if not configured or not configured.get('selected'):raise ValueError('Configure este ativo primeiro.')
                    if payload.get('action')=='START' and not instrument_execution_ready(symbol,control.worker_status()):
                        raise ValueError('Ativo configurado. A execução deste ativo aguarda a preparação do motor multiativo.')
                state=control.command(payload,self.headers.get('Idempotency-Key',''),actor='local_owner')
                if payload.get('action')=='START':self.server.app.assets.remember_session_lot(state)
            self.send(200,dict(ok=True,state=state))
        except (ValueError,TypeError,KeyError) as exc:self.send(400,dict(ok=False,error=str(exc)[:200]))
        except Exception:self.send(503,dict(ok=False,error='Nao foi possivel persistir o comando. Consulte o estado antes de repetir.'))

def main():
    app=Application();server=ThreadingHTTPServer(('127.0.0.1',8770),Handler)
    server.daemon_threads=True;server.app=app
    def stop(*_):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:server.serve_forever()
    finally:server.server_close();app.memory.close()

if __name__=='__main__':main()
