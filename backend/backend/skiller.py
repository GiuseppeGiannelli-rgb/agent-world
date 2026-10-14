"""Skiller (Spec 05): a background scout for new skill repositories.

On a schedule it looks for candidate repositories on GitHub (search API) and on
the web (search results that point to github.com), measures how reliable each
one is from metadata alone, and keeps the verdicts in data/skiller.json.

Reliability, 0-100:
  stars           up to 40   10 * log10(stars + 1)
  last push       up to 25   <=30 days 25, <=90 20, <=180 12, <=365 5
  open issues     up to 15   open/stars <=0.05 15, <=0.15 10, <=0.3 5
  license         10
  SKILL.md found  10
Hard gates (any one rejects): archived, disabled, fork, no license, no SKILL.md,
a deprecated package (npm "deprecated", PyPI "Development Status :: 7 -
Inactive"), "deprecated" in the description or topics, fewer than minStars,
last push older than maxDaysSinceCommit.

Nothing is downloaded here: the only requests are GitHub/npm/PyPI metadata and
two small manifest files (package.json, pyproject.toml) read through the GitHub
API. Approved repositories wait in the report until the install step, which is
held back pending the security review of external downloads (Spec 05, §5).
"""

import asyncio
import base64
import json
import math
import os
import re
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from backend import web

GITHUB = "https://api.github.com"
SLUG_RE = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/([A-Za-z0-9._-]{1,100})")
NOT_OWNERS = {
    "topics", "orgs", "features", "marketplace", "sponsors", "about", "login", "search", "settings", "site",
    "collections", "trending", "apps", "enterprise", "pricing", "security", "customer-stories", "readme",
    "explore", "issues", "pulls", "notifications", "new", "codespaces", "events", "users",
}
INACTIVE = "Development Status :: 7 - Inactive"
DEFAULTS = {
    "enabled": True,
    "intervalHours": 24,
    "firstRunMinutes": 10,
    "queries": ["topic:agent-skills", "topic:claude-skills"],
    "webQueries": [],
    "maxCandidates": 25,
    "minStars": 20,
    "maxDaysSinceCommit": 365,
    "minScore": 60,
    "recheckDays": 7,
}


class RateLimited(RuntimeError):
    pass


def score_repo(meta: dict, *, skill_files: int, deprecated: list[str], now: float, min_stars: int, max_days: int) -> tuple[float, list[str]]:
    """(score 0-100, gate reasons). No reasons means the repo may be approved."""
    stars = int(meta.get("stargazers_count") or 0)
    pushed = meta.get("pushed_at")
    days = (now - datetime.fromisoformat(pushed.replace("Z", "+00:00")).timestamp()) / 86400 if pushed else 10**6
    ratio = int(meta.get("open_issues_count") or 0) / max(stars, 1)
    license_id = ((meta.get("license") or {}).get("spdx_id") or "").strip()
    has_license = bool(license_id) and license_id != "NOASSERTION"

    score = min(40.0, 10 * math.log10(stars + 1))
    score += 25 if days <= 30 else 20 if days <= 90 else 12 if days <= 180 else 5 if days <= 365 else 0
    score += 15 if ratio <= 0.05 else 10 if ratio <= 0.15 else 5 if ratio <= 0.3 else 0
    score += 10 if has_license else 0
    score += 10 if skill_files > 0 else 0

    reasons = []
    if meta.get("archived"):
        reasons.append("archived")
    if meta.get("disabled"):
        reasons.append("disabled")
    if meta.get("fork"):
        reasons.append("fork")
    if not has_license:
        reasons.append("no license")
    if skill_files == 0:
        reasons.append("no SKILL.md")
    text = f"{meta.get('description') or ''} {' '.join(meta.get('topics') or [])}".lower()
    if "deprecated" in text:
        reasons.append("described as deprecated")
    reasons += [f"deprecated package: {d}" for d in deprecated]
    if stars < min_stars:
        reasons.append(f"{stars} stars < {min_stars}")
    if days > max_days:
        reasons.append(f"last push {int(days)} days ago > {max_days}")
    return round(score, 1), reasons


def slugs_in(text: str) -> list[str]:
    """owner/repo slugs of the github.com links in a text, in order, unique."""
    out = []
    for owner, repo in SLUG_RE.findall(text or ""):
        repo = re.sub(r"\.git$", "", repo.rstrip("."))
        if owner.lower() in NOT_OWNERS or not repo:
            continue
        slug = f"{owner}/{repo}"
        if slug.lower() not in (s.lower() for s in out):
            out.append(slug)
    return out


