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

CSRF=secrets.token_urlsafe(32)
ALLOWED_ORIGINS={'http://192.168.97.221:8097','http://127.0.0.1:8770','http://localhost:8770'}
STATIC={'/operacao':'operation.html','/operation.css':'operation.css','/operation.js':'operation.js',
        '/diagnostico':'diagnostics.html','/diagnostico/':'diagnostics.html',
        '/diagnostics.css':'diagnostics.css','/diagnostics.js':'diagnostics.js',
        '/timestral.css':'timestral.css','/timestral-panel.js':'timestral-panel.js',
        '/history.css':'history.css','/history-panel.js':'history-panel.js'}

class Application:
    def __init__(self):
        self.memory=open_memory()
        self.operation=OperationControl(self.memory)
        self.forecasts=ForecastRepository(self.memory)
        self.history=HistoricalRepository(self.memory)

class Handler(BaseHTTPRequestHandler):
    server_version='AureliaFX/2.0'
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
            if path=='/api/diagnostics/agent':
                self.send(200,dict(ok=True,csrf=CSRF,state=app.operation.status(),
                    worker=app.operation.worker_status(),authenticated=True,access_mode='single_user'));return
            if path=='/api/diagnostics/decisions':
                state=app.operation.status()
                self.send(200,dict(ok=True,session_id=state.get('session_id'),
                    decisions=decisions(app.memory,state.get('session_id'),limit=args.get('limit',50),offset=args.get('offset',0))));return
            if path=='/api/diagnostics/history':
                self.send(200,dict(ok=True,**app.history.summary()));return
            if path=='/api/diagnostics/timestral':
                self.send(200,dict(ok=True,**app.forecasts.summary(scope=args.get('scope','live'),source_id=args.get('source_id'))));return
            if path=='/health':
                self.send(200,dict(ok=True,service='Aurelia FX operation API',worker=app.operation.worker_status()));return
            self.send(404,dict(ok=False,error='Rota inexistente.'))
        except (ValueError,TypeError,KeyError):self.send(400,dict(ok=False,error='Consulta invalida.'))
        except Exception:self.send(503,dict(ok=False,error='Servico temporariamente indisponivel; nova tentativa automatica.'))
    def do_POST(self):
        try:
            if urlparse(self.path).path!='/api/diagnostics/agent/command':
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
            state=self.server.app.operation.command(payload,self.headers.get('Idempotency-Key',''),actor='local_owner')
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
