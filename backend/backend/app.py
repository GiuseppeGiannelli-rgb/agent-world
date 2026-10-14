"""FastAPI app factory. Routes are mounted here as each phase lands."""

import asyncio
import os
import types
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend.brain import Brain
from backend.bus import Bus
from backend.embed import Embedder
from backend.config import Config
from backend.media import Media
from backend.router.index import Router
from backend.routes import api_state, events, gateway, runs, skills_brain, static
from backend.skiller import Skiller
from backend.skills import SkillLibrary
from backend.store import Store
from backend.team import Team

ROOT = Path(__file__).resolve().parents[2]  # agent-world/


def data_home() -> Path:
    home = Path(os.environ["AGENT_WORLD_HOME"]).resolve() if os.environ.get("AGENT_WORLD_HOME") else ROOT
    return home / "data"


def _make_lifespan(shutdown: asyncio.Event, router: Router, skills: SkillLibrary, media: Media, skiller: Skiller):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def boot_skills():
            count = await skills.reindex()
            print(f"Skill Hub    →  {count} skill indicizzate")
            added = await skills.ensure_repos()
            if added:
                print(f"Skill Hub    →  scaricate le repo predefinite {', '.join(added)} ({len(skills.skills)} skill)")

        asyncio.ensure_future(boot_skills())
        # Spec 05: the Skiller scouts GitHub on a schedule. The test launchers
        # set AGENT_WORLD_SKILLER=0, so no test ever reaches the network.
        scout = None
        if os.environ.get("AGENT_WORLD_SKILLER") != "0":
            scout = asyncio.ensure_future(skiller.loop(shutdown))
        yield
        # Flips open SSE streams out of their wait loop so uvicorn doesn't
        # hang waiting for connections that would otherwise never close (S3).
        shutdown.set()
        if scout is not None:
            scout.cancel()
        await router.client.aclose()
        await media.client.aclose()

    return lifespan


def create_app(*, config=None, store=None, bus=None, router=None, skills=None, brain=None, team=None, media=None, skiller=None) -> FastAPI:
    config = config or Config(ROOT / "config")
    home = data_home()
    store = store or Store(home)
    bus = bus or Bus()
    router = router or Router(config, home, bus)
    # one embedder for the Skill Hub and the Brain (Spec 05): provider models
    # through the router's HTTP client, vectors cached in data/embeddings/
    embedder = Embedder(config, router=router, cache_dir=home / "embeddings")
    skills = skills or SkillLibrary(ROOT, config, bus, embedder)
    brain = brain or Brain(home / "brain.json", bus, embedder)
    team = team or Team(bus)
    team.load(config.get()["staff"])  # same as server/index.js at boot
    media = media or Media(config=config, bus=bus)
    skiller = skiller or Skiller(config, skills, home, client=router.client, bus=bus)
    # The same shared context object the Node server hands to every Run.
    ctx = types.SimpleNamespace(
        config=config, bus=bus, store=store, router=router, team=team,
        brain=brain, skills=skills, media=media, workspace_root=str(home / "workspace"),
    )
    live: dict = {}  # runId -> Run while it is active
    chats: dict = {}  # agentId -> chat history (capped at 60 by talk())
    shutdown = asyncio.Event()
    app = FastAPI(lifespan=_make_lifespan(shutdown, router, skills, media, skiller))
    # Order matters: static.py's catch-all route must be mounted last, or it
    # would swallow /api/*, /v1/* and /vendor/* first.
    api_state.mount(app, config=config, store=store, bus=bus, router=router, skills=skills, brain=brain, team=team, media=media, live=live)
    runs.mount(app, config=config, store=store, bus=bus, router=router, team=team, media=media, live=live, chats=chats, ctx=ctx)
    skills_brain.mount(app, skills=skills, brain=brain, skiller=skiller)
    events.mount(app, bus=bus, shutdown=shutdown)
    gateway.mount(app, config=config, router=router)
    static.mount(
        app,
        public_root=ROOT / "public",
        three_build=ROOT / "node_modules" / "three" / "build",
        three_addons=ROOT / "node_modules" / "three" / "examples" / "jsm",
        store=store,
        live=live,
    )
    app.state.config = config
    app.state.store = store
    app.state.bus = bus
    app.state.router = router
    app.state.skills = skills
    app.state.brain = brain
    app.state.team = team
    app.state.media = media
    app.state.skiller = skiller
    app.state.ctx = ctx
    app.state.live = live
    app.state.chats = chats
    app.state.shutdown = shutdown
    return app
