"""Mirrors server/router/index.js: the app's own LLM gateway. A request
names a combo, a role (mapped to a combo) or one model; the router walks
the combo, skipping unready providers and targets cooling down.

Spec 08: the router reads why a call failed (providers._classify).
- Credit gone (kind "quota"): the whole provider sits out for
  router.quotaCooldownMs (6 h); its other models are not tried. A refused key
  ("auth") benches the provider the same way, for router.authCooldownMs.
- Model gone ("model_not_found"): that provider/model is blacklisted for
  router.deadModelTtlMs and its router.aliases are tried at once, in its place.
- A rate limit or a server error cools that one target, for the delay the
  provider asked for when it gave one.
- Cascade: when every target of a combo fails, the chain router.cascade goes
  on (frontier -> smart -> fast -> free -> local; a combo outside the chain
  joins it at its "joins"). If nothing answers, the demo simulator steps in:
  in demo mode as always, in live mode only as a flagged emergency
  (router.emergencyMock, a router.emergency event). One explicit model, the
  test button and the /v1 gateway can opt out (cascade=False, emergency=False)."""

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.plan import nz
from backend.router import profiler
from backend.router.providers import ProviderError, base_url, call_provider

log = logging.getLogger("agent_world.router")

DEFAULT_QUOTA_COOLDOWN_MS = 6 * 3600 * 1000
DEFAULT_DEAD_MODEL_TTL_MS = 24 * 3600 * 1000
DEFAULT_DISCOVER_MAX = 6
DEFAULT_DISCOVER_INTERVAL_MS = 10 * 60 * 1000
DISCOVER_TIMEOUT_S = 4


