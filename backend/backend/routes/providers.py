"""Spec 09 §1.2: an OpenAI-compatible provider, or one more model of a known
one, registered from the Settings while the server runs.

The provider goes to the preferences (local.json, "custom": true), its models
to the combos; the router reads the config at every call, so no restart. Keys
never travel in a request: they stay in .env, which the registration reads
again for the variables not known yet (env.load_env never overwrites one).

Spec 07 holds: whoever reaches /api controls the config, so a registration
must not be a way to send a key somewhere else -- https (http only to this
computer), no credentials in the URL, and a key variable of its own."""

import ipaddress
import re
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.env import load_env
from backend.router import profiler

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/@+\-]{1,120}$")
RESERVED_KEYS = {"GITHUB_TOKEN"}
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _loopback(host: str) -> bool:
    if host in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_url(url) -> str | None:
    """The reason a base URL is refused, or None."""
    if not isinstance(url, str) or not url.strip():
        return "Serve l'URL base del provider (https://...)."
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return "URL non valido."
    if u.username or u.password or "@" in u.netloc:
        return "Niente credenziali nell'URL: la chiave va in .env."
    if u.query or u.fragment:
        return "L'URL base non può avere parametri o frammenti."
    host = (u.hostname or "").lower()
    if not host:
        return "URL non valido: manca l'host."
    if u.scheme == "https" or (u.scheme == "http" and _loopback(host)):
        return None
    return "Serve https (http solo verso questo computer: 127.0.0.1, localhost)."


def check_key(name, providers: dict, own_id: str) -> str | None:
    if not isinstance(name, str) or not KEY_RE.match(name) or not (name.endswith("_KEY") or name.endswith("_TOKEN")):
        return "La variabile della chiave deve essere in MAIUSCOLO e finire con _KEY o _TOKEN (es. MYPROVIDER_API_KEY)."
    if name.startswith("AGENT_WORLD_") or name in RESERVED_KEYS:
        return f"{name} non è la chiave di un provider: scegline una sua."
    for pid, p in providers.items():
        if pid != own_id and p.get("keyEnv") == name:
            return f"{name} è già la chiave di {pid}: un provider nuovo ne usa una sua, o quella chiave andrebbe a un altro server."
    return None


def mount(app, *, config, router, bus=None, env_file) -> None:
    @app.post("/api/providers")
    async def api_provider_add(request: Request):
        body = await request.json()
        cfg = config.get()
        pid = str(body.get("id") or "").strip()
        if not ID_RE.match(pid) or pid == "mock":
            return _err("id del provider non valido: lettere minuscole, cifre e trattini (es. my-llm).")
        models = body.get("models")
        if not isinstance(models, list) or not models or len(models) > 20 or any(not isinstance(m, str) or not MODEL_RE.match(m) for m in models):
            return _err("Indica da 1 a 20 modelli, senza spazi (es. llama-3.3-70b).")
        combos = body.get("combos")
        if combos is not None and (not isinstance(combos, list) or any(c not in cfg["combos"] for c in combos)):
            bad = [c for c in (combos if isinstance(combos, list) else [combos]) if c not in cfg["combos"]]
            return _err(f"Combo sconosciute: {', '.join(map(str, bad))}.")
        known = cfg["providers"].get(pid)
        media_keys = {f"media:{k}": v for k, v in (cfg.get("media") or {}).get("providers", {}).items()}
        if known is not None and not known.get("custom"):
            # a shipped provider takes new models, never a new URL or key variable
            for field in ("baseUrl", "keyEnv"):
                if body.get(field) not in (None, known.get(field)):
                    return _err(f"{pid} è un provider di serie: puoi aggiungergli modelli, non cambiarne {field}.")
            entry = None
        else:
            why = check_url(body.get("baseUrl"))
            if why:
                return _err(why)
            keyless = bool(body.get("keyless"))
            key = body.get("keyEnv")
            if not keyless or key:
                why = check_key(key, {**cfg["providers"], **media_keys}, pid)
                if why:
                    return _err(why)
            entry = {"kind": "openai", "baseUrl": body["baseUrl"].strip().rstrip("/")}
            if key:
                entry["keyEnv"] = key
            if keyless:
                entry["keyless"] = True
            if body.get("jsonMode") is False:
                entry["jsonMode"] = False
            if body.get("discover"):
                entry["discover"] = True
            entry["custom"] = True
        load_env(env_file())  # a key just added to .env, without a restart
        placed = {}
        new_combos = {name: {**c, "models": list(c["models"])} for name, c in cfg["combos"].items()}
        provider_cfg = entry or known
        for m in models:
            names = combos if combos else profiler.combos_for(profiler.profile(f"{pid}/{m}", None, provider_cfg))
            names = [n for n in names if n in new_combos] or ["free" if "free" in new_combos else next(iter(new_combos))]
            for n in names:
                if f"{pid}/{m}" not in new_combos[n]["models"]:
                    new_combos[n]["models"].append(f"{pid}/{m}")
            placed[m] = names
        patch = {"combos": new_combos}
        if entry is not None:
            patch["providers"] = {pid: entry}
        config.update(patch)
        if bus is not None:
            from backend.state import public_config

            bus.emit("config", public_config(config))
        p = config.get()["providers"][pid]
        return {"ok": True, "provider": pid, "ready": router.provider_ready(pid), "combos": placed, "missingKey": p.get("keyEnv") if p.get("keyEnv") and not router.provider_ready(pid) else None}

    @app.delete("/api/providers/{pid}")
    async def api_provider_remove(pid: str):
        p = config.get()["providers"].get(pid)
        if p is None:
            return _err("Provider non trovato", 404)
        if not p.get("custom"):
            return _err(f"{pid} è un provider di serie: puoi spegnerlo dalle Impostazioni, non toglierlo.")
        combos = {name: {**c, "models": [m for m in c["models"] if not m.startswith(f"{pid}/")]} for name, c in config.get()["combos"].items()}
        config.remove_local("providers", pid)
        config.update({"combos": combos})
        if bus is not None:
            from backend.state import public_config

            bus.emit("config", public_config(config))
        return {"ok": True}
