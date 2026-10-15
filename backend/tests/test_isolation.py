"""N15: the tests never read or write the user's own state. The repository
keeps it next to the code: config/local.json (the preferences saved from the
app), data/ (runs, Brain, call logs) and skills/vendor/ (the skill repos the
app clones at startup). Four sources wrote there: test_state.py and
test_events.py through POST /api/config (1, 2), test_runs.py through the
router's call logs (3), and any test starting the app's lifespan through a
`git clone` of skills.repos (4). conftest.py also checks the whole session."""

import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest

from backend.app import ROOT, create_app, data_home
from backend.config import Config
from backend.store import Store
from conftest import repo_leaks, repo_snapshot


def _defaults_dir(tmp_path: Path, **patch) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    value = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
    value.update(patch)
    (d / "default.json").write_text(json.dumps(value), encoding="utf-8")
    return d


def _inside(path, root) -> bool:
    return Path(path).resolve().is_relative_to(Path(root).resolve())


# ---------- the mechanism: where the preferences live ----------


def test_the_preferences_follow_agent_world_local_config(tmp_path, monkeypatch):
    d = _defaults_dir(tmp_path)
    prefs = tmp_path / "elsewhere" / "local.json"
    monkeypatch.setenv("AGENT_WORLD_LOCAL_CONFIG", str(prefs))
    Config(d).update({"limits": {"maxParallel": 2}})
    assert json.loads(prefs.read_text(encoding="utf-8")) == {"limits": {"maxParallel": 2}}
    assert not (d / "local.json").exists()
    assert Config(d).get()["limits"]["maxParallel"] == 2  # and they are read back from there


def test_an_explicit_local_file_wins_over_the_variable(tmp_path, monkeypatch):
    d = _defaults_dir(tmp_path)
    monkeypatch.setenv("AGENT_WORLD_LOCAL_CONFIG", str(tmp_path / "from-env.json"))
    mine = tmp_path / "mine.json"
    Config(d, local_file=mine).update({"limits": {"maxParallel": 4}})
    assert mine.exists() and not (tmp_path / "from-env.json").exists()


def test_without_the_variable_they_stay_next_to_default_json(tmp_path, monkeypatch):
    """What the app does for the user: nothing changes there."""
    d = _defaults_dir(tmp_path)
    monkeypatch.delenv("AGENT_WORLD_LOCAL_CONFIG", raising=False)
    cfg = Config(d)
    assert cfg.local_file == d / "local.json"
    cfg.update({"limits": {"maxParallel": 5}})
    assert (d / "local.json").exists()


# ---------- the tests themselves (sources 1-3) ----------


def test_in_a_test_the_repo_config_never_means_the_users_preferences():
    # sources 1 and 2: Config(ROOT / "config") in test_state.py, create_app() in test_events.py
    cfg = Config(ROOT / "config")
    assert not _inside(cfg.local_file, ROOT), cfg.local_file
    assert cfg.defaults_file == ROOT / "config" / "default.json"  # the shipped defaults are still the real ones


def test_in_a_test_create_app_keeps_preferences_and_data_out_of_the_repo():
    # source 3: the router wrote its call logs into the repo's data/calls
    app = create_app()
    assert not _inside(app.state.config.local_file, ROOT), app.state.config.local_file
    assert not _inside(data_home(), ROOT), data_home()
    assert not _inside(app.state.router.data_dir, ROOT), app.state.router.data_dir
    assert not _inside(app.state.ctx.workspace_root, ROOT), app.state.ctx.workspace_root


async def test_saving_preferences_in_a_test_leaves_the_users_file_alone():
    before = repo_snapshot()
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        res = await c.post("/api/config", json={"limits": {"maxParallel": 7}, "ui": {"language": "de"}})
        assert res.status_code == 200
    assert app.state.config.get()["limits"]["maxParallel"] == 7
    assert repo_leaks(before, repo_snapshot()) == []


# ---------- source 4: no skill repo cloned at startup ----------


async def test_the_startup_clones_no_skill_repo_in_tests(tmp_path, monkeypatch):
    """The lifespan clones skills.repos that are missing: on a fresh clone of
    the repository a test reached GitHub and wrote into skills/vendor/."""
    import backend.skills as skills_mod
    from backend.skills import SkillLibrary

    calls = []

    async def fake_git(args):
        calls.append(args)

    monkeypatch.setattr(skills_mod, "_git", fake_git)
    d = _defaults_dir(tmp_path, skills={"sources": ["skills"], "repos": ["https://github.com/example-owner/example-repo"], "perTask": 3, "skiller": {"enabled": False}})
    config = Config(d)
    lib = SkillLibrary(tmp_path / "root", config)  # its vendor/ is under tmp, not the repo
    indexed = asyncio.Event()
    real_reindex = lib.reindex

    async def reindex():
        n = await real_reindex()
        indexed.set()
        return n

    lib.reindex = reindex
    app = create_app(config=config, store=Store(tmp_path), skills=lib)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(indexed.wait(), 10)
        await asyncio.sleep(0.3)  # ensure_repos would run right after the reindex
    assert calls == []


def test_the_switch_is_only_for_tests(tmp_path, monkeypatch):
    """Without AGENT_WORLD_SKILL_REPOS=0 the app still clones its repos, as before."""
    from backend.app import skill_repos_enabled

    monkeypatch.delenv("AGENT_WORLD_SKILL_REPOS", raising=False)
    assert skill_repos_enabled() is True
    monkeypatch.setenv("AGENT_WORLD_SKILL_REPOS", "0")
    assert skill_repos_enabled() is False


# ---------- the session guard itself ----------


def test_the_guard_reports_every_kind_of_leak():
    before = {"config/local.json": (1, b"{}"), "data": {"data/runs/a.json": 1, "data/brain.json": 5}, "skills/vendor": {}}
    after = {
        "config/local.json": (2, b"{}"),  # rewritten, even with the same bytes
        "data": {"data/runs/a.json": 1, "data/brain.json": 6, "data/calls/x.json": 1},
        "skills/vendor": {"skills/vendor/o-r/SKILL.md": 1},
    }
    leaks = repo_leaks(before, after)
    assert leaks == [
        "config/local.json (the user's preferences) was written",
        "data/calls/x.json was created",
        "data/brain.json was changed",
        "skills/vendor/o-r/SKILL.md was created",
    ]
    assert repo_leaks(before, before) == []