class Router:
    def __init__(self, config, data_dir: Path, bus=None, client: httpx.AsyncClient | None = None):
        self.config = config
        self.data_dir = Path(data_dir)
        self.bus = bus
        self.client = client or httpx.AsyncClient()
        self.cooldowns: dict[str, dict] = {}  # target key -> {until, failures, reason}
        self.provider_cooldowns: dict[str, dict] = {}  # provider id -> {until, reason}: credit gone, key refused
        self.dead: dict[str, dict] = {}  # target key -> {until, reason}: the model does not exist (any more)
        self.stats: dict[str, dict] = {}
        self.rr_cursor: dict[str, int] = {}
        self.recent: list[dict] = []
        self.discovered: dict[str, list[dict]] = {}  # provider id -> profiles of the models its /models listed

    @property
    def cfg(self) -> dict:
        return self.config.get()

    @staticmethod
    def _now() -> float:
        return time.time() * 1000

    def provider_ready(self, id: str) -> bool:
        import os

        p = self.cfg["providers"].get(id)
        if not p or p.get("enabled") is False:
            return False
        if p.get("baseUrlEnv") and not os.environ.get(p["baseUrlEnv"], "").strip():
            return False  # a server named only by its environment variable, which is not set
        if p.get("kind") == "mock" or p.get("keyless"):
            return True
        return bool(p.get("keyEnv") and os.environ.get(p["keyEnv"]))

    def provider_cooldown(self, id: str) -> dict | None:
        """The bench of a provider (credit gone, key refused), while it lasts."""
        cd = self.provider_cooldowns.get(id)
        return cd if cd and cd["until"] > self._now() else None

    def available(self, id: str) -> bool:
        """Ready and not benched: what the embedder asks before calling it."""
        return self.provider_ready(id) and self.provider_cooldown(id) is None

    def is_dead(self, key: str) -> bool:
        d = self.dead.get(key)
        return bool(d and d["until"] > self._now())

    def mode(self) -> str:
        live = any(p.get("kind") != "mock" and self.provider_ready(id) for id, p in self.cfg["providers"].items())
        return "live" if live else "demo"

    def parse_target(self, target: str) -> dict | None:
        slash = target.find("/")
        if slash < 1:
            return None
        return {"provider": target[:slash], "model": target[slash + 1 :], "key": target}

    def aliases_of(self, target: dict, depth: int = 0) -> list[dict]:
        """The live replacements of a dead model, in the order of router.aliases
        (an alias that is dead too gives its own aliases)."""
        out: list[dict] = []
        for key in (self.cfg["router"].get("aliases") or {}).get(target["key"], []):
            alias = self.parse_target(key)
            if not alias:
                continue
            if self.is_dead(alias["key"]):
                if depth < 3:
                    out += self.aliases_of(alias, depth + 1)
            else:
                out.append(alias)
        return out

    def _live(self, targets: list[dict]) -> list[dict]:
        out, seen = [], set()
        for t in targets:
            for c in ([t] if not self.is_dead(t["key"]) else self.aliases_of(t)):
                if c["key"] not in seen:
                    seen.add(c["key"])
                    out.append(c)
        return out

    def expand(self, spec: str) -> dict:
        name = spec[len("combo:") :] if spec.startswith("combo:") else spec
        combo = self.cfg["combos"].get(name)
        if combo:
            targets = [t for t in (self.parse_target(m) for m in combo["models"]) if t]
            return {"combo": name, "strategy": combo.get("strategy", "fallback"), "targets": self._live(targets + self.assumed(name, {t["key"] for t in targets}))}
        single = self.parse_target(spec)
        if not single:
            raise ValueError(f'Unknown combo or model "{spec}"')
        return {"combo": None, "strategy": "fallback", "targets": self._live([single])}

    # ---------- spec 08: profiles and discovery ----------

    def profile(self, key: str) -> dict:
        """The profile of a target, with the metadata /models gave, if any."""
        provider_id = key.partition("/")[0]
        meta = next((p.get("meta") for p in self.discovered.get(provider_id, []) if p["key"] == key), None)
        return profiler.profile(key, meta, self.cfg["providers"].get(provider_id))

    def assumed(self, combo: str, configured: set[str]) -> list[dict]:
        """The models found at runtime that join `combo` (profiler.combos_for),
        after the configured ones, at most router.discoverMax of them."""
        limit = int(self.cfg["router"].get("discoverMax", DEFAULT_DISCOVER_MAX))
        out = []
        for provider_id, profiles in self.discovered.items():
            if not self.provider_ready(provider_id):
                continue
            for p in profiles:
                if combo in profiler.combos_for(p) and p["key"] not in configured and len(out) < limit:
                    out.append({"provider": p["provider"], "model": p["model"], "key": p["key"]})
        return out

    async def discover(self) -> dict[str, list[dict]]:
        """Asks /models of every ready provider that may be listed: the local
        ones (Ollama, LM Studio, a local server) and those with "discover" in
        their config ("free": only the :free models). A provider that does not
        answer keeps what it listed last time."""
        found: dict[str, list[dict]] = {}
        for id_, p in self.cfg["providers"].items():
            mode = p.get("discover", True if p.get("local") else False)
            if not mode or p.get("kind") != "openai" or not self.available(id_):
                continue
            import os

            key = os.environ.get(p["keyEnv"]) if p.get("keyEnv") else None
            try:
                res = await self.client.get(base_url(p) + "/models", headers={"authorization": f"Bearer {key}"} if key else {}, timeout=DISCOVER_TIMEOUT_S)
                if res.status_code >= 400:
                    continue
                entries = res.json().get("data") or []
            except Exception:  # noqa: BLE001 -- a provider that is not running is simply not listed
                continue
            profiles = []
            for e in entries:
                model = str((e or {}).get("id") or "")
                if not model or (mode == "free" and not model.endswith(":free")):
                    continue
                prof = profiler.profile(f"{id_}/{model}", e, p)
                prof["meta"] = {k: e[k] for k in ("context_length", "contextLength", "context_window") if k in e}
                profiles.append(prof)
            found[id_] = profiles
        self.discovered.update(found)
        return found

    async def discovery_loop(self, shutdown) -> None:
        """Lists the models at startup, then every router.discoverIntervalMs, so a
        local server started later (or a provider enabled in the Settings) joins
        its combos without a restart."""
        import asyncio

        while not shutdown.is_set():
            try:
                await self.discover()
            except Exception as err:  # noqa: BLE001 -- discovery is a bonus, never a crash
                log.warning("model discovery failed: %s", err)
            interval = int(self.cfg["router"].get("discoverIntervalMs", DEFAULT_DISCOVER_INTERVAL_MS)) / 1000
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    def cascade_after(self, name: str | None) -> list[str]:
        """The combos to try after `name`, down router.cascade."""
        chain = list(self.cfg["router"].get("cascade") or [])
        combos = self.cfg["combos"]
        if name in chain:
            rest = chain[chain.index(name) + 1 :]
        else:
            joins = (combos.get(name) or {}).get("joins") if name else None
            rest = chain[chain.index(joins) :] if joins in chain else chain
        return [c for c in rest if c != name and c in combos]

    def spec_for_role(self, role: str | None) -> str:
        default = self.cfg["router"]["defaultCombo"]
        if role == "ceo":
            return nz((self.cfg.get("ceo") or {}).get("combo"), default)
        team = (self.cfg.get("teams") or {}).get(role or "") or {}
        return nz(team.get("combo"), default)

    def order(self, expanded: dict, *, rotate: bool = True) -> list[dict]:
        """The ready targets of one combo, benched providers left out, the warm
        ones first and the cooling ones last (soonest back first)."""
        combo, strategy = expanded["combo"], expanded["strategy"]
        ready = [t for t in expanded["targets"] if self.provider_ready(t["provider"]) and self.provider_cooldown(t["provider"]) is None]
        if strategy == "round-robin" and len(ready) > 1 and combo:
            start = self.rr_cursor.get(combo, 0) % len(ready)
            if rotate:
                self.rr_cursor[combo] = start + 1
            ready = ready[start:] + ready[:start]
        now = self._now()
        warm = [t for t in ready if not (self.cooldowns.get(t["key"], {}).get("until", 0) > now)]
        cold = sorted((t for t in ready if self.cooldowns.get(t["key"], {}).get("until", 0) > now), key=lambda t: self.cooldowns[t["key"]]["until"])
        return warm + cold

    def peek(self, spec: str | None = None, role: str | None = None) -> dict:
        """Spec 08: the profile of the model a call would most likely reach (the
        first ready target down the cascade), so a prompt can be sized for it
        before the call. Nothing moves: no round-robin step, no call."""
        spec = spec or self.spec_for_role(role)
        try:
            first = self.expand(spec)
        except ValueError:
            return self.profile(f"mock/mock-{role or 'any'}")
        steps = [first] + ([self.expand(n) for n in self.cascade_after(first["combo"])] if first["combo"] else [])
        for step in steps:
            for t in self.order(step, rotate=False):
                if not self.is_dead(t["key"]):
                    return self.profile(t["key"])
        return self.profile(f"mock/mock-{role or 'any'}")

    def plan(self, spec: str, role: str | None) -> dict:
        """The first step of a call, kept for the callers of the old router."""
        expanded = self.expand(spec)
        return {"combo": expanded["combo"], "strategy": expanded["strategy"], "demo": False, "order": self.order(expanded)}

    def _may_simulate(self, emergency: bool | None) -> bool:
        r = self.cfg["router"]
        if not r.get("demoFallback") or "mock" not in self.cfg["providers"]:
            return False
        if self.mode() == "demo":
            return True
        return bool(emergency if emergency is not None else r.get("emergencyMock", True))

    async def chat(self, *, role: str | None = None, use: str | None = None, messages: list[dict], json: bool = False, max_tokens: int | None = None, temperature: float | None = None, meta: dict | None = None, cascade: bool | None = None, emergency: bool | None = None) -> dict:
        meta = meta or {}
        spec = use or self.spec_for_role(role)
        first = self.expand(spec)
        steps = [first]
        if emergency is None and first["combo"] is None:
            emergency = False  # one explicit model: its own error, not an invented answer
        if cascade if cascade is not None else first["combo"] is not None:
            steps += [self.expand(name) for name in self.cascade_after(first["combo"])]
        req = {"messages": messages, "json": json, "maxTokens": max_tokens, "temperature": temperature, "role": role}
        tried: set[str] = set()
        visited: list[str] = []
        errors: list[str] = []
        for step in steps:
            visited.append(step["combo"] or spec)
            queue = self.order(step)
            while queue:
                target = queue.pop(0)
                if target["key"] in tried or self.provider_cooldown(target["provider"]) or self.is_dead(target["key"]):
                    continue
                tried.add(target["key"])
                provider = self.cfg["providers"][target["provider"]]
                started = time.monotonic()
                try:
                    res = await call_provider(provider, target["provider"], target["model"], req, self.client)
                except ProviderError as err:
                    ms = (time.monotonic() - started) * 1000
                    self.cool(target, err)
                    self.record(target, ok=False, ms=ms, error=str(err))
                    self.log(target, step["combo"], role, meta, ms, False, error=str(err))
                    errors.append(f"{target['key']}: {err}")
                    if err.kind == "model_not_found":
                        # its updated aliases first, before the next target
                        queue[0:0] = [a for a in self.aliases_of(target) if a["key"] not in tried and self.provider_ready(a["provider"])]
                    continue
                ms = (time.monotonic() - started) * 1000
                self.cooldowns.pop(target["key"], None)
                self.record(target, ok=True, ms=ms, usage=res["usage"])
                summary = self.log(target, step["combo"], role, meta, ms, True, usage=res["usage"])
                return {"text": res["text"], "provider": target["provider"], "model": res["model"], "target": target["key"], "usage": res["usage"], "ms": ms, "callId": summary["id"], "demo": False, "emergency": False, "combo": step["combo"], "requested": spec, "cascade": visited, "profile": self.profile(target["key"])}
        if self._may_simulate(emergency):
            return await self._simulate(req, role, spec, visited, meta, errors)
        if not errors:
            raise ProviderError(f'No provider with a key in "{spec}"')
        raise ProviderError(f'Every target failed for "{spec}":\n' + "\n".join(errors))

    async def _simulate(self, req: dict, role, spec: str, visited: list[str], meta: dict, errors: list[str]) -> dict:
        """The demo simulator: the normal answer in demo mode, an emergency in live mode."""
        emergency = self.mode() == "live"
        target = {"provider": "mock", "model": f"mock-{role or 'any'}", "key": f"mock/mock-{role or 'any'}"}
        if emergency:
            log.warning('No provider answered for "%s" (tried %s): the demo simulator answers instead', spec, " -> ".join(visited))
            if self.bus is not None:
                self.bus.emit("router.emergency", {"requested": spec, "role": role, "cascade": visited, "runId": meta.get("runId"), "taskId": meta.get("taskId"), "agentId": meta.get("agentId"), "errors": errors[-6:]})
        started = time.monotonic()
        res = await call_provider(self.cfg["providers"]["mock"], "mock", target["model"], req, self.client)
        ms = (time.monotonic() - started) * 1000
        self.record(target, ok=True, ms=ms, usage=res["usage"])
        summary = self.log(target, None, role, meta, ms, True, usage=res["usage"], demo=True, emergency=emergency)
        return {"text": res["text"], "provider": "mock", "model": res["model"], "target": target["key"], "usage": res["usage"], "ms": ms, "callId": summary["id"], "demo": True, "emergency": emergency, "combo": None, "requested": spec, "cascade": visited, "profile": self.profile(target["key"])}

    def cool(self, target: dict, err: ProviderError) -> None:
        r = self.cfg["router"]
        now = self._now()
        if err.kind == "quota":
            self.provider_cooldowns[target["provider"]] = {"until": now + r.get("quotaCooldownMs", DEFAULT_QUOTA_COOLDOWN_MS), "reason": "quota_exhausted"}
            log.warning("%s: the credit is exhausted, the provider sits out", target["provider"])
            return
        if err.kind == "auth":
            # A refused key fails the same way for every model of that provider.
            self.provider_cooldowns[target["provider"]] = {"until": now + r["authCooldownMs"], "reason": "auth"}
            return
        if err.kind == "model_not_found":
            self.dead[target["key"]] = {"until": now + r.get("deadModelTtlMs", DEFAULT_DEAD_MODEL_TTL_MS), "reason": "model_not_found"}
            return
        if not err.retryable:
            return
        prev = self.cooldowns.get(target["key"])
        failures = (prev["failures"] if prev else 0) + 1
        wait = err.retry_after_ms or min(r["cooldownBaseMs"] * 2 ** (failures - 1), r["cooldownMaxMs"])
        self.cooldowns[target["key"]] = {"until": now + wait, "failures": failures, "reason": str(err)[:120]}

    def record(self, target: dict, *, ok: bool, ms: float, usage: dict | None = None, error: str | None = None) -> None:
        s = self.stats.get(target["key"]) or {"calls": 0, "ok": 0, "fail": 0, "tokensIn": 0, "tokensOut": 0, "totalMs": 0, "lastError": None}
        s["calls"] += 1
        s["totalMs"] += ms
        if ok:
            s["ok"] += 1
            s["tokensIn"] += (usage or {}).get("in", 0)
            s["tokensOut"] += (usage or {}).get("out", 0)
        else:
            s["fail"] += 1
            s["lastError"] = error
        s["lastAt"] = time.time() * 1000
        self.stats[target["key"]] = s

    def log(self, target: dict, combo, role, meta: dict, ms: float, ok: bool, *, usage: dict | None = None, error: str | None = None, demo: bool = False, emergency: bool = False) -> dict:
        summary = {
            "id": str(uuid.uuid4()),
            "at": datetime.now(timezone.utc).isoformat(),
            "target": target["key"],
            "provider": target["provider"],
            "model": target["model"],
            "combo": combo,
            "role": role,
            "runId": meta.get("runId"),
            "taskId": meta.get("taskId"),
            "agentId": meta.get("agentId"),
            "ms": ms,
            "ok": ok,
            "demo": demo,
            "emergency": emergency,
            "tokens": {"in": (usage or {}).get("in", 0), "out": (usage or {}).get("out", 0)},
            "error": error,
        }
        self.recent.insert(0, summary)
        self.recent = self.recent[:200]
        if self.bus is not None:
            self.bus.emit("router.call", summary)
        if self.cfg["router"].get("logCalls"):
            self._write_call_log(summary)
        return summary

    def _write_call_log(self, summary: dict) -> None:
        import json as jsonlib

        day = summary["at"][:10]
        dir_ = self.data_dir / "calls" / day
        try:
            dir_.mkdir(parents=True, exist_ok=True)
            file = dir_ / f"{summary['at'].replace(':', '-').replace('.', '-')}_{summary['id']}.json"
            file.write_text(jsonlib.dumps({"summary": summary}, indent=1), encoding="utf-8")
        except OSError:
            pass  # fire-and-forget, like the Node log(): never blocks or raises

    def _target_state(self, key: str, provider: str | None, now: float) -> tuple[float, str | None]:
        """(ms still cooling, why) for one target: a dead model, a benched
        provider or its own cooldown, whichever lasts longest."""
        best, why = 0.0, None
        candidates = [self.dead.get(key), self.provider_cooldowns.get(provider) if provider else None, self.cooldowns.get(key)]
        for cd in candidates:
            if cd and cd["until"] - now > best:
                best, why = cd["until"] - now, cd["reason"]
        return best, why

    def snapshot(self) -> dict:
        now = time.time() * 1000
        cfg = self.cfg
        providers = [
            {"id": id, "kind": p.get("kind"), "baseUrl": p.get("baseUrl"), "keyEnv": p.get("keyEnv"), "enabled": p.get("enabled") is not False, "ready": self.provider_ready(id), "benched": (self.provider_cooldown(id) or {}).get("reason"), "discovered": len(self.discovered.get(id, []))}
            for id, p in cfg["providers"].items()
        ]
        combos = []
        for name, c in cfg["combos"].items():
            targets = []
            for key in c["models"]:
                t = self.parse_target(key)
                cooling, reason = self._target_state(key, t["provider"] if t else None, now)
                targets.append({"key": key, "ready": self.provider_ready(t["provider"]) if t else False, "coolingMs": cooling, "reason": reason, "stats": self.stats.get(key)})
            combos.append({"name": name, "strategy": c.get("strategy", "fallback"), "targets": targets})
        # the shape the panel reads stays the same (test_state.py): a dead model or a
        # benched provider shows up as the reason and the coolingMs of its targets
        return {"mode": self.mode(), "providers": providers, "combos": combos, "recent": self.recent[:60]}