class Skiller:
    def __init__(self, config, skills, data_dir: Path, *, client, bus=None, web_search=web.web_search, now=time.time):
        self.config = config
        self.skills = skills
        self.file = Path(data_dir) / "skiller.json"
        self.client = client
        self.bus = bus
        self.web_search = web_search
        self.now = now
        self.state = self._load()
        self._lock = asyncio.Lock()
        self.running = False
        self.next_run: float | None = None

    @property
    def cfg(self) -> dict:
        return {**DEFAULTS, **(((self.config.get() or {}).get("skills") or {}).get("skiller") or {})}

    def _load(self) -> dict:
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"repos": {}, "lastRun": None, "lastReport": None}

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def _headers(self) -> dict:
        h = {"accept": "application/vnd.github+json", "user-agent": web.UA, "x-github-api-version": "2022-11-28"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            h["authorization"] = f"Bearer {token}"
        return h

    async def _gh(self, path: str):
        res = await self.client.get(f"{GITHUB}{path}", headers=self._headers(), timeout=20)
        if res.status_code in (403, 429) and res.headers.get("x-ratelimit-remaining") == "0":
            raise RateLimited("GitHub rate limit reached (set GITHUB_TOKEN to raise it)")
        if res.status_code == 404:
            return None
        if res.status_code >= 400:
            raise RuntimeError(f"GitHub {path}: HTTP {res.status_code}")
        return res.json()

    def installed(self, slug: str) -> bool:
        repo = self.skills.repo(f"https://github.com/{slug}")
        listed = {str(u).lower().rstrip("/").removesuffix(".git") for u in ((self.config.get().get("skills") or {}).get("repos") or [])}
        return bool(repo and repo["dir"].exists()) or f"https://github.com/{slug}".lower() in listed

    async def discover(self) -> list[tuple[str, dict | None]]:
        """(slug, metadata if already known) for new candidates, best first."""
        cfg = self.cfg
        found: dict[str, dict | None] = {}
        for q in cfg["queries"]:
            data = await self._gh(f"/search/repositories?q={quote(q)}&sort=stars&order=desc&per_page={int(cfg['maxCandidates'])}")
            for item in (data or {}).get("items") or []:
                found.setdefault(item["full_name"], item)
        for q in cfg["webQueries"]:
            try:
                text = await self.web_search(q, client=self.client)
            except Exception:  # noqa: BLE001 -- the web part is a bonus, GitHub search is the base
                continue
            for slug in slugs_in(text):
                found.setdefault(slug, None)
        recheck = float(cfg["recheckDays"]) * 86400
        fresh = []
        for slug, meta in found.items():
            if self.installed(slug):
                continue
            seen = self.state["repos"].get(slug)
            if seen and seen.get("verdict") != "error" and self.now() - seen.get("checkedAt", 0) < recheck:
                continue
            fresh.append((slug, meta))
        return fresh[: int(cfg["maxCandidates"])]

    async def _manifest(self, slug: str, path: str) -> str | None:
        data = await self._gh(f"/repos/{slug}/contents/{path}")
        if not data or data.get("encoding") != "base64" or int(data.get("size") or 0) > 200_000:
            return None
        return base64.b64decode(data["content"]).decode("utf-8", errors="replace")

    async def deprecated_packages(self, slug: str, root_files: set[str]) -> list[str]:
        out = []
        if "package.json" in root_files:
            try:
                name = json.loads(await self._manifest(slug, "package.json") or "{}").get("name")
            except ValueError:
                name = None
            if name:
                res = await self.client.get(f"https://registry.npmjs.org/{quote(name, safe='@')}", timeout=20)
                if res.status_code == 200:
                    doc = res.json()
                    latest = (doc.get("dist-tags") or {}).get("latest")
                    if latest and (doc.get("versions") or {}).get(latest, {}).get("deprecated"):
                        out.append(f"npm {name}")
        if "pyproject.toml" in root_files:
            try:
                name = (tomllib.loads(await self._manifest(slug, "pyproject.toml") or "").get("project") or {}).get("name")
            except tomllib.TOMLDecodeError:
                name = None
            if name:
                res = await self.client.get(f"https://pypi.org/pypi/{quote(name)}/json", timeout=20)
                if res.status_code == 200 and INACTIVE in ((res.json().get("info") or {}).get("classifiers") or []):
                    out.append(f"pypi {name}")
        return out

    async def evaluate(self, slug: str, meta: dict | None = None) -> dict:
        cfg = self.cfg
        meta = meta or await self._gh(f"/repos/{slug}")
        if meta is None:
            return {"slug": slug, "verdict": "error", "reasons": ["repository not found"], "checkedAt": self.now()}
        tree = await self._gh(f"/repos/{slug}/git/trees/{quote(meta.get('default_branch') or 'HEAD')}?recursive=1") or {}
        paths = [e["path"] for e in tree.get("tree") or [] if e.get("type") == "blob"]
        skill_files = sum(1 for p in paths if p.rsplit("/", 1)[-1].lower() == "skill.md")
        deprecated = await self.deprecated_packages(slug, {p for p in paths if "/" not in p})
        score, reasons = score_repo(meta, skill_files=skill_files, deprecated=deprecated, now=self.now(), min_stars=int(cfg["minStars"]), max_days=int(cfg["maxDaysSinceCommit"]))
        approved = not reasons and score >= float(cfg["minScore"])
        if not reasons and not approved:
            reasons = [f"score {score} < {cfg['minScore']}"]
        return {
            "slug": slug,
            "url": f"https://github.com/{slug}",
            "stars": int(meta.get("stargazers_count") or 0),
            "pushedAt": meta.get("pushed_at"),
            "openIssues": int(meta.get("open_issues_count") or 0),
            "license": (meta.get("license") or {}).get("spdx_id"),
            "skillFiles": skill_files,
            "truncatedTree": bool(tree.get("truncated")),
            "deprecated": deprecated,
            "score": score,
            "reasons": reasons,
            "verdict": "approved" if approved else "rejected",
            "checkedAt": self.now(),
        }

    async def run_once(self) -> dict:
        async with self._lock:
            self.running = True
            try:
                evaluated, errors = [], []
                try:
                    candidates = await self.discover()
                except RateLimited as err:
                    candidates, errors = [], [str(err)]
                for slug, meta in candidates:
                    try:
                        ev = await self.evaluate(slug, meta)
                    except RateLimited as err:
                        errors.append(str(err))
                        break
                    except Exception as err:  # noqa: BLE001 -- one bad repo never stops the run
                        ev = {"slug": slug, "verdict": "error", "reasons": [str(err)[:200]], "checkedAt": self.now()}
                    self.state["repos"][slug] = ev
                    evaluated.append(ev)
                report = {
                    "ranAt": self.now(),
                    "evaluated": len(evaluated),
                    "approved": [e["slug"] for e in evaluated if e["verdict"] == "approved"],
                    "rejected": [e["slug"] for e in evaluated if e["verdict"] == "rejected"],
                    "errors": errors + [f"{e['slug']}: {e['reasons'][0]}" for e in evaluated if e["verdict"] == "error"],
                }
                self.state["lastRun"] = report["ranAt"]
                self.state["lastReport"] = report
                await asyncio.to_thread(self._save)
                if self.bus is not None:
                    self.bus.emit("skills", {"count": len(self.skills.skills), "op": "skiller", "evaluated": len(evaluated), "approved": len(report["approved"])})
                return report
            finally:
                self.running = False

    def report(self) -> dict:
        repos = self.state["repos"].values()
        return {
            "enabled": bool(self.cfg["enabled"]),
            "running": self.running,
            "lastRun": self.state.get("lastRun"),
            "nextRun": self.next_run,
            "lastReport": self.state.get("lastReport"),
            "approved": sorted((r for r in repos if r.get("verdict") == "approved"), key=lambda r: -r.get("score", 0)),
            "install": "held: external downloads wait for the security review (Spec 05, section 5)",
        }

    async def loop(self, shutdown: asyncio.Event) -> None:
        """First run after firstRunMinutes, then every intervalHours. Never raises."""
        delay = float(self.cfg["firstRunMinutes"]) * 60
        while not shutdown.is_set():
            self.next_run = self.now() + delay
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=delay)
                return  # shutdown
            except asyncio.TimeoutError:
                pass
            if self.cfg["enabled"]:
                try:
                    report = await self.run_once()
                    print(f"Skiller      →  {report['evaluated']} repo valutate, {len(report['approved'])} approvate", flush=True)
                except Exception as err:  # noqa: BLE001 -- a failed run waits for the next one
                    print(f"Skiller      →  giro fallito: {err}", flush=True)
            delay = float(self.cfg["intervalHours"]) * 3600
