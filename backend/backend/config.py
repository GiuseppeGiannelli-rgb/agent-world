"""Mirrors server/config.js: default.json + local.json, deep merge, env
overrides, derived staff list, EDITABLE whitelist for update().

N15: default.json holds the shipped defaults, local.json the user's own
preferences. AGENT_WORLD_LOCAL_CONFIG moves the preferences file elsewhere
(the tests and the test launchers do, so they never read or write the user's
file); without it they stay next to default.json, as always."""

import json
import os
from pathlib import Path

from backend.i18n import DEFAULT as DEFAULT_LANGUAGE

EDITABLE = ["limits", "pacing", "router", "providers", "combos", "teams", "ceo", "media", "skills", "rag", "ui"]


def _is_object(v) -> bool:
    return isinstance(v, dict)


def merge(base, over):
    if not _is_object(over):
        return base if over is None else over
    out = dict(base) if _is_object(base) else {}
    for key, value in over.items():
        if _is_object(value) and _is_object(out.get(key)):
            out[key] = merge(out[key], value)
        else:
            out[key] = value
    return out


def local_config_path() -> Path | None:
    v = os.environ.get("AGENT_WORLD_LOCAL_CONFIG")
    return Path(v) if v else None


class Config:
    def __init__(self, dir: Path, local_file: Path | None = None):
        dir = Path(dir)
        self.defaults_file = dir / "default.json"
        # an explicit file first, then AGENT_WORLD_LOCAL_CONFIG, then next to the defaults
        self.local_file = Path(local_file) if local_file is not None else local_config_path() or dir / "local.json"
        self.reload()

    def reload(self) -> None:
        defaults = json.loads(self.defaults_file.read_text(encoding="utf-8"))
        self.local = json.loads(self.local_file.read_text(encoding="utf-8")) if self.local_file.exists() else {}
        self.value = merge(defaults, self.local)
        if os.environ.get("PORT"):
            self.value["server"]["port"] = int(os.environ["PORT"])
        self.value.setdefault("ui", {}).setdefault("language", DEFAULT_LANGUAGE)  # spec 06: English
        self.value["limits"]["allowShell"] = os.environ.get("AGENT_WORLD_ALLOW_SHELL") == "1"
        if os.environ.get("AGENT_WORLD_FAST") == "1":
            for k in list(self.value["pacing"].keys()):
                self.value["pacing"][k] = 20
            self.value["providers"]["mock"]["latencyMs"] = [10, 40]
        staff = [{"id": self.value["ceo"]["id"], "name": self.value["ceo"]["name"], "team": "ceo", "kind": "ceo"}]
        for team, t in self.value["teams"].items():
            if t.get("lead"):
                staff.append({"id": t["lead"]["id"], "name": t["lead"]["name"], "team": team, "kind": "lead"})
            for w in t.get("workers", []):
                staff.append({"id": w["id"], "name": w["name"], "team": team, "kind": "worker"})
        self.value["staff"] = staff

    def get(self) -> dict:
        return self.value

    def remove_local(self, key: str, name: str) -> None:
        """Spec 09: takes one entry out of a preference (a provider the owner added)."""
        section = self.local.get(key)
        if isinstance(section, dict) and name in section:
            del section[name]
            self.local_file.parent.mkdir(parents=True, exist_ok=True)
            self.local_file.write_text(json.dumps(self.local, indent=2), encoding="utf-8")
            self.reload()

    def update(self, patch: dict) -> None:
        for key in EDITABLE:
            if key not in patch:
                continue
            self.local[key] = patch[key] if key == "combos" else merge(self.local.get(key, {}), patch[key])
        self.local_file.parent.mkdir(parents=True, exist_ok=True)
        self.local_file.write_text(json.dumps(self.local, indent=2), encoding="utf-8")
        self.reload()
