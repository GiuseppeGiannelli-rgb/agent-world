"""Spec 05: the Skiller scouts and scores skill repositories from metadata only.
Every request goes to a mock transport; the test also proves that nothing but
metadata hosts is ever contacted (no archive, no clone)."""

import asyncio
import base64
import json
import time

import httpx
import pytest

from backend.skiller import Skiller, score_repo, slugs_in

NOW = time.mktime((2026, 10, 14, 0, 0, 0, 0, 0, -1))
DAY = 86400


def iso(days_ago: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW - days_ago * DAY))


def repo_meta(full_name, *, stars=500, days=10, issues=5, license="MIT", **extra):
    return {
        "full_name": full_name, "stargazers_count": stars, "pushed_at": iso(days), "open_issues_count": issues,
        "license": {"spdx_id": license} if license else None, "archived": False, "disabled": False, "fork": False,
        "description": "Agent skills", "topics": ["agent-skills"], "default_branch": "main", **extra,
    }


def b64(text: str) -> dict:
    return {"encoding": "base64", "size": len(text), "content": base64.b64encode(text.encode()).decode()}


# ---------- pure scoring ----------


def test_score_rewards_reliable_repos():
    score, reasons = score_repo(repo_meta("a/b", stars=20000, days=5, issues=40), skill_files=12, deprecated=[], now=NOW, min_stars=20, max_days=365)
    assert reasons == [] and score == pytest.approx(40 + 25 + 15 + 10 + 10)


@pytest.mark.parametrize(
    "meta, kwargs, reason",
    [
        (repo_meta("a/b", archived=True), {}, "archived"),
        (repo_meta("a/b", fork=True), {}, "fork"),
        (repo_meta("a/b", license=None), {}, "no license"),
        (repo_meta("a/b", license="NOASSERTION"), {}, "no license"),
        (repo_meta("a/b"), {"skill_files": 0}, "no SKILL.md"),
        (repo_meta("a/b", description="DEPRECATED, use x"), {}, "described as deprecated"),
        (repo_meta("a/b"), {"deprecated": ["npm old-pkg"]}, "deprecated package: npm old-pkg"),
        (repo_meta("a/b", stars=3), {}, "3 stars < 20"),
        (repo_meta("a/b", days=500), {}, "last push 500 days ago > 365"),
    ],
)
def test_score_hard_gates(meta, kwargs, reason):
    args = {"skill_files": 3, "deprecated": [], **kwargs}
    _, reasons = score_repo(meta, now=NOW, min_stars=20, max_days=365, **args)
    assert reason in reasons


def test_slugs_in_reads_repo_links_only():
    text = """1. Skills\n   https://github.com/acme/skills.git\n   https://github.com/topics/agent-skills
   see github.com/Acme/Skills and https://github.com/orgs/acme, https://github.com/other/repo."""
    assert slugs_in(text) == ["acme/skills", "other/repo"]


# ---------- the scout against a fake GitHub ----------


class Cfg:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeSkills:
    def __init__(self, tmp_path):
        self.skills = [{"id": "x"}] * 7
        self.vendor = tmp_path / "skills" / "vendor"

    def repo(self, url):
        slug = url.removeprefix("https://github.com/")
        return {"dir": self.vendor / slug.replace("/", "-")}


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


def fake_github(requests, *, rate_limited=False):
    repos = {
        "good/skills": repo_meta("good/skills", stars=3000, days=3, issues=10),
        "old/skills": repo_meta("old/skills", stars=900, days=800),
        "npm/skills": repo_meta("npm/skills", stars=900, days=20),
        "py/skills": repo_meta("py/skills", stars=900, days=20),
        "listed/skills": repo_meta("listed/skills"),
        "web/found": repo_meta("web/found", stars=150, days=40),
    }
    trees = {
        "good/skills": ["skills/a/SKILL.md", "skills/b/SKILL.md", "README.md"],
        "old/skills": ["SKILL.md"],
        "npm/skills": ["package.json", "skills/x/SKILL.md"],
        "py/skills": ["pyproject.toml", "s/SKILL.md"],
        "web/found": ["README.md"],
    }

    def handler(request: httpx.Request):
        url = str(request.url)
        requests.append(url)
        path = request.url.path
        if rate_limited:
            return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={})
        if path == "/search/repositories":
            return httpx.Response(200, json={"items": [repos[s] for s in ("good/skills", "old/skills", "npm/skills", "py/skills", "listed/skills")]})
        if request.url.host == "registry.npmjs.org":
            return httpx.Response(200, json={"dist-tags": {"latest": "2.0.0"}, "versions": {"2.0.0": {"deprecated": "use other-pkg"}}})
        if request.url.host == "pypi.org":
            return httpx.Response(200, json={"info": {"classifiers": ["Development Status :: 7 - Inactive"]}})
        for slug, meta in repos.items():
            if path == f"/repos/{slug}":
                return httpx.Response(200, json=meta)
            if path.startswith(f"/repos/{slug}/git/trees/"):
                return httpx.Response(200, json={"tree": [{"path": p, "type": "blob"} for p in trees.get(slug, [])], "truncated": False})
            if path == f"/repos/{slug}/contents/package.json":
                return httpx.Response(200, json=b64(json.dumps({"name": "old-skill-pkg"})))
            if path == f"/repos/{slug}/contents/pyproject.toml":
                return httpx.Response(200, json=b64('[project]\nname = "old-skill-py"\n'))
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


