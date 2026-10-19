"""Spec 07 (security audit): the server listens on 127.0.0.1 with no login,
so any web page the user visits can try to talk to it. One ASGI middleware
refuses, before any route runs:

- an unknown Host header (DNS rebinding: evil.example made to resolve to
  127.0.0.1 would otherwise be "same origin" for the attacker's page);
- an unsafe method (POST...) whose Origin is not this server's own (CSRF:
  a cross-site "simple" request, text/plain and no preflight, used to reach
  /api/config and point a provider at the attacker, who then received the
  API key). Browsers always send Origin there; a script or an IDE using the
  /v1 gateway sends none and passes;
- a cross-site or same-site browser request to /api or /v1, even a GET
  (Sec-Fetch-Site): an <img> on /api/skills?q= would spend embedding calls.

The sites the agents build are served sandboxed (routes/static.py), so their
scripts have an opaque origin ("null") and fall under the same rules.

Allowed hosts: the loopback names, the configured server.host unless it is a
wildcard, and AGENT_WORLD_ALLOWED_HOSTS (comma separated) for a LAN setup.

Spec 11 T02, the LAN: after those checks, a request that is not local needs
AGENT_WORLD_API_KEY on /api/*, /api/events and /v1/*. Local means a loopback
Host *and* a loopback peer address: the Host header is written by the client,
and a script on the LAN can write 127.0.0.1 (D7). The key comes as a Bearer
header (scripts) or as the session cookie the browser gets from POST
/api/session with the key (routes/session.py, D10): the cookie is not the key
but an expiry signed with it, so a new key logs everyone out. Without a key on
the server the LAN is refused (D8). The page itself (public/) loads anywhere:
it is the app's code, and it carries the login.

The refusals speak the language of the app (N13): `language` reads ui.language
at every refusal, so a switch in the UI applies at once."""

import hashlib
import hmac
import ipaddress
import json
import os
import time

from starlette.requests import cookie_parser

from backend.i18n import DEFAULT, http_error

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
FOREIGN_SITES = {"cross-site", "same-site"}

SESSION_COOKIE = "aw_session"
SESSION_DAYS = 7
SESSION_PATH = "/api/session"  # the login itself: reachable without the key


def allowed_hosts(config_host: str | None = None, env: str | None = None) -> set[str]:
    hosts = set(LOOPBACK)
    if config_host and config_host not in ("0.0.0.0", "::", ""):
        hosts.add(config_host.lower())
    for h in (env if env is not None else os.environ.get("AGENT_WORLD_ALLOWED_HOSTS", "")).split(","):
        if h.strip():
            hosts.add(h.strip().lower())
    return hosts


def host_name(host_header: str) -> str:
    """'127.0.0.1:4300' -> '127.0.0.1', '[::1]:4300' -> '::1', lower case."""
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1 : h.find("]")] if "]" in h else h
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def access_key() -> str:
    """AGENT_WORLD_API_KEY, read at every request: registering a provider reads
    .env again (spec 09), and a key changed there applies at once."""
    return os.environ.get("AGENT_WORLD_API_KEY", "")


def _loopback_peer(client) -> bool:
    if not client:
        return False
    try:
        ip = ipaddress.ip_address(str(client[0]).split("%")[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return ip.is_loopback or (mapped is not None and mapped.is_loopback)


def _headers(scope) -> dict[str, str]:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def is_local(scope, headers: dict[str, str] | None = None) -> bool:
    """A loopback Host and a loopback peer: this machine talking to itself (D7)."""
    h = _headers(scope) if headers is None else headers
    return host_name(h.get("host", "")) in LOOPBACK and _loopback_peer(scope.get("client"))


def _sign(key: str, exp: int) -> str:
    return hmac.new(key.encode(), f"agent-world-session:{exp}".encode(), hashlib.sha256).hexdigest()


def session_token(key: str, now: float | None = None) -> str:
    """'<expiry>.<HMAC-SHA256(key, expiry)>': no state on the server, so it lives
    through a restart; a stolen cookie expires and does not reveal the key."""
    exp = int((time.time() if now is None else now) + SESSION_DAYS * 86400)
    return f"{exp}.{_sign(key, exp)}"


def valid_session(key: str, token: str, now: float | None = None) -> bool:
    exp, dot, sig = (token or "").partition(".")
    if not (key and dot and sig and exp.isascii() and exp.isdigit()):
        return False
    if int(exp) <= (time.time() if now is None else now):
        return False
    return hmac.compare_digest(sig.encode(), _sign(key, int(exp)).encode())


def authorized(headers, key: str) -> bool:
    """The key as a Bearer header, or a valid session cookie. `headers` maps
    lower-case names (a dict, or Starlette's Headers)."""
    if not key:
        return False
    # spec 07: a constant-time comparison, so the answer time says nothing about the key
    if hmac.compare_digest(headers.get("authorization", "").encode(), f"Bearer {key}".encode()):
        return True
    return valid_session(key, cookie_parser(headers.get("cookie", "")).get(SESSION_COOKIE, ""))


class LocalGuard:
    def __init__(self, app, *, hosts: set[str], language=lambda: DEFAULT, key=access_key):
        self.app = app
        self.hosts = hosts
        self.language = language
        self.key = key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = _headers(scope)
        host = headers.get("host", "")
        if host_name(host) not in self.hosts:
            return await self._refuse(send, "refused_host")
        path = scope.get("path", "")
        api = path == "/api" or path.startswith("/api/") or path == "/v1" or path.startswith("/v1/")
        if api and headers.get("sec-fetch-site") in FOREIGN_SITES:
            return await self._refuse(send, "refused_site")
        origin = headers.get("origin")
        if scope.get("method") not in SAFE_METHODS and origin is not None and origin.lower() != f"{scope.get('scheme', 'http')}://{host}".lower():
            return await self._refuse(send, "refused_origin")
        # spec 11 T02: the API from the LAN only with the key (D7, D8)
        if api and path != SESSION_PATH and not is_local(scope, headers):
            key = self.key()
            if not key:
                return await self._refuse(send, "lan_needs_key")
            if not authorized(headers, key):
                return await self._refuse(send, "auth_required", status=401, extra=[(b"www-authenticate", b'Bearer realm="agent-world"')])
        return await self.app(scope, receive, send)

    async def _refuse(self, send, key: str, *, status: int = 403, extra=()) -> None:
        body = json.dumps({"error": http_error(self.language(), key)}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *extra]})
        await send({"type": "http.response.body", "body": body})
