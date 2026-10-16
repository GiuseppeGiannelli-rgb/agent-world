import os
import sys
from pathlib import Path

import pytest

# Spec 05: an app started with its lifespan (test_events.py) must not schedule the
# Skiller's background scouting of GitHub. The Node launchers do the same (demoEnv).
os.environ["AGENT_WORLD_SKILLER"] = "0"
# N15: nor clone the missing skills.repos into skills/vendor/ (source 4).
os.environ["AGENT_WORLD_SKILL_REPOS"] = "0"
# Spec 08: nor ask the providers (or a local Ollama) which models they have.
os.environ["AGENT_WORLD_DISCOVER"] = "0"


@pytest.fixture(autouse=True)
def isolated_user_state(tmp_path_factory, monkeypatch):
    """N15: every test gets its own preferences file (empty: the shipped defaults
    only) and its own data home, so it neither reads the user's local.json nor
    writes it, nor logs calls or runs into the repo's data/ (sources 1-3)."""
    root = tmp_path_factory.mktemp("user-state")
    monkeypatch.setenv("AGENT_WORLD_LOCAL_CONFIG", str(root / "local.json"))
    monkeypatch.setenv("AGENT_WORLD_HOME", str(root / "home"))
    return root


@pytest.fixture(autouse=True)
def no_edge_tts(monkeypatch):
    """Spec 08: edge-tts ships with the backend, and a live speech call would send
    its text to Microsoft. Every test sees it as not installed; a test that wants
    the neural voice puts its own fake in sys.modules["edge_tts"]."""
    monkeypatch.setitem(sys.modules, "edge_tts", None)


# ---------- N15: the tests never touch the user's own files ----------
# The repository holds the user's state next to the code: config/local.json (the
# preferences saved from the app), data/ (runs, Brain, call logs) and skills/vendor/
# (the skill repos cloned at startup). A snapshot is taken when the session starts
# and compared when it ends: any file a test wrote there turns the run red, with
# the list. If the app itself is running from this folder while the tests run, its
# own writes to data/ show up too: stop it, or ignore that part of the report.

REPO = Path(__file__).resolve().parents[2]
WATCHED_TREES = ("data", "skills/vendor")
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv"}


def _tree(root: Path) -> dict[str, int]:
    files: dict[str, int] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            try:
                files[p.relative_to(REPO).as_posix()] = p.stat().st_mtime_ns
            except OSError:
                pass
    return files


def repo_snapshot() -> dict:
    local = REPO / "config" / "local.json"
    snap = {"config/local.json": (local.stat().st_mtime_ns, local.read_bytes()) if local.exists() else None}
    for rel in WATCHED_TREES:
        snap[rel] = _tree(REPO / rel) if (REPO / rel).exists() else {}
    return snap


def repo_leaks(before: dict, after: dict) -> list[str]:
    leaks = []
    if before["config/local.json"] != after["config/local.json"]:
        leaks.append("config/local.json (the user's preferences) was written")
    for rel in WATCHED_TREES:
        b, a = before[rel], after[rel]
        leaks += [f"{p} was created" for p in sorted(set(a) - set(b))]
        leaks += [f"{p} was changed" for p in sorted(p for p in set(a) & set(b) if a[p] != b[p])]
        leaks += [f"{p} was deleted" for p in sorted(set(b) - set(a))]
    return leaks


def pytest_sessionstart(session):
    session.config._aw_repo_snapshot = repo_snapshot()


def pytest_sessionfinish(session, exitstatus):
    before = getattr(session.config, "_aw_repo_snapshot", None)
    if before is None:
        return
    leaks = repo_leaks(before, repo_snapshot())
    if leaks:
        shown = leaks[:20] + ([f"... and {len(leaks) - 20} more"] if len(leaks) > 20 else [])
        print("\n\nN15: the tests wrote the user's own files in the repository:\n  " + "\n  ".join(shown))
        session.exitstatus = 1
