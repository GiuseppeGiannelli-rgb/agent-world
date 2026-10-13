import asyncio
import contextlib
import json

import httpx
import pytest
import uvicorn

from backend.app import create_app
from backend.store import Store

# NOTE: httpx.ASGITransport cannot be used for these tests. It runs the whole
# ASGI call to completion in memory before returning a Response (see its
# source: `await self.app(scope, receive, send)` is awaited fully, then
# `assert response_complete.is_set()`) -- incompatible with a generator that
# is meant to stay open. A real uvicorn server on a real socket is required
# to exercise genuine incremental streaming.


@pytest.fixture
async def live_server(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_HOME", str(tmp_path))  # isolates Brain/Store from the repo's own data/
    app = create_app(store=Store(tmp_path))
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield app, f"http://127.0.0.1:{port}"
    finally:
        app.state.shutdown.set()  # unsticks any SSE generator still polling its queue
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=5)
        except asyncio.TimeoutError:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


class FrameReader:
    """Wraps one response's aiter_text() so it is only ever iterated once --
    httpx raises StreamConsumed on a second full iteration of the same
    response, so repeated `read(n)` calls share this one generator."""

    def __init__(self, resp):
        self._chunks = resp.aiter_text()
        self._buf = ""

    async def read(self, n):
        frames = []
        while len(frames) < n:
            while "\n\n" in self._buf:
                frame, self._buf = self._buf.split("\n\n", 1)
                frames.append(frame + "\n\n")
                if len(frames) >= n:
                    return frames
            self._buf += await self._chunks.__anext__()
        return frames


async def _read_frames(resp, n):
    return await FrameReader(resp).read(n)


@pytest.mark.asyncio
async def test_retry_header_first(live_server):
    app, base_url = live_server
    async with httpx.AsyncClient(base_url=base_url) as client:
        async with client.stream("GET", "/api/events") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            frames = await _read_frames(resp, 1)
            assert frames[0] == "retry: 2000\n\n"


@pytest.mark.asyncio
async def test_config_post_produces_sse_frame(live_server):
    app, base_url = live_server
    async with httpx.AsyncClient(base_url=base_url) as client:
        async with client.stream("GET", "/api/events") as resp:
            reader = asyncio.ensure_future(_read_frames(resp, 2))
            await asyncio.sleep(0.05)
            post = await client.post("/api/config", json={"limits": {"maxParallel": 5}})
            assert post.status_code == 200
            frames = await reader
            assert frames[0] == "retry: 2000\n\n"
            body = json.loads(frames[1][len("data: "):-2])
            assert body["type"] == "config"
            assert body["seq"] == 1
            assert body["payload"]["limits"]["maxParallel"] == 5


@pytest.mark.asyncio
async def test_ping_on_idle(live_server, monkeypatch):
    from backend.routes import events

    monkeypatch.setattr(events, "PING_INTERVAL_S", 0.05)
    app, base_url = live_server
    async with httpx.AsyncClient(base_url=base_url) as client:
        async with client.stream("GET", "/api/events") as resp:
            reader = FrameReader(resp)
            assert (await reader.read(1))[0] == "retry: 2000\n\n"
            # Other subsystems (the real SkillLibrary's startup reindex, here)
            # may also emit on this bus; only the absence of real traffic
            # triggers a ping, so skip past whatever else arrives first.
            for _ in range(20):
                frame = (await reader.read(1))[0]
                if frame == ": ping\n\n":
                    return
            pytest.fail("no ping frame seen")


@pytest.mark.asyncio
async def test_slow_client_disconnects_without_blocking_others(live_server):
    app, base_url = live_server
    async with httpx.AsyncClient(base_url=base_url) as fast_client, httpx.AsyncClient(base_url=base_url) as slow_client:
        async with fast_client.stream("GET", "/api/events") as fast_resp, slow_client.stream("GET", "/api/events") as slow_resp:
            fast_reader = FrameReader(fast_resp)
            slow_reader = FrameReader(slow_resp)
            await fast_reader.read(1)
            await slow_reader.read(1)
            # the slow client never reads again; the fast one keeps receiving
            for i in range(5):
                await fast_client.post("/api/config", json={"limits": {"maxParallel": i + 1}})
            frames = await fast_reader.read(5)
            assert len(frames) == 5


def test_only_forward_types_allowed():
    from backend.bus import FORWARD

    assert FORWARD == {
        "chat", "run", "task", "workstream", "subtasks", "agent", "agent.spawn", "agent.despawn",
        "message", "plan", "file", "waiting", "brain", "skills", "run.done", "router.call", "config",
    }
