"""Loopback-only local web server for the Forex analysis workbench."""

from __future__ import annotations

import json
import re
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from backtest import run_backtest
from learning import append_outcomes, train_model
from learning import ENTRY_PROBABILITY_FLOOR, features_from_signal, predict_win_probability
from security import load_credentials, save_credentials
from typesafe_jev import review_entry
from dukascopy_feed import DukascopyFeed
from mt5_provider import fetch_history as mt5_fetch_history, status as mt5_status
from strategy_optimizer import optimize_history


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = ROOT / "data"
CONFIG_PATH = DATA / "user_config.json"
SECRETS_PATH = DATA / "credentials.dpapi"
TYPESAFE_PATH = DATA / "typesafe.dpapi"
DUKASCOPY_PATH = DATA / "dukascopy_fix.dpapi"
DECISION_MODEL_PATH = DATA / "decision_model.json"
LEARNING_PATH = DATA / "decision_history.json"
HOST = "127.0.0.1"
PORT = 8768
LOCAL_TOKEN = secrets.token_urlsafe(32)
CONFIG_LOCK = threading.Lock()
LEARNING_LOCK = threading.Lock()

DEFAULT_CONFIG = json.loads((DATA / "default_config.json").read_text(encoding="utf-8"))
NUMBER_RANGES = {
    "risk_per_trade_pct": (0.05, 2.0),
    "max_daily_loss_pct": (0.1, 10.0),
    "max_drawdown_pct": (1.0, 30.0),
    "max_open_positions": (1, 10),
    "max_trades_per_day": (1, 100),
    "max_spread_pips": (0, 20),
    "max_slippage_pips": (0, 10),
    "minimum_risk_reward": (1.0, 10.0),
    "minimum_confluence": (1, 11),
    "ema_fast": (3, 200),
    "ema_slow": (5, 500),
    "rsi_period": (3, 50),
    "rsi_long_min": (1, 99),
    "rsi_long_max": (1, 99),
    "rsi_short_min": (1, 99),
    "rsi_short_max": (1, 99),
    "adx_period": (3, 50),
    "adx_min": (1, 80),
    "atr_period": (3, 100),
    "atr_min_pct": (0, 20),
    "atr_max_pct": (0.01, 50),
    "swing_window": (2, 10),
    "pullback_min_pct": (0, 99),
    "pullback_max_pct": (1, 100),
    "fib_zone_min_pct": (0, 99),
    "fib_zone_max_pct": (1, 100),
    "stop_atr_buffer": (0, 5),
    "maximum_bars_in_trade": (1, 500),
    "pip_size": (0.000001, 1),
    "starting_balance": (100, 100000000),
}
BOOLEAN_FIELDS = {
    "trend_filter", "pullback_filter", "volume_filter", "smc_filter", "wyckoff_filter",
    "rsi_filter", "macd_filter", "adx_filter", "atr_filter", "talib_patterns_filter",
}
STRING_FIELDS = {"instrument", "timeframe", "account_currency", "broker", "mode"}
TIMEFRAMES = {"M5", "M15", "M30", "H1", "H4", "D1"}
BROKERS = {
    "paper": "Simulador local",
    "interactive_brokers": "Interactive Brokers / NautilusTrader",
    "mt5_community": "MetaTrader 5 (adaptador da comunidade)",
    "custom": "Adaptador próprio",
}


def load_config() -> dict[str, Any]:
    with CONFIG_LOCK:
        if CONFIG_PATH.exists():
            try:
                saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return {**DEFAULT_CONFIG, **saved}
            except (json.JSONDecodeError, OSError):
                pass
        return dict(DEFAULT_CONFIG)


