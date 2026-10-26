"""Read-only access to prices and bars from the locally logged-in MT5 terminal."""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from src.aurelia_fx.mt5_clock import ClockCalibrationPending, MT5Clock

if sys.platform == "win32":
    import MetaTrader5 as mt5
else:  # The official Python bridge requires a local Windows terminal.
    mt5 = None


_LOCK = threading.Lock()
_CLOCK = MT5Clock(Path(__file__).resolve().parent / "data/mt5_clock_state.json")
_TIMEFRAMES: dict[str, int] = {
    "M1": 1,
    "M2": 2,
    "M3": 3,
    "M4": 4,
    "M5": 5,
    "M6": 6,
    "M10": 10,
    "M12": 12,
    "M15": 15,
    "M20": 20,
    "M30": 30,
    "H1": 16385,
    "H2": 16386,
    "H3": 16387,
    "H4": 16388,
    "H6": 16390,
    "H8": 16392,
    "H12": 16396,
    "D1": 16408,
    "W1": 32769,
    "MN": 49153,
}


def _require_package() -> None:
    if mt5 is None:
        raise RuntimeError(
            "O conector oficial MetaTrader5 precisa rodar no Windows junto ao terminal. "
            "Este projeto foi aberto em Linux; inicie o serviço de análise no Windows que está com o MT5."
        )


def _open_terminal() -> dict[str, Any]:
    _require_package()
    if not mt5.initialize(timeout=5000):
        raise RuntimeError(
            f"Não foi possível conectar ao terminal MT5 aberto: {mt5.last_error()}."
        )
    terminal = mt5.terminal_info()
    account = mt5.account_info()
    if terminal is None or account is None or not terminal.connected:
        error = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"Terminal MT5 sem sessão de corretora conectada: {error}.")
    return {
        "connected": True,
        "terminal": terminal.name,
        "broker": account.company,
        "server": account.server,
        "account_currency": account.currency,
        "trade_mode": "demo"
        if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO
        else "real_or_other",
        "orders_enabled_by_application": False,
    }


def status() -> dict[str, Any]:
    with _LOCK:
        try:
            return _open_terminal()
        finally:
            if mt5 is not None:
                mt5.shutdown()


def instrument_catalog(query='', limit=100):
    """Exact broker symbols for a selector; no trading or fuzzy substitution."""
    if not isinstance(query,str) or len(query)>80:raise ValueError('Busca de ativo inválida.')
    limit=max(1,min(200,int(limit)))
    with _LOCK:
        try:
            terminal=_open_terminal();symbols=mt5.symbols_get()
            if symbols is None:raise RuntimeError('Catálogo de ativos indisponível.')
            matches=sorted((s for s in symbols if query.casefold() in (s.name+' '+s.description).casefold()),key=lambda s:s.name)
            return dict(broker=terminal['broker'],server=terminal['server'],account_currency=terminal['account_currency'],
                total=len(matches),symbols=[dict(symbol=s.name,description=s.description,path=s.path,
                    contract_size=s.trade_contract_size,volume_min=s.volume_min,volume_step=s.volume_step,
                    currency_profit=s.currency_profit,trade_mode=s.trade_mode) for s in matches[:limit]])
        finally:
            if mt5 is not None:mt5.shutdown()


def inspect_instrument(symbol):
    from src.aurelia_fx.instruments import inspect_contract
    with _LOCK:
        try:
            terminal=_open_terminal()
            return dict(**inspect_contract(mt5,symbol,broker=terminal['broker'],server=terminal['server']),
                        account_currency=terminal['account_currency'],trade_mode=terminal['trade_mode'])
        finally:
            if mt5 is not None:mt5.shutdown()


