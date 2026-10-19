"""Read-only Dukascopy FIX 4.4 market-data session and live candle builder."""

from __future__ import annotations

import socket
import ssl
import threading
import time
from collections import deque
from datetime import datetime, timezone
from datetime import time as session_time
from typing import Any, Callable

from analysis import analyze
from src.aurelia_fx.market_intelligence import (
    MarketIntelligenceSession,
    observation_only_result,
)
from src.aurelia_fx.regime.strategy_metadata import StrategyMetadata
from src.aurelia_fx.sessions import SessionWindow
from src.aurelia_fx.trend import HierarchyConfig

TIMEFRAME_SECONDS = {
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}
SOH = b"\x01"


def _fix_time(value: str | None, date_value: str | None = None) -> datetime:
    if value:
        candidate = value
        if date_value and len(value) <= 15 and len(date_value) == 8:
            candidate = f"{date_value}-{value}"
        try:
            return datetime.strptime(candidate[:21], "%Y%m%d-%H:%M:%S.%f").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            try:
                return datetime.strptime(candidate[:17], "%Y%m%d-%H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                pass
        try:
            parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed.astimezone(timezone.utc)
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _build_message(
    msg_type: str, seq: int, sender: str, target: str, fields: list[tuple[str, str]]
) -> bytes:
    sending_time = datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3]
    body = (
        SOH.join(
            [
                f"35={msg_type}".encode(),
                f"34={seq}".encode(),
                f"49={sender}".encode(),
                f"52={sending_time}".encode(),
                f"56={target}".encode(),
                *(f"{tag}={value}".encode() for tag, value in fields),
            ]
        )
        + SOH
    )
    prefix = b"8=FIX.4.4\x019=" + str(len(body)).encode() + SOH
    unsigned = prefix + body
    checksum = sum(unsigned) % 256
    return unsigned + f"10={checksum:03d}".encode() + SOH


def _extract_frame(buffer: bytearray) -> dict[str, Any] | None:
    begin = b"8=FIX.4.4\x01"
    start = buffer.find(begin)
    if start < 0:
        if len(buffer) > 32:
            del buffer[:-16]
        return None
    if start:
        del buffer[:start]
    body_length_start = len(begin)
    length_end = buffer.find(SOH, body_length_start)
    if length_end < 0:
        return None
    try:
        body_length = int(bytes(buffer[body_length_start:length_end]).split(b"=", 1)[1])
    except (ValueError, IndexError):
        del buffer[0]
        return None
    body_start = length_end + 1
    checksum_start = body_start + body_length
    frame_end = checksum_start + 7
    if len(buffer) < frame_end:
        return None
    frame = bytes(buffer[:frame_end])
    del buffer[:frame_end]
    if frame[checksum_start : checksum_start + 3] != b"10=":
        raise ValueError("Quadro FIX com checksum ausente ou inválido.")
    try:
        received_checksum = int(frame[checksum_start + 3 : checksum_start + 6])
    except ValueError:
        raise ValueError("Checksum FIX malformado.") from None
    if sum(frame[:checksum_start]) % 256 != received_checksum:
        raise ValueError("Checksum FIX não confere.")
    values: dict[str, Any] = {}
    pairs: list[tuple[str, str]] = []
    for item in frame.rstrip(SOH).split(SOH):
        if b"=" in item:
            tag, value = item.split(b"=", 1)
            pairs.append(
                (tag.decode("ascii", "ignore"), value.decode("utf-8", "replace"))
            )
    for tag, value in pairs:
        values[tag] = value
    values["_pairs"] = pairs
    return values


