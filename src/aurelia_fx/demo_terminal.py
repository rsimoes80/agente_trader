"""Windows terminal boundary; every connection and send is pinned to DEMO."""

from contextlib import contextmanager
from datetime import datetime, timezone
import math

from .agent_model import fingerprint


def account_identity(account, terminal):
    return fingerprint(dict(login=int(account.login),server=account.server,path=terminal.path))


class DemoTerminal:
    def __init__(self, provider, *, account_id=None, clock_id=None):
        self.provider=provider;self.sdk=provider.mt5
        self.account_id=account_id;self.clock_id=clock_id
        self.check_account()
        self.symbol=provider._resolve_symbol("EURUSD")
        self.info=self.sdk.symbol_info(self.symbol)
        if self.account.currency!="USD" or self.info.currency_base!="EUR" or self.info.currency_profit!="USD":
            raise ValueError("O executor demo requer conta USD e contrato EUR/USD.")

    def check_account(self, *, sending=False):
        account=self.sdk.account_info();terminal=self.sdk.terminal_info()
        if account is None or terminal is None or not terminal.connected:
            raise RuntimeError("Terminal demo desconectado.")
        if account.trade_mode!=self.sdk.ACCOUNT_TRADE_MODE_DEMO:
            raise ValueError("Execução recusada: a conta do MT5 não é DEMO.")
        identity=account_identity(account,terminal)
        if self.account_id and identity!=self.account_id:
            raise ValueError("A conta ou o terminal mudou. A autorização demo não será transferida.")
        if sending and (not terminal.trade_allowed or terminal.tradeapi_disabled
                        or not account.trade_allowed or not account.trade_expert):
            raise RuntimeError("Negociação automatizada não está habilitada no terminal demo.")
        self.account_id=identity;self.account=account;self.terminal=terminal
        return account

    def quote(self):
        tick=self.sdk.symbol_info_tick(self.symbol)
        if tick is None:raise RuntimeError("Cotação demo indisponível.")
        clock=self.provider._CLOCK.resolve(self.account.company,self.account.server,tick.time)
        if self.clock_id and clock["clock_id"]!=self.clock_id:
            raise ValueError("A fonte de horário mudou durante a execução demo.")
        now=datetime.now(timezone.utc)
        age=(now-datetime.fromisoformat(clock["tick_utc"])).total_seconds()
        if not clock["verified_current"] or not 0<=age<=5:
            raise RuntimeError("Aguardando cotação demo recente e relógio validado.")
        if not all(math.isfinite(p) and p>0 for p in (tick.bid,tick.ask)) or tick.ask<tick.bid:
            raise ValueError("Bid/ask demo inválido.")
        self.clock_id=clock["clock_id"]
        return dict(bid=tick.bid,ask=tick.ask,at=clock["tick_utc"],observed_at=now.isoformat())

    def positions(self):
        rows=self.sdk.positions_get()
        if rows is None:raise RuntimeError("Não foi possível reconciliar as posições demo.")
        return list(rows)

    def orders(self):
        rows=self.sdk.orders_get()
        if rows is None:raise RuntimeError("Não foi possível reconciliar as ordens demo.")
        return list(rows)


@contextmanager
def demo_terminal(*, account_id=None, clock_id=None):
    import mt5_provider as provider
    with provider._LOCK:
        try:
            provider._open_terminal()
            yield DemoTerminal(provider,account_id=account_id,clock_id=clock_id)
        finally:
            if provider.mt5 is not None:provider.mt5.shutdown()
