import httpx
import pytest

from backend.app import create_app
from backend.store import Store


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_HOME", str(tmp_path))
    app = create_app(store=Store(tmp_path))
    await app.state.skills.reindex()
    transport = httpx.ASGITransport(app=app)
    return app, httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_api_skills_summary_and_search(client):
    app, c = client
    async with c:
        res = await c.get("/api/skills")
        assert res.status_code == 200
        body = res.json()
        assert "count" in body and "results" in body


async def test_api_skills_read_missing(client):
    app, c = client
    async with c:
        res = await c.get("/api/skills/read", params={"id": "nope"})
        assert res.status_code == 404


async def test_api_skills_reindex(client):
    app, c = client
    async with c:
        res = await c.post("/api/skills/reindex")
        assert res.status_code == 200
        assert "count" in res.json()


async def test_api_skills_repo_rejects_bad_url(client):
    app, c = client
    async with c:
        res = await c.post("/api/skills/repo", json={"url": "not a url"})
        assert res.status_code == 400


async def test_api_brain_add_and_search(client):
    app, c = client
    async with c:
        res = await c.post("/api/brain", json={"title": "A", "text": "remember this pizza fact"})
        assert res.status_code == 201
        assert res.json()["title"] == "A"
        res2 = await c.get("/api/brain", params={"q": "pizza fact"})
        assert res2.status_code == 200
        assert res2.json()["count"] == 1
        assert len(res2.json()["notes"]) == 1


async def test_api_brain_requires_text(client):
    app, c = client
    async with c:
        res = await c.post("/api/brain", json={"title": "A", "text": "  "})
        assert res.status_code == 400


async def test_api_state_includes_real_skills_and_brain(client):
    app, c = client
    async with c:
        res = await c.get("/api/state")
        body = res.json()
        assert "sources" in body["skills"]
        assert body["brain"] == {"count": 0, "recent": []}