def load_active_model() -> dict[str, Any] | None:
    try:
        stored = json.loads(DECISION_MODEL_PATH.read_text(encoding="utf-8"))
        model = stored.get("model") if stored.get("promoted") else None
        return model if isinstance(model, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


LIVE_FEED = DukascopyFeed(load_config, load_active_model)


def learning_rows(instrument: str, timeframe: str, source: str | None = None) -> list[dict[str, Any]]:
    if not LEARNING_PATH.exists():
        return []
    try:
        rows = json.loads(LEARNING_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(rows, list):
        return []
    return [
        row for row in rows
        if isinstance(row, dict)
        and row.get("instrument") == instrument
        and row.get("timeframe") == timeframe
        and (source is None or row.get("source", "csv") == source)
        and (source != "mt5" or row.get("evaluation_scope") == "treino")
    ]


def save_config(config: dict[str, Any]) -> None:
    with CONFIG_LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        temp = CONFIG_PATH.with_suffix(".tmp")
        temp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(CONFIG_PATH)


def sanitize_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_config()
    for key, value in payload.items():
        if key in STRING_FIELDS:
            if not isinstance(value, str) or len(value) > 40:
                raise ValueError(f"Valor inválido para {key}.")
            if key == "instrument" and not re.fullmatch(r"[A-Z]{3}/[A-Z]{3}", value.upper()):
                raise ValueError("Use o formato de par Forex, por exemplo EUR/USD.")
            if key == "timeframe" and value.upper() not in TIMEFRAMES:
                raise ValueError("Período gráfico não suportado.")
            if key == "broker" and value not in BROKERS:
                raise ValueError("Corretora não cadastrada.")
            if key == "mode" and value != "paper":
                raise ValueError("Execução live desativada neste build.")
            current[key] = value.upper() if key in {"instrument", "timeframe", "account_currency"} else value
        elif key in BOOLEAN_FIELDS:
            if not isinstance(value, bool):
                raise ValueError(f"Valor inválido para {key}.")
            current[key] = value
        elif key in NUMBER_RANGES:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Valor numérico inválido para {key}.")
            low, high = NUMBER_RANGES[key]
            if not low <= float(value) <= high:
                raise ValueError(f"{key} deve ficar entre {low} e {high}.")
            current[key] = int(value) if key in {"max_open_positions", "max_trades_per_day", "minimum_confluence", "ema_fast", "ema_slow", "rsi_period", "adx_period", "atr_period", "swing_window", "maximum_bars_in_trade"} else float(value)
        else:
            raise ValueError(f"Configuração desconhecida: {key}.")
    if current["ema_fast"] >= current["ema_slow"]:
        raise ValueError("EMA rápida precisa ser menor que a EMA lenta.")
    if current["rsi_long_min"] >= current["rsi_long_max"] or current["rsi_short_min"] >= current["rsi_short_max"]:
        raise ValueError("A faixa mínima do RSI precisa ser menor que a máxima.")
    if current["atr_min_pct"] >= current["atr_max_pct"]:
        raise ValueError("ATR mínimo precisa ser menor que o ATR máximo.")
    if current["pullback_min_pct"] >= current["pullback_max_pct"]:
        raise ValueError("Retração mínima precisa ser menor que a máxima.")
    if current["fib_zone_min_pct"] >= current["fib_zone_max_pct"]:
        raise ValueError("Faixa Fibonacci mínima precisa ser menor que a máxima.")
    if current["mode"] != "paper":
        raise ValueError("Execução live desativada. A integração da corretora e as salvaguardas ainda precisam ser validadas.")
    return current


class Handler(BaseHTTPRequestHandler):
    server_version = "AureliaFX/0.1"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        # Do not include request bodies, which may contain credentials.
        print(f"{self.address_string()} {self.command} {self.path}")

    def _send(self, code: int, payload: dict[str, Any], content_type: str = "application/json; charset=utf-8") -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if content_type.startswith("application/json") else payload["bytes"]
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        raw_length = int(self.headers.get("Content-Length", "0"))
        if raw_length <= 0 or raw_length > 2_500_000:
            raise ValueError("Tamanho de solicitação inválido.")
        payload = json.loads(self.rfile.read(raw_length))
        if not isinstance(payload, dict):
            raise ValueError("O corpo precisa ser um objeto JSON.")
        return payload

    def _guard_local(self) -> None:
        host = self.headers.get("Host", "").lower()
        allowed_hosts = {f"{HOST}:{PORT}", f"localhost:{PORT}"}
        if host not in allowed_hosts:
            raise PermissionError("Apenas acesso local é aceito.")
        origin = self.headers.get("Origin")
        if origin and origin.lower() not in {f"http://{HOST}:{PORT}", f"http://localhost:{PORT}"}:
            raise PermissionError("Origem não autorizada.")
        if self.headers.get("X-Local-Token") != LOCAL_TOKEN:
            raise PermissionError("Token local ausente ou inválido.")

    def do_GET(self) -> None:
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/api/mt5/chart":
            query = parse_qs(parsed_url.query)
            timeframe = query.get("timeframe", ["M5"])[0].upper()
            try:
                count = max(100, min(2_000, int(query.get("count", ["600"])[0])))
                result = mt5_fetch_history("EUR/USD", timeframe, count, include_current=True)
                self._send(200, {"ok": True, **result})
            except (RuntimeError, ValueError) as exc:
                self._send(503, {"ok": False, "error": str(exc)})
            return
        if path == "/api/state":
            config = load_config()
            market = LIVE_FEED.snapshot()
            mt5_rows = learning_rows(config["instrument"], config["timeframe"], "mt5")
            model_rows = mt5_rows or learning_rows(config["instrument"], config["timeframe"], "csv")
            _, model_status = train_model(model_rows)
            model_status["source"] = "mt5" if mt5_rows else "csv"
            self._send(200, {
                "csrf": LOCAL_TOKEN,
                "config": config,
                "brokers": BROKERS,
                "credentials_saved": SECRETS_PATH.exists(),
                "typesafe_configured": TYPESAFE_PATH.exists(),
                "dukascopy_configured": DUKASCOPY_PATH.exists(),
                "market": LIVE_FEED.snapshot(),
                "learning_status": model_status,
                "mode": "paper",
                "market_status": market["status"],
                "nautilus_version": "2.0.0rc7",
                "message": "Painel local pronto. O feed Dukascopy FIX opera somente em leitura.",
            })
            return
        if path == "/api/market":
            self._send(200, LIVE_FEED.snapshot())
            return
        if path == "/api/mt5/status":
            try:
                self._send(200, mt5_status())
            except (RuntimeError, ValueError) as exc:
                self._send(200, {"connected": False, "message": str(exc), "orders_enabled_by_application": False})
            return
        if path == "/INTEGRATION_NAUTILUS.md":
            candidate = ROOT / "INTEGRATION_NAUTILUS.md"
            content_type = "text/markdown; charset=utf-8"
            safe_root = ROOT.resolve()
        else:
            relative = "index.html" if path == "/" else path.lstrip("/")
            candidate = (STATIC / relative).resolve()
            content_type = "text/html; charset=utf-8" if candidate.suffix == ".html" else "text/css; charset=utf-8" if candidate.suffix == ".css" else "text/javascript; charset=utf-8" if candidate.suffix == ".js" else "application/octet-stream"
            safe_root = STATIC.resolve()
        if not candidate.resolve().is_relative_to(safe_root) or not candidate.is_file():
            self._send(404, {"error": "Arquivo não encontrado."})
            return
        self._send(200, {"bytes": candidate.read_bytes()}, content_type)

    def do_POST(self) -> None:
        try:
            self._guard_local()
            payload = self._read_json()
            path = urlparse(self.path).path
            if path == "/api/config":
                previous = load_config()
                config = sanitize_config(payload)
                save_config(config)
                if any(previous.get(key) != config.get(key) for key in ("instrument", "timeframe")):
                    LIVE_FEED.stop()
                self._send(200, {"ok": True, "config": config})
                return
            if path == "/api/dukascopy/settings":
                host = str(payload.get("host", "")).strip()
                port = str(payload.get("port", "")).strip()
                values = {
                    "host": host[:253],
                    "port": port[:5],
                    "target_comp_id": str(payload.get("target_comp_id", "")).strip()[:64],
                    "feed_sender_comp_id": str(payload.get("feed_sender_comp_id", "")).strip()[:64],
                    "username": str(payload.get("username", ""))[:128],
                    "password": str(payload.get("password", ""))[:256],
                }
                try:
                    port_number = int(values["port"])
                except ValueError:
                    raise ValueError("Informe a porta FIX fornecida pela Dukascopy.") from None
                if not values["host"] or not 1 <= port_number <= 65535:
                    raise ValueError("Informe um host e uma porta FIX válidos.")
                if not all(values[key] for key in ("target_comp_id", "feed_sender_comp_id", "username", "password")):
                    raise ValueError("Preencha os identificadores e credenciais FIX fornecidos pela Dukascopy.")
                save_credentials(DUKASCOPY_PATH, values)
                self._send(200, {"ok": True, "saved": True, "message": "Parâmetros FIX protegidos localmente. Nenhuma conexão foi iniciada."})
                return
            if path == "/api/market/connect":
                if not DUKASCOPY_PATH.exists():
                    raise ValueError("Configure os dados de acesso FIX da Dukascopy antes de conectar.")
                settings = load_credentials(DUKASCOPY_PATH)
                LIVE_FEED.start(settings)
                self._send(200, {"ok": True, "message": "Conexão de leitura iniciada. Acompanhe o estado do feed no painel."})
                return
            if path == "/api/market/disconnect":
                LIVE_FEED.stop()
                self._send(200, {"ok": True, "message": "Feed de mercado desconectado."})
                return
            if path == "/api/market/jev-review":
                if not TYPESAFE_PATH.exists():
                    raise ValueError("Configure a chave TypeSafe no Caderno de pesquisa antes de ativar a revisão automática do Jev.")
                market = LIVE_FEED.snapshot()
                candles = market.get("candles", [])
                if market.get("analysis", {}).get("signal") not in {"BUY", "SELL"} or not candles:
                    raise ValueError("Não há candidato técnico fechado para o Jev revisar.")
                config = load_config()
                secret = load_credentials(TYPESAFE_PATH).get("api_key", "")
                result = review_entry(candles, config, secret)
                LIVE_FEED.set_jev_review(result, candles[-1]["timestamp"])
                self._send(200, {"ok": True, "result": result})
                return
            if path == "/api/credentials":
                provider = payload.get("provider")
                if provider not in BROKERS or provider == "paper":
                    raise ValueError("Selecione uma conexão compatível.")
                values = {key: str(payload.get(key, ""))[:2048] for key in ("api_key", "api_secret", "access_token", "account_id", "host", "port", "client_id", "login_type")}
                if not any(values.values()):
                    raise ValueError("Informe pelo menos um dado de conexão.")
                save_credentials(SECRETS_PATH, {"provider": provider, "values": values})
                self._send(200, {"ok": True, "saved": True, "storage": "DPAPI - usuário atual do Windows", "message": "Credenciais criptografadas localmente. Nenhuma conexão ou ordem foi iniciada."})
                return
            if path == "/api/typesafe/key":
                api_key = payload.get("api_key")
                if not isinstance(api_key, str) or len(api_key.strip()) < 12 or len(api_key) > 512:
                    raise ValueError("Informe uma chave de API TypeSafe válida.")
                save_credentials(TYPESAFE_PATH, {"api_key": api_key.strip()})
                self._send(200, {"ok": True, "saved": True, "message": "Chave TypeSafe criptografada localmente com DPAPI."})
                return
            if path == "/api/jev/review":
                candles = payload.get("candles")
                if not isinstance(candles, list) or not candles:
                    raise ValueError("Envie candles OHLCV para revisar o cenário atual.")
                if not TYPESAFE_PATH.exists():
                    raise ValueError("Salve sua chave TypeSafe no Caderno de pesquisa antes de pedir uma revisão ao Jev.")
                config = sanitize_config(payload.get("config", {}))
                secret = load_credentials(TYPESAFE_PATH).get("api_key", "")
                result = review_entry(candles, config, secret)
                self._send(200, {"ok": True, "result": result})
                return
            if path == "/api/backtest":
                candles = payload.get("candles")
                if not isinstance(candles, list) or not candles:
                    raise ValueError("Envie candles OHLCV carregados de um CSV.")
                if len(candles) > 20_000:
                    raise ValueError("O limite do CSV é de 20.000 candles.")
                config = sanitize_config(payload.get("config", {}))
                with LEARNING_LOCK:
                    prior_rows = learning_rows(config["instrument"], config["timeframe"], "csv")
                    learned_model, _ = train_model(prior_rows)
                    result = run_backtest(candles, config, float(payload.get("starting_balance", config["starting_balance"])), learned_model)
                    new_outcomes = append_outcomes(LEARNING_PATH, result["trades"], config["instrument"], config["timeframe"], "csv")
                    _, learning_status = train_model(learning_rows(config["instrument"], config["timeframe"], "csv"))
                learning_status["new_outcomes"] = new_outcomes
                result["learning"] = learning_status
                self._send(200, {"ok": True, "result": result})
                return
            if path == "/api/mt5/backtest":
                config = sanitize_config(payload.get("config", {}))
                count = int(payload.get("count", 100_000))
                history = mt5_fetch_history(config["instrument"], config["timeframe"], count)
                config["pip_size"] = history["pip_size"]
                with LEARNING_LOCK:
                    candles = history["candles"]
                    split = int(len(candles) * 0.70)
                    starting_balance = float(payload.get("starting_balance", config["starting_balance"]))
                    training_result = run_backtest(candles[:split], config, starting_balance, None)
                    # Evaluate only the final 30%, with earlier candles retained as indicator warm-up.
                    result = run_backtest(candles, config, starting_balance, None, evaluation_start=split)
                    new_outcomes = append_outcomes(
                        LEARNING_PATH, training_result["trades"], config["instrument"], config["timeframe"],
                        "mt5", "treino",
                    )
                    _, learning_status = train_model(learning_rows(config["instrument"], config["timeframe"], "mt5"))
                learning_status["new_outcomes"] = new_outcomes
                learning_status["source"] = "mt5"
                learning_status["historical_replay_used_prior_model"] = False
                result["learning"] = learning_status
                result["training_metrics"] = training_result["metrics"]
                result["validation_split_pct"] = 70
                result["validation_trades_are_training_data"] = False
                result["data_source"] = {key: value for key, value in history.items() if key != "candles"}
                result["source_candles"] = len(history["candles"])
                self._send(200, {"ok": True, "result": result})
                return
            if path == "/api/mt5/optimize":
                config = sanitize_config(payload.get("config", {}))
                count = int(payload.get("count", 100_000))
                history = mt5_fetch_history(config["instrument"], config["timeframe"], count)
                config["pip_size"] = history["pip_size"]
                result = optimize_history(
                    history["candles"], config, DATA,
                    float(payload.get("starting_balance", config["starting_balance"])),
                    {key: value for key, value in history.items() if key != "candles"},
                )
                if result["optimization"]["promoted"]:
                    promoted_config = {**config, **result["optimization"]["selected_config"]}
                    save_config(promoted_config)
                    result["optimization"]["selected_config"] = promoted_config
                self._send(200, {"ok": True, "result": result})
                return
            self._send(404, {"error": "Rota não encontrada."})
        except PermissionError as exc:
            self._send(403, {"error": str(exc)})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._send(400, {"error": str(exc)})
        except Exception as exc:
            # Avoid returning exception details which might reveal secret payloads.
            self._send(500, {"error": "Falha interna ao processar a solicitação.", "type": type(exc).__name__})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    print(f"Aurelia FX disponível em http://{HOST}:{PORT}")
    print("Feed Dukascopy FIX somente para leitura; nenhuma ordem será enviada.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
