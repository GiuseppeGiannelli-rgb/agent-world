import httpx
import pytest

from backend.app import ROOT, create_app
from backend.config import Config
from backend.store import Store


@pytest.fixture
def app_and_store(tmp_path):
    store = Store(tmp_path)
    config = Config(ROOT / "config")
    app = create_app(config=config, store=store)
    return app, store, config


@pytest.fixture
def client(app_and_store):
    app, _, _ = app_and_store
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_api_state_has_stub_and_real_fields(client):
    async with client as c:
        res = await c.get("/api/state")
        assert res.status_code == 200
        body = res.json()
        assert set(body.keys()) == {"mode", "config", "agents", "run", "runs", "router", "media", "skills", "brain"}
        assert body["config"]["ceo"]["id"] == "ada"
        assert body["agents"] == []
        assert body["run"] is None
        assert body["runs"] == []
        # P3 replaced the router stub with Router.snapshot() -- same shape, real data.
        assert set(body["router"].keys()) == {"mode", "providers", "combos", "recent"}
        assert body["media"] == {"ready": False, "image": [], "speech": []}
        assert body["skills"] == {"count": 0, "sources": []}
        assert body["brain"] == {"count": 0, "recent": []}


async def test_api_config_get(client):
    async with client as c:
        res = await c.get("/api/config")
        assert res.status_code == 200
        assert res.json()["ceo"]["id"] == "ada"
        assert "server" not in res.json()  # publicConfig never leaks server/secrets


async def test_api_config_post_updates_and_emits(client, app_and_store):
    app, _, config = app_and_store
    async with client as c:
        res = await c.post("/api/config", json={"limits": {"maxParallel": 3}})
        assert res.status_code == 200
        assert res.json()["limits"]["maxParallel"] == 3
    assert config.get()["limits"]["maxParallel"] == 3


async def test_api_config_post_rejects_bad_combo(client):
    async with client as c:
        res = await c.post("/api/config", json={"combos": {"broken": {"models": ["not-a-provider-slash-model", 5]}}})
        assert res.status_code == 400
        assert "models" in res.json()["error"]


async def test_api_runs_list_and_get(client, app_and_store):
    _, store, _ = app_and_store
    store.save({"id": "r1", "goal": "demo", "status": "completed", "mode": "demo", "createdAt": "2026-10-13T00:00:00.000Z", "finishedAt": None, "complexity": "simple", "workstreams": [], "tasks": []}, immediate=True)
    async with client as c:
        res = await c.get("/api/runs")
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["id"] == "r1"

        res2 = await c.get("/api/runs/r1")
        assert res2.status_code == 200
        assert res2.json()["id"] == "r1"

        res3 = await c.get("/api/runs/missing")
        assert res3.status_code == 404
