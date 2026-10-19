"""Spec 11 T02: /api/session, how a browser on the LAN gets in (D10).

GET says whether this request needs the key and has it, plus the app's
language: the page asks it before anything else, and shows its login in that
language, since /api/config is closed to it until then. POST checks the key
(constant time) and sets the session cookie: HttpOnly (no script reads it),
SameSite=Strict (no other site sends it), Path=/, SESSION_DAYS long. Both are
reachable without the key (security.SESSION_PATH); the spec 07 checks still
apply, so another site can neither sign the browser in nor probe the key."""

import hmac

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.i18n import http_error, ui_language
from backend.security import SESSION_COOKIE, SESSION_DAYS, access_key, authorized, is_local, session_token


def mount(app, *, config) -> None:
    def _err(status: int, key: str) -> JSONResponse:
        return JSONResponse({"error": http_error(ui_language(config.get()), key)}, status_code=status)

    @app.get("/api/session")
    async def api_session(request: Request):
        local = is_local(request.scope)
        key = access_key()
        return {"local": local, "keyRequired": not local, "keySet": bool(key), "authenticated": local or authorized(request.headers, key), "language": ui_language(config.get())}

    @app.post("/api/session")
    async def api_session_open(request: Request):
        key = access_key()
        if not key:
            return _err(403, "lan_needs_key")
        try:
            body = await request.json()
        except ValueError:  # not JSON, or not UTF-8: a wrong key, never a 500
            body = None
        given = body.get("key") if isinstance(body, dict) else None
        if not isinstance(given, str) or not hmac.compare_digest(given.encode(), key.encode()):
            return _err(401, "auth_wrong")
        res = JSONResponse({"ok": True})
        res.set_cookie(SESSION_COOKIE, session_token(key), max_age=SESSION_DAYS * 86400, path="/", httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return res