class DukascopyFeed:
    """One FIX market-data connection. Trading messages are never generated."""

    def __init__(
        self,
        config_provider: Callable[[], dict[str, Any]],
        model_provider: Callable[[], dict[str, Any] | None] | None = None,
    ):
        self.config_provider = config_provider
        self.model_provider = model_provider or (lambda: None)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: ssl.SSLSocket | None = None
        self._bars: deque[dict[str, Any]] = deque(maxlen=3000)
        self._events: deque[dict[str, Any]] = deque(maxlen=100)
        self._state: dict[str, Any] = {
            "status": "desconectado",
            "message": "Feed ao vivo parado.",
            "ticks": 0,
        }
        self._bar: dict[str, Any] | None = None
        self._bucket: int | None = None
        self._bid: float | None = None
        self._ask: float | None = None
        self._seq = 1
        self._last_send = 0.0
        self._analysis: dict[str, Any] = {
            "signal": "WAIT",
            "message": "Aguardando feed de mercado.",
        }
        self._jev_review: dict[str, Any] | None = None

    def start(self, settings: dict[str, Any]) -> None:
        self.stop()
        with self._lock:
            stop_event = threading.Event()
            self._stop = stop_event
            self._bars.clear()
            self._events.clear()
            self._bar = None
            self._bucket = None
            self._bid = self._ask = None
            self._analysis = {
                "signal": "WAIT",
                "message": "Aguardando cotações e candles fechados.",
            }
            self._jev_review = None
            self._state = {
                "status": "conectando",
                "message": "Abrindo sessão FIX segura de leitura.",
                "ticks": 0,
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(dict(settings), stop_event),
                name="dukascopy-market-data",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            active = self._socket
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        if thread and thread.is_alive() and active:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active.close()
            except OSError:
                pass
        with self._lock:
            if self._state.get("status") != "erro":
                self._state.update(
                    status="desconectado", message="Feed ao vivo parado."
                )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._state,
                "quote": {
                    "bid": self._bid,
                    "ask": self._ask,
                    "mid": (
                        (self._bid + self._ask) / 2
                        if self._bid is not None and self._ask is not None
                        else None
                    ),
                },
                "current_candle": dict(self._bar) if self._bar else None,
                "candles": [dict(item) for item in list(self._bars)[-500:]],
                "analysis": dict(self._analysis),
                "jev_review": dict(self._jev_review) if self._jev_review else None,
                "events": [dict(item) for item in self._events],
                "live_orders_enabled": False,
            }

    def _send(
        self,
        sock: ssl.SSLSocket,
        msg_type: str,
        target: str,
        sender: str,
        fields: list[tuple[str, str]] = (),
    ) -> None:
        message = _build_message(msg_type, self._seq, sender, target, list(fields))
        self._seq += 1
        sock.sendall(message)
        self._last_send = time.monotonic()

    def _run(self, settings: dict[str, Any], stop_event: threading.Event) -> None:
        sock: ssl.SSLSocket | None = None
        try:
            host = str(settings["host"]).strip()
            port = int(settings["port"])
            target = str(settings["target_comp_id"]).strip()
            sender = str(settings["feed_sender_comp_id"]).strip()
            feed_sender = sender if sender.startswith("FEED_") else f"FEED_{sender}"
            username = str(settings["username"])
            password = str(settings["password"])
            if (
                not host
                or not (1 <= port <= 65535)
                or not all((target, sender, username, password))
            ):
                raise ValueError(
                    "Complete host, porta, TargetCompID, SenderCompID do feed, usuário e senha FIX."
                )
            raw = socket.create_connection((host, port), timeout=15)
            context = ssl.create_default_context()
            sock = context.wrap_socket(raw, server_hostname=host)
            sock.settimeout(0.5)
            with self._lock:
                self._socket = sock
                self._state.update(
                    status="autenticando",
                    message="Conexão TLS aberta; aguardando logon FIX.",
                    host=host,
                )
            self._seq = 1
            self._send(
                sock,
                "A",
                target,
                sender,
                [
                    ("98", "0"),
                    ("108", "30"),
                    ("141", "Y"),
                    ("553", username),
                    ("554", password),
                ],
            )
            buffer = bytearray()
            logged_in = False
            subscribed = False
            expected_in = 1
            last_receive = time.monotonic()
            while not stop_event.is_set():
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        raise ConnectionError("A corretora encerrou a sessão FIX.")
                    buffer.extend(chunk)
                except socket.timeout:
                    pass
                while True:
                    message = _extract_frame(buffer)
                    if message is None:
                        break
                    last_receive = time.monotonic()
                    try:
                        incoming_seq = int(message.get("34", "0"))
                    except ValueError:
                        incoming_seq = 0
                    if incoming_seq and expected_in and incoming_seq != expected_in:
                        raise ConnectionError(
                            f"Sequência FIX inesperada ({incoming_seq}; esperada {expected_in})."
                        )
                    if incoming_seq:
                        expected_in = incoming_seq + 1
                    msg_type = message.get("35")
                    if msg_type == "A":
                        logged_in = True
                        with self._lock:
                            self._state.update(
                                status="conectado",
                                message="FIX autenticado; assinando cotações do instrumento.",
                            )
                    elif msg_type == "1":
                        self._send(
                            sock,
                            "0",
                            target,
                            feed_sender,
                            [("112", message.get("112", ""))]
                            if message.get("112")
                            else [],
                        )
                    elif msg_type == "5":
                        raise ConnectionError("Sessão FIX encerrada pela corretora.")
                    elif msg_type == "3" or msg_type == "j":
                        reason = message.get("58", "Mensagem FIX rejeitada.")
                        raise ConnectionError(
                            f"A corretora rejeitou a sessão FIX: {reason[:180]}"
                        )
                    elif msg_type == "Y":
                        raise ConnectionError(
                            f"Assinatura de mercado rejeitada: {message.get('58', message.get('281', 'motivo não informado'))}"
                        )
                    elif msg_type == "W":
                        self._on_market_data(message)
                    if logged_in and not subscribed:
                        config = self.config_provider()
                        symbol = str(config.get("instrument", "EUR/USD"))
                        self._send(
                            sock,
                            "V",
                            target,
                            feed_sender,
                            [
                                ("262", f"md-{symbol.replace('/', '')}"),
                                ("263", "1"),
                                ("264", "1"),
                                ("265", "0"),
                                ("146", "1"),
                                ("55", symbol),
                                ("267", "2"),
                                ("269", "0"),
                                ("269", "1"),
                            ],
                        )
                        subscribed = True
                        with self._lock:
                            self._state.update(
                                status="conectado",
                                message=f"Assinatura ativa para {symbol}; aguardando bid/ask.",
                                instrument=symbol,
                            )
                now = time.monotonic()
                if now - last_receive > 90:
                    raise TimeoutError("Sem mensagens da corretora há 90 segundos.")
                if now - self._last_send >= 25:
                    self._send(sock, "0", target, feed_sender)
            try:
                self._send(sock, "5", target, feed_sender)
            except OSError:
                pass
        except Exception as exc:
            if not stop_event.is_set():
                # Never expose credentials or FIX payloads in status or logs.
                with self._lock:
                    self._state.update(status="erro", message=str(exc)[:240])
        finally:
            with self._lock:
                if self._socket is sock:
                    self._socket = None
                if stop_event.is_set() and self._state.get("status") != "erro":
                    self._state.update(
                        status="desconectado", message="Feed ao vivo parado."
                    )
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass

    def _on_market_data(self, message: dict[str, str]) -> None:
        symbol = message.get("55", "")
        config = self.config_provider()
        if symbol and symbol != config.get("instrument"):
            return
        bid = self._bid
        ask = self._ask
        entries: list[dict[str, str]] = []
        current: dict[str, str] | None = None
        for tag, value in message.get("_pairs", []):
            if tag == "269":
                current = {"type": value}
                entries.append(current)
            elif current is not None:
                current[tag] = value
        for entry in entries:
            try:
                price = float(entry.get("270", "nan"))
            except ValueError:
                continue
            if entry.get("type") == "0":
                bid = price
            elif entry.get("type") == "1":
                ask = price
        if bid is None or ask is None or bid <= 0 or ask < bid:
            return
        entry_time = (
            f"{message['272']}-{message['273']}"
            if message.get("272") and message.get("273")
            else None
        )
        timestamp = _fix_time(
            message.get("60") or entry_time or message.get("52"), message.get("272")
        )
        mid = (bid + ask) / 2
        seconds = TIMEFRAME_SECONDS.get(str(config.get("timeframe", "M5")), 300)
        epoch = timestamp.timestamp()
        bucket = int(epoch // seconds) * seconds
        closed: dict[str, Any] | None = None
        with self._lock:
            self._bid, self._ask = bid, ask
            self._state.update(
                ticks=int(self._state.get("ticks", 0)) + 1,
                last_tick_utc=timestamp.isoformat(),
                spread_pips=round(
                    (ask - bid) / float(config.get("pip_size", 0.0001)), 2
                ),
            )
            if self._bucket is not None and bucket < self._bucket:
                return
            if self._bucket is None or bucket > self._bucket:
                if self._bucket is not None and bucket - self._bucket > seconds * 2:
                    self._bars.clear()
                    self._events.clear()
                    self._analysis = {
                        "signal": "WAIT",
                        "message": "Pausa no feed detectada; reiniciando o aquecimento dos indicadores.",
                    }
                    self._jev_review = None
                if self._bar:
                    closed = dict(self._bar)
                    closed["volume"] = closed.get("tick_count", 0)
                    self._bars.append(closed)
                self._bucket = bucket
                self._bar = {
                    "timestamp": datetime.fromtimestamp(
                        bucket, timezone.utc
                    ).isoformat(),
                    "open": mid,
                    "high": mid,
                    "low": mid,
                    "close": mid,
                    "volume": 0,
                    "tick_count": 1,
                    "bid": bid,
                    "ask": ask,
                }
            else:
                self._bar["high"] = max(float(self._bar["high"]), mid)
                self._bar["low"] = min(float(self._bar["low"]), mid)
                self._bar["close"] = mid
                self._bar["tick_count"] = int(self._bar.get("tick_count", 0)) + 1
                self._bar["bid"] = bid
                self._bar["ask"] = ask
            self._state["latest_price"] = mid
        if closed:
            self._on_candle_close(closed, config)

    def _on_candle_close(self, candle: dict[str, Any], config: dict[str, Any]) -> None:
        with self._lock:
            candles = [dict(item) for item in self._bars]
            spread_pips = float(self._state.get("spread_pips", 0.0))
        signature = (
            config.get("instrument"),
            config.get("timeframe"),
            config.get("swing_window"),
            config.get("max_spread_pips"),
            config.get("pip_size"),
        )
        try:
            if getattr(self, "_intelligence_signature", None) != signature:
                self._intelligence = MarketIntelligenceSession(
                    symbol=str(config.get("instrument", "EUR/USD")),
                    hierarchy=HierarchyConfig.for_execution(
                        str(config.get("timeframe", "M5"))
                    ),
                    sessions=(
                        SessionWindow(
                            "london", "Europe/London", session_time(8), session_time(17)
                        ),
                        SessionWindow(
                            "new_york",
                            "America/New_York",
                            session_time(8),
                            session_time(17),
                        ),
                    ),
                    max_spread_pips=float(config.get("max_spread_pips", 1.5)),
                    pip_size=float(config.get("pip_size", 0.0001)),
                    swing_window=int(config.get("swing_window", 2)),
                )
                self._intelligence_signature = signature
            snapshot = self._intelligence.update(candles, spread_pips=spread_pips)
            eligibility = StrategyMetadata("legacy_indicator_research", "1").evaluate(
                snapshot
            )
            result = (
                analyze(candles, config)
                if eligibility["regime_match"]
                else {
                    "signal": "WAIT",
                    "reason_code": eligibility["reason"],
                    "message": "Regime incompatível com a pesquisa de tendência.",
                }
            )
            # Persist closed-bar observations before publishing them to the UI.
            from src.aurelia_fx.storage import open_memory

            if getattr(self, "_memory", None) is None:
                self._memory = open_memory()
            with self._memory.transaction():
                self._memory.record_project_data(
                    "strategy_evaluation",
                    snapshot.snapshot_id,
                    {
                        **eligibility,
                        "snapshot_id": snapshot.snapshot_id,
                        "regime_model_version": snapshot.regime_model_version,
                        "regime_config_hash": snapshot.regime_config_hash,
                        "market_location": snapshot.market_location,
                    },
                )
                self._memory.record_project_data(
                    "closed_candle",
                    f"dukascopy:{snapshot.symbol}:{snapshot.timeframe}:{candle['timestamp']}",
                    {
                        "source": "dukascopy_fix_mid",
                        "symbol": snapshot.symbol,
                        "timeframe": snapshot.timeframe,
                        "candle": candle,
                    },
                )
                self._memory.record_snapshot(
                    snapshot.as_dict(),
                    session="+".join(snapshot.session) or "outside_sessions",
                    regime=snapshot.market_regime,
                    data_reference="dukascopy_fix_mid",
                )
                self._memory.record_intelligence(snapshot.as_dict())
            result = observation_only_result(result, snapshot)
            result["strategy_regime_compatibility"] = eligibility
        except Exception:
            result = {
                "signal": "WAIT",
                "reason_code": "V4_DATA_OR_STORAGE_ERROR",
                "message": "Leitura V4 ou persistência indisponível. Verifique dados e conexão ao banco.",
                "orders_enabled_by_application": False,
            }
        with self._lock:
            self._analysis = result
            self._state["closed_candles"] = len(candles)
            self._state["last_closed_candle_utc"] = candle["timestamp"]
            if result.get("signal") in {"BUY", "SELL"}:
                self._jev_review = None
                self._events.appendleft(
                    {
                        "timestamp": candle["timestamp"],
                        "signal": result["signal"],
                        "side": result.get("side"),
                        "entry": result.get("entry"),
                        "stop": result.get("stop"),
                        "target": result.get("target"),
                        "score": result.get("score"),
                        "score_total": result.get("score_total"),
                        "message": "Candidato técnico detectado em candle fechado. Nenhuma ordem enviada.",
                    }
                )

    def set_jev_review(self, result: dict[str, Any], candle_time: str) -> None:
        with self._lock:
            self._jev_review = {**result, "candle_time": candle_time}
