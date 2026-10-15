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
wildcard, and AGENT_WORLD_ALLOWED_HOSTS (comma separated) for a LAN setup."""

import json
import os

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
FOREIGN_SITES = {"cross-site", "same-site"}


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


class LocalGuard:
    def __init__(self, app, *, hosts: set[str]):
        self.app = app
        self.hosts = hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        host = headers.get("host", "")
        if host_name(host) not in self.hosts:
            return await _refuse(send, "Host non ammesso")
        path = scope.get("path", "")
        api = path == "/api" or path.startswith("/api/") or path == "/v1" or path.startswith("/v1/")
        if api and headers.get("sec-fetch-site") in FOREIGN_SITES:
            return await _refuse(send, "Richiesta da un altro sito")
        origin = headers.get("origin")
        if scope.get("method") not in SAFE_METHODS and origin is not None and origin.lower() != f"{scope.get('scheme', 'http')}://{host}".lower():
            return await _refuse(send, "Origine non ammessa")
        return await self.app(scope, receive, send)


async def _refuse(send, why: str) -> None:
    body = json.dumps({"error": f"Richiesta rifiutata: {why}"}).encode()
    await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})
