import httpx
import pytest

from backend.app import create_app
from backend.store import Store


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_HOME", str(tmp_path))  # isolates Brain/Store from the repo's own data/
    app = create_app(store=Store(tmp_path))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1")


@pytest.mark.asyncio
async def test_api_router_snapshot(client):
    async with client as c:
        res = await c.get("/api/router")
        assert res.status_code == 200
        body = res.json()
        assert "mode" in body and "providers" in body and "combos" in body


@pytest.mark.asyncio
async def test_api_router_test_demo(client):
    async with client as c:
        res = await c.post("/api/router/test", json={"use": "fast"})
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert "pong" in body["text"].lower() or body["text"]


@pytest.mark.asyncio
async def test_v1_models_lists_combos_and_bare_models(client):
    async with client as c:
        res = await c.get("/v1/models")
        assert res.status_code == 200
        body = res.json()
        assert body["object"] == "list"
        ids = [d["id"] for d in body["data"]]
        assert any(i.startswith("combo:") for i in ids)
        assert len(ids) == len(set(ids))  # de-duplicated


@pytest.mark.asyncio
async def test_v1_chat_completions_demo(client):
    async with client as c:
        res = await c.post("/v1/chat/completions", json={"model": "combo:fast", "messages": [{"role": "user", "content": "ping"}]})
        assert res.status_code == 200
        body = res.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["usage"]["total_tokens"] == body["usage"]["prompt_tokens"] + body["usage"]["completion_tokens"]


@pytest.mark.asyncio
async def test_v1_chat_completions_requires_messages(client):
    async with client as c:
        res = await c.post("/v1/chat/completions", json={"model": "combo:fast"})
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_v1_chat_completions_stream_single_chunk(client):
    async with client as c:
        async with c.stream("POST", "/v1/chat/completions", json={"model": "combo:fast", "stream": True, "messages": [{"role": "user", "content": "ping"}]}) as resp:
            assert resp.status_code == 200
            text = ""
            async for chunk in resp.aiter_text():
                text += chunk
    frames = [f for f in text.split("\n\n") if f.strip()]
    assert frames[-1] == "data: [DONE]"
    assert "chat.completion.chunk" in frames[0]


@pytest.mark.asyncio
async def test_gateway_requires_api_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_API_KEY", "secret-key")
    async with client as c:
        res = await c.get("/v1/models")
        assert res.status_code == 401
        res2 = await c.get("/v1/models", headers={"authorization": "Bearer secret-key"})
        assert res2.status_code == 200


@pytest.mark.asyncio
async def test_unknown_gateway_route(client):
    async with client as c:
        res = await c.get("/v1/does-not-exist")
        assert res.status_code == 404
