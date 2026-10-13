"""FastAPI app factory. Routes are mounted here as each phase lands."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend.bus import Bus
from backend.config import Config
from backend.router.index import Router
from backend.routes import api_state, events, gateway, static
from backend.store import Store

ROOT = Path(__file__).resolve().parents[2]  # agent-world/


def data_home() -> Path:
    home = Path(os.environ["AGENT_WORLD_HOME"]).resolve() if os.environ.get("AGENT_WORLD_HOME") else ROOT
    return home / "data"


def _make_lifespan(shutdown: asyncio.Event, router: Router):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Flips open SSE streams out of their wait loop so uvicorn doesn't
        # hang waiting for connections that would otherwise never close (S3).
        shutdown.set()
        await router.client.aclose()

    return lifespan


def create_app(*, config=None, store=None, bus=None, router=None) -> FastAPI:
    config = config or Config(ROOT / "config")
    store = store or Store(data_home())
    bus = bus or Bus()
    router = router or Router(config, data_home(), bus)
    shutdown = asyncio.Event()
    app = FastAPI(lifespan=_make_lifespan(shutdown, router))
    # Order matters: static.py's catch-all route must be mounted last, or it
    # would swallow /api/*, /v1/* and /vendor/* first.
    api_state.mount(app, config=config, store=store, bus=bus, router=router)
    events.mount(app, bus=bus, shutdown=shutdown)
    gateway.mount(app, config=config, router=router)
    static.mount(
        app,
        public_root=ROOT / "public",
        three_build=ROOT / "node_modules" / "three" / "build",
        three_addons=ROOT / "node_modules" / "three" / "examples" / "jsm",
        store=store,
    )
    app.state.config = config
    app.state.store = store
    app.state.bus = bus
    app.state.router = router
    app.state.shutdown = shutdown
    return app
