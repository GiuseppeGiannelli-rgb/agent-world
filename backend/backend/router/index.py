"""Mirrors server/router/index.js: the app's own LLM gateway. A request
names a combo, a role (mapped to a combo) or one model; the router walks
the combo, skipping unready providers and targets cooling down."""

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.plan import nz
from backend.router.providers import ProviderError, call_provider


class Router:
    def __init__(self, config, data_dir: Path, bus=None, client: httpx.AsyncClient | None = None):
        self.config = config
        self.data_dir = Path(data_dir)
        self.bus = bus
        self.client = client or httpx.AsyncClient()
        self.cooldowns: dict[str, dict] = {}  # target key -> {until, failures, reason}
        self.stats: dict[str, dict] = {}
        self.rr_cursor: dict[str, int] = {}
        self.recent: list[dict] = []

    @property
    def cfg(self) -> dict:
        return self.config.get()

    def provider_ready(self, id: str) -> bool:
        p = self.cfg["providers"].get(id)
        if not p or p.get("enabled") is False:
            return False
        if p.get("kind") == "mock" or p.get("keyless"):
            return True
        import os

        return bool(p.get("keyEnv") and os.environ.get(p["keyEnv"]))

    def mode(self) -> str:
        live = any(p.get("kind") != "mock" and self.provider_ready(id) for id, p in self.cfg["providers"].items())
        return "live" if live else "demo"

    def parse_target(self, target: str) -> dict | None:
        slash = target.find("/")
        if slash < 1:
            return None
        return {"provider": target[:slash], "model": target[slash + 1 :], "key": target}

    def expand(self, spec: str) -> dict:
        name = spec[len("combo:") :] if spec.startswith("combo:") else spec
        combo = self.cfg["combos"].get(name)
        if combo:
            targets = [t for t in (self.parse_target(m) for m in combo["models"]) if t]
            return {"combo": name, "strategy": combo.get("strategy", "fallback"), "targets": targets}
        single = self.parse_target(spec)
        if not single:
            raise ValueError(f'Unknown combo or model "{spec}"')
        return {"combo": None, "strategy": "fallback", "targets": [single]}

    def spec_for_role(self, role: str | None) -> str:
        default = self.cfg["router"]["defaultCombo"]
        if role == "ceo":
            return nz((self.cfg.get("ceo") or {}).get("combo"), default)
        team = (self.cfg.get("teams") or {}).get(role or "") or {}
        return nz(team.get("combo"), default)

    def plan(self, spec: str, role: str | None) -> dict:
        expanded = self.expand(spec)
        combo, strategy, targets = expanded["combo"], expanded["strategy"], expanded["targets"]
        ready = [t for t in targets if self.provider_ready(t["provider"])]
        demo = False
        if not ready:
            if not self.cfg["router"].get("demoFallback"):
                raise ValueError(f'No provider with a key in "{spec}"')
            ready = [{"provider": "mock", "model": f"mock-{role or 'any'}", "key": f"mock/mock-{role or 'any'}"}]
            demo = True
        if strategy == "round-robin" and len(ready) > 1 and combo:
            start = self.rr_cursor.get(combo, 0) % len(ready)
            self.rr_cursor[combo] = start + 1
            ready = ready[start:] + ready[:start]
        now = time.time() * 1000
        warm = [t for t in ready if not (self.cooldowns.get(t["key"], {}).get("until", 0) > now)]
        cold = sorted(
            (t for t in ready if self.cooldowns.get(t["key"], {}).get("until", 0) > now),
            key=lambda t: self.cooldowns[t["key"]]["until"],
        )
        return {"combo": combo, "strategy": strategy, "demo": demo, "order": warm + cold}

    async def chat(self, *, role: str | None = None, use: str | None = None, messages: list[dict], json: bool = False, max_tokens: int | None = None, temperature: float | None = None, meta: dict | None = None) -> dict:
        meta = meta or {}
        spec = use or self.spec_for_role(role)
        planned = self.plan(spec, role)
        combo, demo, order = planned["combo"], planned["demo"], planned["order"]
        errors = []
        for target in order:
            provider = self.cfg["providers"][target["provider"]]
            started = time.monotonic()
            try:
                req = {"messages": messages, "json": json, "maxTokens": max_tokens, "temperature": temperature, "role": role}
                res = await call_provider(provider, target["provider"], target["model"], req, self.client)
                ms = (time.monotonic() - started) * 1000
                self.cooldowns.pop(target["key"], None)
                self.record(target, ok=True, ms=ms, usage=res["usage"])
                summary = self.log(target, combo, role, meta, ms, True, usage=res["usage"], demo=demo)
                return {"text": res["text"], "provider": target["provider"], "model": res["model"], "target": target["key"], "usage": res["usage"], "ms": ms, "callId": summary["id"], "demo": demo}
            except ProviderError as err:
                ms = (time.monotonic() - started) * 1000
                self.cool(target, err)
                self.record(target, ok=False, ms=ms, error=str(err))
                self.log(target, combo, role, meta, ms, False, error=str(err), demo=demo)
                errors.append(f"{target['key']}: {err}")
        raise ProviderError(f'Every target failed for "{spec}":\n' + "\n".join(errors))

    def cool(self, target: dict, err: ProviderError) -> None:
        r = self.cfg["router"]
        if err.auth:
            # A refused key fails the same way for every model of that provider.
            for combo in self.cfg["combos"].values():
                for t in combo["models"]:
                    if t.startswith(f"{target['provider']}/"):
                        self.cooldowns[t] = {"until": time.time() * 1000 + r["authCooldownMs"], "failures": 1, "reason": "auth"}
            return
        if not err.retryable:
            return
        prev = self.cooldowns.get(target["key"])
        failures = (prev["failures"] if prev else 0) + 1
        wait = min(r["cooldownBaseMs"] * 2 ** (failures - 1), r["cooldownMaxMs"])
        self.cooldowns[target["key"]] = {"until": time.time() * 1000 + wait, "failures": failures, "reason": str(err)[:120]}

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

    def log(self, target: dict, combo, role, meta: dict, ms: float, ok: bool, *, usage: dict | None = None, error: str | None = None, demo: bool = False) -> dict:
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

    def snapshot(self) -> dict:
        now = time.time() * 1000
        cfg = self.cfg
        providers = [
            {"id": id, "kind": p.get("kind"), "baseUrl": p.get("baseUrl"), "keyEnv": p.get("keyEnv"), "enabled": p.get("enabled") is not False, "ready": self.provider_ready(id)}
            for id, p in cfg["providers"].items()
        ]
        combos = []
        for name, c in cfg["combos"].items():
            targets = []
            for key in c["models"]:
                t = self.parse_target(key)
                cd = self.cooldowns.get(key)
                cooling = cd["until"] - now if cd and cd["until"] > now else 0
                targets.append({"key": key, "ready": self.provider_ready(t["provider"]) if t else False, "coolingMs": cooling, "reason": cd["reason"] if cooling else None, "stats": self.stats.get(key)})
            combos.append({"name": name, "strategy": c.get("strategy", "fallback"), "targets": targets})
        return {"mode": self.mode(), "providers": providers, "combos": combos, "recent": self.recent[:60]}
