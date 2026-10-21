"""Versioned broker wall-clock conversion, verified against advancing live ticks.

MT5 APIs may return actual UTC epochs or broker wall-clock labels encoded as epochs.
Only explicit broker profiles may use the second interpretation. Never infer an
arbitrary timezone from a single potentially stale quote.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

CONTRACT = "mt5-utc-v1"
NY = ZoneInfo("America/New_York")


class ClockUnavailable(RuntimeError):
    pass


class ClockCalibrationPending(ClockUnavailable):
    pass


@dataclass(frozen=True)
class ClockProfile:
    name: str
    broker_wall: bool


def profile_for(broker: str, server: str) -> ClockProfile:
    if server.lower().startswith("thinkmarkets-") and any(
        s in broker.lower() for s in ("tf global markets", "thinkmarkets")
    ):
        return ClockProfile("thinkmarkets-ny-close-v1", True)
    return ClockProfile("documented-api-utc-v1", False)


def broker_offset(utc: datetime) -> int:
    # NY close at 17:00 corresponds to broker midnight (NY + seven hours).
    return int((utc.astimezone(NY).utcoffset() + timedelta(hours=7)).total_seconds())


def wall_to_utc(epoch: int) -> datetime:
    label = datetime.fromtimestamp(epoch, timezone.utc)
    candidates = [
        label - timedelta(seconds=offset)
        for offset in (7200, 10800)
        if broker_offset(label - timedelta(seconds=offset)) == offset
    ]
    if len(candidates) != 1:
        raise ClockUnavailable(
            "Horário de origem ambíguo/inexistente na mudança de DST; captura bloqueada."
        )
    return candidates[0]


class MT5Clock:
    def __init__(self, path: Path):
        self.path = path
        self.probes = {}

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            sources = (
                data.get("sources", {})
                if isinstance(data, dict) and data.get("contract") == CONTRACT
                else {}
            )
            return sources if isinstance(sources, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def _save(self, identity, record):
        sources = self._load()
        sources[identity] = record
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + "." + str(uuid4()) + ".tmp")
        try:
            tmp.write_text(
                json.dumps({"contract": CONTRACT, "sources": sources}, sort_keys=True),
                encoding="utf-8",
            )
            # Windows sharing locks (including sync/antivirus readers) can briefly
            # deny atomic replacement. Preserve the old file and retry boundedly.
            for attempt in range(8):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt==7:
                        raise ClockUnavailable('Arquivo do relógio temporariamente ocupado; nova tentativa automática.') from None
                    time.sleep(min(.02*2**attempt,.2))
        except OSError as exc:
            raise ClockUnavailable('Não foi possível persistir a validação do relógio; nova tentativa automática.') from exc
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    @staticmethod
    def convert(epoch, mode):
        try:
            if mode == "utc":
                return datetime.fromtimestamp(int(epoch), timezone.utc)
            if mode == "broker_wall":
                return wall_to_utc(int(epoch))
        except (ValueError, OverflowError, OSError):
            raise ClockUnavailable(
                "Timestamp de origem fora do intervalo suportado."
            ) from None
        raise ClockUnavailable("Interpretação de horário não suportada.")

    def resolve(self, broker, server, tick_epoch, *, now=None):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("Relógio de referência precisa ser UTC aware.")
        now = now.astimezone(timezone.utc)
        if (
            not isinstance(broker, str)
            or not isinstance(server, str)
            or not broker
            or not server
        ):
            raise ClockUnavailable("Identidade do servidor MT5 indisponível.")
        profile = profile_for(broker, server)
        identity = hashlib.sha256(
            f"{broker}\0{server}\0{profile.name}".encode()
        ).hexdigest()[:24]
        if (
            not isinstance(tick_epoch, (int, float))
            or not math.isfinite(tick_epoch)
            or tick_epoch <= 0
        ):
            raise ClockUnavailable("Aguardando tick válido do terminal MT5.")
        cached = self._load().get(identity, {})
        if not isinstance(cached, dict):
            cached = {}
        fresh = []
        for mode in ("utc", "broker_wall") if profile.broker_wall else ("utc",):
            try:
                stamp = self.convert(tick_epoch, mode)
            except ClockUnavailable:
                continue
            if -5 <= (now - stamp).total_seconds() <= 30:
                fresh.append(mode)
        mode = fresh[0] if len(fresh) == 1 else None
        verified = False
        if mode:
            try:
                age = (
                    now - datetime.fromisoformat(cached["verified_at"])
                ).total_seconds()
                cached_valid = cached["mode"] == mode and 0 <= age <= 7 * 86400
            except (KeyError, TypeError, ValueError):
                cached_valid = False
            previous = self.probes.get(identity)
            if (
                previous is None
                or previous[2] != mode
                or (now - previous[1]).total_seconds() > 60
            ):
                self.probes[identity] = (tick_epoch, now, mode)
            advancing = bool(
                previous
                and previous[2] == mode
                and tick_epoch > previous[0]
                and 1 <= (now - previous[1]).total_seconds() <= 60
                and abs(
                    (tick_epoch - previous[0]) - (now - previous[1]).total_seconds()
                )
                <= 10
            )
            if not (cached_valid or advancing):
                raise ClockCalibrationPending(
                    "Calibrando relógio MT5: aguardando outro tick recente e crescente; nova tentativa automática."
                )
            verified = True
            self._save(
                identity,
                {
                    "mode": mode,
                    "profile": profile.name,
                    "tick_epoch": int(tick_epoch),
                    "verified_at": now.isoformat(),
                },
            )
        else:
            try:
                age = (
                    now - datetime.fromisoformat(cached["verified_at"])
                ).total_seconds()
                mode = cached["mode"]
                allowed = mode == "utc" or (
                    profile.broker_wall and mode == "broker_wall"
                )
                valid = (
                    allowed
                    and 0 <= age <= 7 * 86400
                    and cached["tick_epoch"] == int(tick_epoch)
                )
            except (KeyError, TypeError, ValueError):
                valid = False
            if not valid:
                self.probes.pop(identity, None)
                raise ClockUnavailable(
                    "Relógio MT5 não validado: tick atrasado, fonte alterada ou fuso não configurado. Nova tentativa automática."
                )
        stamp = self.convert(tick_epoch, mode)
        return {
            "contract": CONTRACT,
            "clock_id": identity + ":" + mode,
            "profile": profile.name,
            "mode": mode,
            "broker": broker,
            "server": server,
            "normalized_to": "UTC",
            "verified_current": verified,
            "status": "verified" if verified else "cached_stale_quote",
            "verified_at": now.isoformat() if verified else cached["verified_at"],
            "response_at_utc": now.isoformat(),
            "raw_tick_epoch": int(tick_epoch),
            "tick_utc": stamp.isoformat(),
            "offset_seconds": int(tick_epoch - stamp.timestamp()),
            "quote_age_seconds": (now - stamp).total_seconds(),
        }

    def normalize_bars(self, bars, clock, *, now=None):
        now = now or datetime.now(timezone.utc)
        result = []
        last = None
        for bar in bars:
            raw = int(bar["time"])
            stamp = self.convert(raw, clock["mode"])
            if stamp > now + timedelta(seconds=5) or (
                last is not None and stamp <= last
            ):
                raise ClockUnavailable(
                    "Candles futuros ou fora de ordem após conversão UTC; captura bloqueada."
                )
            offset = int(raw - stamp.timestamp())
            result.append((stamp.isoformat(), raw, offset))
            last = stamp
        return result
