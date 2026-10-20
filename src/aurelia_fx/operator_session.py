"""Server-side operator sessions; credentials never enter frontend storage."""

from __future__ import annotations

import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie

from .operator_auth import authorized


class OperatorSessions:
    def __init__(self, credential):
        self.credential = credential
        self.sessions = {}
        self.attempts = {}
        self.lock = threading.Lock()

    def login(self, password, ip):
        now = time.monotonic()
        with self.lock:
            self.attempts = {k: v for k, v in self.attempts.items() if now - v[0] < 900}
            self.sessions = {k: v for k, v in self.sessions.items() if v > now}
            failed = self.attempts.get(ip, (now, 0))
            if failed[1] >= 10:
                raise ValueError("Muitas tentativas. Aguarde 15 minutos.")
            if (
                not isinstance(password, str)
                or not password.isascii()
                or not authorized(password, self.credential)
            ):
                self.attempts[ip] = (failed[0], failed[1] + 1)
                raise ValueError("Credencial de acesso inválida.")
            self.attempts.pop(ip, None)
            token = secrets.token_urlsafe(32)
            self.sessions[token] = now + 8 * 3600
        return (
            "aurelia_operator="
            + token
            + "; HttpOnly; SameSite=Strict; Path=/api/diagnostics/; Max-Age=28800"
        )

    def authenticated(self, header):
        cookie = SimpleCookie()
        try:
            cookie.load(header or "")
            token = cookie["aurelia_operator"].value
        except (CookieError, KeyError, ValueError):
            return False
        with self.lock:
            return self.sessions.get(token, 0) > time.monotonic()

    def logout(self, header):
        cookie = SimpleCookie()
        try:
            cookie.load(header or "")
            token = cookie["aurelia_operator"].value
        except (CookieError, KeyError, ValueError):
            token = ""
        with self.lock:
            self.sessions.pop(token, None)
        return "aurelia_operator=; HttpOnly; SameSite=Strict; Path=/api/diagnostics/; Max-Age=0"
