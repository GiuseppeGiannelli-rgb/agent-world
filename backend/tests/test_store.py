import asyncio
import json

import pytest


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


def test_list_and_get(data_dir):
    from backend.store import Store

    runs_dir = data_dir / "runs"
    runs_dir.mkdir()
    (runs_dir / "a.json").write_text(json.dumps({"id": "a", "status": "completed", "createdAt": "2026-10-10T00:00:00.000Z"}))
    (runs_dir / "b.json").write_text(json.dumps({"id": "b", "status": "completed", "createdAt": "2026-10-13T00:00:00.000Z"}))
    store = Store(data_dir)
    assert store.get("a")["id"] == "a"
    assert [r["id"] for r in store.list()] == ["b", "a"]  # newest first


def test_interrupted_status_rewritten_in_memory_only(data_dir):
    from backend.store import Store

    runs_dir = data_dir / "runs"
    runs_dir.mkdir()
    f = runs_dir / "r.json"
    f.write_text(json.dumps({"id": "r", "status": "running", "createdAt": "2026-10-13T00:00:00.000Z"}))
    store = Store(data_dir)
    run = store.get("r")
    assert run["status"] == "stopped"
    assert run["error"] == "Interrupted: the server stopped while this run was active."
    # The file on disk must NOT have been touched yet.
    on_disk = json.loads(f.read_text())
    assert on_disk["status"] == "running"
    assert "error" not in on_disk


def test_corrupt_file_is_skipped(data_dir):
    from backend.store import Store

    runs_dir = data_dir / "runs"
    runs_dir.mkdir()
    (runs_dir / "broken.json").write_text("{not json")
    store = Store(data_dir)  # must not raise
    assert store.list() == []


@pytest.mark.asyncio
async def test_debounced_save_coalesces_writes(data_dir):
    from backend.store import Store

    store = Store(data_dir)
    run = {"id": "x", "status": "running", "createdAt": "now"}
    store.save(run)
    run["status"] = "completed"
    store.save(run)  # same id within 400ms: replaces the pending write, doesn't add one
    f = data_dir / "runs" / "x.json"
    assert not f.exists()
    await asyncio.sleep(0.6)
    assert json.loads(f.read_text())["status"] == "completed"


def test_immediate_save_writes_now(data_dir):
    from backend.store import Store

    store = Store(data_dir)
    run = {"id": "y", "status": "completed", "createdAt": "now"}
    store.save(run, immediate=True)
    f = data_dir / "runs" / "y.json"
    assert json.loads(f.read_text())["status"] == "completed"


def test_indent_matches_node(data_dir):
    from backend.store import Store

    store = Store(data_dir)
    run = {"id": "z", "status": "completed", "createdAt": "now"}
    store.save(run, immediate=True)
    text = (data_dir / "runs" / "z.json").read_text()
    assert text == json.dumps(run, indent=1)


# ---------- spec 11 T04: atomic writes and the workers' checkpoints ----------


def test_a_write_that_dies_halfway_leaves_the_last_good_file(data_dir, monkeypatch):
    """D18: the store writes often now (a checkpoint at every valid step), and a
    write cut halfway (a crash, a full disk) must leave the last good file: before
    T04 the run file was rewritten in place, and a broken one is skipped at the next
    start, i.e. the run disappeared."""
    from pathlib import Path

    from backend.store import Store

    store = Store(data_dir)
    run = {"id": "r1", "status": "running", "createdAt": "now", "tasks": []}
    store.save(run, immediate=True)
    store.save_sessions("r1", {"w1.1": {"messages": [{"role": "user", "content": "brief"}]}}, immediate=True)
    real = Path.write_text

    def dies_halfway(self, text, *a, **k):
        real(self, text[: len(text) // 2], *a, **k)
        raise OSError("the disk is full")

    monkeypatch.setattr(Path, "write_text", dies_halfway)
    run["status"] = "completed"
    with pytest.raises(OSError):
        store.save(run, immediate=True)
    with pytest.raises(OSError):
        store.save_sessions("r1", {"w1.1": {"messages": []}}, immediate=True)
    monkeypatch.undo()
    assert json.loads((data_dir / "runs" / "r1.json").read_text(encoding="utf-8"))["status"] == "running"
    assert Store(data_dir).get("r1")["id"] == "r1"  # still there after a restart
    assert Store(data_dir).load_sessions("r1")["w1.1"]["messages"][0]["content"] == "brief"
    assert not list((data_dir / "runs").rglob("*.tmp"))


@pytest.mark.asyncio
async def test_sessions_are_debounced_and_removed_when_empty(data_dir):
    from backend.store import Store

    store = Store(data_dir)
    f = data_dir / "runs" / "sessions" / "r1.json"
    store.save_sessions("r1", {"w1.1": {"step": 1}})
    store.save_sessions("r1", {"w1.1": {"step": 2}})  # replaces the pending write
    assert not f.exists()
    await asyncio.sleep(0.6)
    assert json.loads(f.read_text(encoding="utf-8")) == {"w1.1": {"step": 2}}
    assert store.load_sessions("r1") == {"w1.1": {"step": 2}}
    # an immediate save wins over the pending one
    store.save_sessions("r1", {"w1.1": {"step": 3}})
    store.save_sessions("r1", {"w1.1": {"step": 4, "note": "è così"}}, immediate=True)
    await asyncio.sleep(0.6)
    assert store.load_sessions("r1") == {"w1.1": {"step": 4, "note": "è così"}}
    assert "è così" in f.read_text(encoding="utf-8")  # not escaped, as before
    store.save_sessions("r1", {}, immediate=True)  # nothing left to resume: no file
    assert not f.exists() and store.load_sessions("r1") == {}
    f.write_text("{not json", encoding="utf-8")
    assert store.load_sessions("r1") == {}
    assert store.load_sessions("nope") == {}


@pytest.mark.asyncio
async def test_a_busy_run_still_reaches_the_disk(data_dir):
    """Measured on the demo: a delay that starts again at every call never writes
    while the workers keep stepping (8 workers in a live run step about every
    0.4 s between them). A pending write keeps its time and takes the newest state."""
    from backend.store import Store

    store = Store(data_dir)
    run = {"id": "busy", "status": "running", "createdAt": "now", "step": 0}
    sessions, runs = data_dir / "runs" / "sessions" / "busy.json", data_dir / "runs" / "busy.json"
    for i in range(12):
        run["step"] = i
        store.save(run)
        store.save_sessions("busy", {"w1.1": {"step": i}})
        await asyncio.sleep(0.1)
        if sessions.exists() and runs.exists():
            break
    assert sessions.exists() and runs.exists() and i <= 6, i
    assert json.loads(sessions.read_text(encoding="utf-8"))["w1.1"]["step"] >= 3  # the newest state when it wrote
    assert json.loads(runs.read_text(encoding="utf-8"))["step"] >= 3


def test_leftover_temp_files_are_swept_at_start(data_dir):
    from backend.store import Store

    runs = data_dir / "runs"
    (runs / "sessions").mkdir(parents=True)
    (runs / "a.json.tmp").write_text("{half", encoding="utf-8")
    (runs / "sessions" / "a.json.tmp").write_text("{", encoding="utf-8")
    store = Store(data_dir)
    assert store.list() == []
    assert not list(runs.rglob("*.tmp"))


def test_has(data_dir):
    from backend.store import Store

    store = Store(data_dir)
    assert not store.has("nope")
    store.save({"id": "w", "status": "completed", "createdAt": "now"}, immediate=True)
    assert store.has("w")
