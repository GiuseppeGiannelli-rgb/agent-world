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
from backend.downloads import DownloadError, resolve_download_root
from backend.i18n import ui_language
from backend.media import Media
from backend.router.index import Router
from backend.security import LocalGuard, allowed_hosts
from backend.routes import api_state, events, gateway, providers, runs, session, skills_brain, static
from backend.skiller import Skiller
from backend.skills import SkillLibrary
from backend.store import Store
from backend.team import Team

ROOT = Path(__file__).resolve().parents[2]  # agent-world/


def skill_repos_enabled() -> bool:
    """N15: AGENT_WORLD_SKILL_REPOS=0 skips the clone of the missing skills.repos
    at startup. The tests set it: no test reaches GitHub or writes skills/vendor/."""
    return os.environ.get("AGENT_WORLD_SKILL_REPOS") != "0"


def env_file() -> Path:
    """Spec 09: the .env the provider registration reads again. AGENT_WORLD_ENV_FILE
    moves it (the tests do: they never read the developer's real keys)."""
    v = os.environ.get("AGENT_WORLD_ENV_FILE")
    return Path(v) if v else ROOT / ".env"


def data_home() -> Path:
    home = Path(os.environ["AGENT_WORLD_HOME"]).resolve() if os.environ.get("AGENT_WORLD_HOME") else ROOT
    return home / "data"


def _make_lifespan(shutdown: asyncio.Event, router: Router, skills: SkillLibrary, media: Media, skiller: Skiller):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async def boot_skills():
            count = await skills.reindex()
            print(f"Skill Hub    →  {count} skills indexed")
            added = await skills.ensure_repos() if skill_repos_enabled() else []
            if added:
                print(f"Skill Hub    →  default repos downloaded: {', '.join(added)} ({len(skills.skills)} skills)")

        asyncio.ensure_future(boot_skills())
        # Spec 05: the Skiller scouts GitHub on a schedule. The test launchers
        # set AGENT_WORLD_SKILLER=0, so no test ever reaches the network.
        scout = None
        if os.environ.get("AGENT_WORLD_SKILLER") != "0":
            scout = asyncio.ensure_future(skiller.loop(shutdown))
        # Spec 08: the models of the local servers (and of the providers with
        # "discover") join their combos. Off in the tests: AGENT_WORLD_DISCOVER=0.
        finder = None
        if os.environ.get("AGENT_WORLD_DISCOVER") != "0":
            finder = asyncio.ensure_future(router.discovery_loop(shutdown))
        yield
        # Flips open SSE streams out of their wait loop so uvicorn doesn't
        # hang waiting for connections that would otherwise never close (S3).
        shutdown.set()
        if scout is not None:
            scout.cancel()
        if finder is not None:
            finder.cancel()
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
    # Spec 05 D4: external downloads only with CUSTOM_DOWNLOAD_PATH, checked here
    download_root = None
    try:
        download_root = resolve_download_root(os.environ.get("CUSTOM_DOWNLOAD_PATH"), app_root=ROOT, data_dir=home)
    except DownloadError as err:
        print(f"Skiller      →  downloads off: {err}", flush=True)
    if download_root is not None:
        skills.extra_sources = [{"label": "downloads", "dir": download_root, "thirdParty": True}]
    skiller = skiller or Skiller(config, skills, home, client=router.client, bus=bus, download_root=download_root)
    # The same shared context object the Node server hands to every Run.
    ctx = types.SimpleNamespace(
        config=config, bus=bus, store=store, router=router, team=team,
        brain=brain, skills=skills, media=media, workspace_root=str(home / "workspace"),
    )
    live: dict = {}  # runId -> Run while it is active
    chats: dict = {}  # agentId -> chat history (capped at 60 by talk())
    shutdown = asyncio.Event()
    app = FastAPI(lifespan=_make_lifespan(shutdown, router, skills, media, skiller))
    # Spec 07: DNS rebinding and CSRF are refused before any route runs
    # (N13: their 403 speaks the language of the app, read at every refusal);
    # spec 11 T02: from the LAN the API also wants AGENT_WORLD_API_KEY
    app.add_middleware(LocalGuard, hosts=allowed_hosts(config.get()["server"].get("host")), language=lambda: ui_language(config.get()))
    # Order matters: static.py's catch-all route must be mounted last, or it
    # would swallow /api/*, /v1/* and /vendor/* first.
    api_state.mount(app, config=config, store=store, bus=bus, router=router, skills=skills, brain=brain, team=team, media=media, live=live)
    runs.mount(app, config=config, store=store, bus=bus, router=router, team=team, media=media, live=live, chats=chats, ctx=ctx, uploads_dir=home / "uploads")
    skills_brain.mount(app, skills=skills, brain=brain, skiller=skiller, config=config)
    events.mount(app, bus=bus, shutdown=shutdown)
    session.mount(app, config=config)
    gateway.mount(app, config=config, router=router)
    providers.mount(app, config=config, router=router, bus=bus, env_file=env_file)
    static.mount(
        app,
        public_root=ROOT / "public",
        three_build=ROOT / "node_modules" / "three" / "build",
        three_addons=ROOT / "node_modules" / "three" / "examples" / "jsm",
        store=store,
        live=live,
        config=config,
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
    app.state.uploads_dir = home / "uploads"
    app.state.shutdown = shutdown
    return app
