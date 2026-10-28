"""Explicit JSON transport for the Linux worker and the Windows terminal boundary."""
from datetime import datetime
import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def encode(value):
    if isinstance(value, datetime):
        return {'__datetime__': value.isoformat()}
    if hasattr(value, '_asdict'):
        return {'__record__': encode(value._asdict())}
    if isinstance(value, dict):
        return {k: encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        if set(value) == {'__datetime__'}:
            return datetime.fromisoformat(value['__datetime__'])
        if set(value) == {'__record__'}:
            return SimpleNamespace(**decode(value['__record__']))
        return {k: decode(v) for k, v in value.items()}
    return value


class BridgeClient:
    def __init__(self, url, token, *, timeout=120):
        self.url, self.token, self.timeout = url.rstrip('/'), token, timeout
        self.local = threading.local()

    def call(self, operation, *args, **kwargs):
        payload = dict(operation=operation, args=encode(args), kwargs=encode(kwargs),
                       account_id=getattr(self.local, 'account_id', None))
        request = Request(self.url + '/api/mt5/rpc',
                          data=json.dumps(payload, allow_nan=False).encode(),
                          headers={'Content-Type': 'application/json', 'X-Bridge-Token': self.token})
        # Never retry sends: the durable Linux journal must reconcile uncertain outcomes.
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = json.load(response)
        except HTTPError as exc:
            raise RuntimeError('Ponte MT5 recusou a operação (HTTP %s).' % exc.code) from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError('Ponte MT5 indisponível; reconciliar antes de repetir envios.') from None
        if not body.get('ok'):
            raise RuntimeError(body.get('error', 'Falha na ponte MT5.'))
        return decode(body['result'])

    def open(self):
        snapshot = self.call('open')
        self.local.account_id = snapshot['account_id']
        self.local.constants = snapshot['constants']
        return snapshot['status']

    def shutdown(self):
        self.local.account_id = None

    def __getattr__(self, name):
        if name.isupper():
            constants = getattr(self.local, 'constants', {})
            if name not in constants:
                raise AttributeError(name)
            return constants[name]
        if name in SDK_METHODS:
            return lambda *args, **kwargs: self.call('sdk.' + name, *args, **kwargs)
        raise AttributeError(name)


SDK_METHODS = frozenset({'account_info', 'terminal_info', 'symbol_info', 'symbol_info_tick',
                         'positions_get', 'orders_get', 'history_deals_get',
                         'order_calc_profit', 'order_calc_margin', 'order_check', 'order_send'})
