"""Allowlisted Windows terminal operations; strategy and risk remain on Linux."""
from pathlib import Path
import sqlite3

from .bridge_transport import SDK_METHODS, decode, encode
from .demo_terminal import account_identity


def dispatch(provider, payload, journal_path):
    operation = payload.get('operation')
    args, kwargs = decode(payload.get('args', [])), decode(payload.get('kwargs', {}))
    public = {'status', 'fetch_history', 'instrument_catalog', 'inspect_instrument'}
    if operation in public:
        return encode(getattr(provider, operation)(*args, **kwargs))
    if operation not in {'open', 'resolve_symbol', 'clock'} | {'sdk.' + x for x in SDK_METHODS}:
        raise ValueError('Operação da ponte não permitida.')
    with provider._LOCK:
        try:
            status = provider._open_terminal()
            sdk = provider.mt5
            account, terminal = sdk.account_info(), sdk.terminal_info()
            identity = account_identity(account, terminal)
            if operation == 'open':
                return dict(status=status, account_id=identity,
                            constants={k: getattr(sdk, k) for k in dir(sdk)
                                       if k.isupper() and type(getattr(sdk, k)) is int})
            if payload.get('account_id') != identity:
                raise ValueError('A conta ou o terminal mudou durante a conexão.')
            if operation == 'resolve_symbol':
                return provider._resolve_symbol(*args, **kwargs)
            if operation == 'clock':
                return provider._CLOCK.resolve(*args, **kwargs)
            method = operation.removeprefix('sdk.')
            if method in {'order_send', 'order_check'}:
                if account.trade_mode != sdk.ACCOUNT_TRADE_MODE_DEMO:
                    raise ValueError('Envios remotos exigem conta DEMO.')
                if (not terminal.trade_allowed or terminal.tradeapi_disabled
                        or not account.trade_allowed or not account.trade_expert):
                    raise ValueError('Negociação automatizada indisponível.')
                request = args[0] if len(args) == 1 and not kwargs else {}
                if (request.get('magic') != 70616041 or request.get('action') != sdk.TRADE_ACTION_DEAL
                        or not str(request.get('comment', '')).startswith('AFX:')):
                    raise ValueError('Requisição demo inválida.')
                if method == 'order_send':
                    # Commit before IPC. Duplicate/uncertain sends must be reconciled by Linux.
                    Path(journal_path).parent.mkdir(parents=True, exist_ok=True)
                    with sqlite3.connect(journal_path) as connection:
                        connection.execute('CREATE TABLE IF NOT EXISTS sends (account TEXT, marker TEXT, PRIMARY KEY(account, marker))')
                        try:
                            connection.execute('INSERT INTO sends VALUES (?, ?)', (identity, request['comment']))
                        except sqlite3.IntegrityError:
                            raise ValueError('Envio já registrado; reconciliação necessária.') from None
            function = getattr(sdk, method)
            # MT5's C extension distinguishes absent kwargs from an empty dict.
            # Passing **{} makes order_check/order_send reject positional requests.
            result = function(*args, **kwargs) if kwargs else function(*args)
            return encode(result)
        finally:
            if provider.mt5 is not None:
                provider.mt5.shutdown()