def _resolve_symbol(requested: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", requested.upper())
    symbols = mt5.symbols_get() or ()
    exact = [
        symbol.name
        for symbol in symbols
        if re.sub(r"[^A-Z0-9]", "", symbol.name.upper()) == compact
    ]
    if not exact:
        exact = [
            symbol.name
            for symbol in symbols
            if re.sub(r"[^A-Z0-9]", "", symbol.name.upper()).startswith(compact)
        ]
    if not exact:
        raise ValueError(
            f"O ativo {requested} não foi encontrado na lista de símbolos deste MT5."
        )
    if len(exact) > 1:
        visible = [
            name
            for name in exact
            if (mt5.symbol_info(name) and mt5.symbol_info(name).visible)
        ]
        if len(visible) == 1:
            exact = visible
        else:
            raise ValueError(
                f"Há mais de um símbolo compatível ({', '.join(exact[:8])}); informe o nome exato do MT5."
            )
    name = exact[0]
    if not mt5.symbol_select(name, True):
        raise RuntimeError(
            f"Não foi possível habilitar {name} no Market Watch: {mt5.last_error()}."
        )
    return name


def fetch_history(
    instrument: str, timeframe: str, count: int, *, include_current: bool = False
) -> dict[str, Any]:
    if timeframe.upper() not in _TIMEFRAMES:
        raise ValueError(f"Período MT5 não suportado: {timeframe}.")
    if not 100 <= int(count) <= 100_000:
        raise ValueError("A captura precisa conter entre 100 e 100.000 candles.")
    with _LOCK:
        try:
            terminal = _open_terminal()
            symbol = _resolve_symbol(instrument)
            info = mt5.symbol_info(symbol)
            tick = mt5.symbol_info_tick(symbol)
            for attempt in range(3):
                try:
                    clock = _CLOCK.resolve(
                        terminal["broker"],
                        terminal["server"],
                        tick.time if tick else None,
                    )
                    break
                except ClockCalibrationPending:
                    if attempt == 2:
                        raise
                    time.sleep(1.1)
                    tick = mt5.symbol_info_tick(symbol)
            chunks = []
            remaining = int(count)
            # The chart should match MT5's rightmost, still-forming candle. Backtests
            # keep the default (position 1) so they only consume completed bars.
            position = 0 if include_current else 1
            while remaining:
                chunk_size = min(remaining, 65_535)
                chunk = mt5.copy_rates_from_pos(
                    symbol, _TIMEFRAMES[timeframe.upper()], position, chunk_size
                )
                if chunk is None:
                    raise RuntimeError(
                        f"Falha ao ler histórico do MT5: {mt5.last_error()}."
                    )
                if not len(chunk):
                    break
                chunks.append(chunk)
                position += len(chunk)
                remaining -= len(chunk)
                if len(chunk) < chunk_size:
                    break
            if not chunks:
                raise RuntimeError(
                    f"Falha ao ler histórico do MT5: {mt5.last_error()}."
                )
            import numpy as np

            rates = np.concatenate(list(reversed(chunks)))
            if len(rates) < 100:
                raise ValueError(
                    f"O terminal retornou somente {len(rates)} candles. Abra o gráfico {symbol} em {timeframe} "
                    "no MT5 e carregue mais histórico antes de tentar novamente."
                )
            pip_size = info.point * 10 if info.digits in (3, 5) else info.point
            candles = []
            normalized = _CLOCK.normalize_bars(rates, clock)
            for rate, (stamp, raw_epoch, offset) in zip(rates, normalized):
                candles.append(
                    {
                        "timestamp": stamp,
                        "source_time_epoch": raw_epoch,
                        "source_utc_offset_seconds": offset,
                        "open": float(rate["open"]),
                        "high": float(rate["high"]),
                        "low": float(rate["low"]),
                        "close": float(rate["close"]),
                        "volume": float(rate["tick_volume"]),
                        "spread_pips": float(rate["spread"]) * info.point / pip_size
                        if pip_size
                        else 0.0,
                    }
                )
            return {
                "candles": candles,
                "source": "MetaTrader 5 · terminal local",
                "symbol": symbol,
                "timeframe": timeframe.upper(),
                "count": len(candles),
                "from_utc": candles[0]["timestamp"],
                "to_utc": candles[-1]["timestamp"],
                "digits": info.digits,
                "pip_size": pip_size,
                "symbol_contract": {
                    "volume_min": float(info.volume_min),
                    "volume_max": float(info.volume_max),
                    "volume_step": float(info.volume_step),
                    "contract_size": float(info.trade_contract_size),
                    "currency_profit": info.currency_profit,
                    "currency_margin": info.currency_margin,
                }
                if all(
                    hasattr(info, key)
                    for key in (
                        "volume_min",
                        "volume_max",
                        "volume_step",
                        "trade_contract_size",
                        "currency_profit",
                        "currency_margin",
                    )
                )
                else None,
                "broker": terminal["broker"],
                "server": terminal["server"],
                "trade_mode": terminal["trade_mode"],
                "source_clock": clock,
                "timestamp_semantics": "utc_v1",
                "quote": (
                    {
                        "bid": float(tick.bid),
                        "ask": float(tick.ask),
                        "last": float(tick.last),
                        "time": clock["tick_utc"],
                        "source_time_epoch": int(tick.time),
                    }
                    if tick is not None
                    else None
                ),
            }
        finally:
            if mt5 is not None:
                mt5.shutdown()
