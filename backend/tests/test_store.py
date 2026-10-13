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


def test_has(data_dir):
    from backend.store import Store

    store = Store(data_dir)
    assert not store.has("nope")
    store.save({"id": "w", "status": "completed", "createdAt": "now"}, immediate=True)
    assert store.has("w")