async def fake_web_search(query, *, client=None):
    return "1. Found\n   https://github.com/web/found\n   a skills repo\n2. Topic\n   https://github.com/topics/agent-skills\n"


def make(tmp_path, requests, **kw):
    cfg = Cfg({
        "skills": {"repos": ["https://github.com/listed/skills"], "skiller": {"queries": ["topic:agent-skills"], "webQueries": ["agent skills github"], "minStars": 20, "maxDaysSinceCommit": 365, "minScore": 60}},
    })
    client = httpx.AsyncClient(transport=fake_github(requests, **kw))
    bus = Bus()
    return Skiller(cfg, FakeSkills(tmp_path), tmp_path, client=client, bus=bus, web_search=fake_web_search, now=lambda: NOW), bus


async def test_run_once_scores_persists_and_reports(tmp_path):
    requests = []
    sk, bus = make(tmp_path, requests)
    report = await sk.run_once()
    assert report["approved"] == ["good/skills"]
    assert set(report["rejected"]) == {"old/skills", "npm/skills", "py/skills", "web/found"}
    repos = json.loads((tmp_path / "skiller.json").read_text())["repos"]
    assert "listed/skills" not in repos  # already a default repo: not scouted
    assert any("last push" in r for r in repos["old/skills"]["reasons"])
    assert "deprecated package: npm old-skill-pkg" in repos["npm/skills"]["reasons"]
    assert "deprecated package: pypi old-skill-py" in repos["py/skills"]["reasons"]
    assert "no SKILL.md" in repos["web/found"]["reasons"]  # found through the web search
    assert repos["good/skills"]["skillFiles"] == 2 and repos["good/skills"]["verdict"] == "approved"
    assert bus.events == [("skills", {"count": 7, "op": "skiller", "evaluated": 5, "approved": 1})]
    assert sk.report()["approved"][0]["slug"] == "good/skills"
    await sk.client.aclose()


async def test_only_metadata_hosts_are_contacted(tmp_path):
    requests = []
    sk, _ = make(tmp_path, requests)
    await sk.run_once()
    hosts = {httpx.URL(u).host for u in requests}
    assert hosts <= {"api.github.com", "registry.npmjs.org", "pypi.org"}
    assert not any("/zipball" in u or "/tarball" in u or u.endswith(".git") for u in requests)
    await sk.client.aclose()


async def test_recently_checked_repos_are_skipped(tmp_path):
    requests = []
    sk, _ = make(tmp_path, requests)
    await sk.run_once()
    second = await sk.run_once()
    assert second["evaluated"] == 0  # all checked less than recheckDays ago
    await sk.client.aclose()


async def test_rate_limit_ends_the_run_cleanly(tmp_path):
    requests = []
    sk, _ = make(tmp_path, requests, rate_limited=True)
    report = await sk.run_once()
    assert report["evaluated"] == 0 and "rate limit" in report["errors"][0]
    await sk.client.aclose()


async def test_loop_runs_then_stops_on_shutdown(tmp_path):
    requests = []
    sk, _ = make(tmp_path, requests)
    sk.config.value["skills"]["skiller"].update({"firstRunMinutes": 0.0005, "intervalHours": 1})
    shutdown = asyncio.Event()
    task = asyncio.ensure_future(sk.loop(shutdown))
    for _ in range(200):
        if sk.state.get("lastRun"):
            break
        await asyncio.sleep(0.01)
    assert sk.state["lastRun"] == NOW
    shutdown.set()
    await asyncio.wait_for(task, 2)
    await sk.client.aclose()


async def test_routes_report_and_run(tmp_path):
    from httpx import ASGITransport

    from backend.app import create_app

    requests = []
    sk, _ = make(tmp_path, requests)
    app = create_app(skiller=sk)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/skills/skiller")).json()["approved"] == []
        body = (await c.post("/api/skills/skiller/run")).json()
        assert body["approved"] == ["good/skills"] and "security review" in body["report"]["install"]
    await sk.client.aclose()
