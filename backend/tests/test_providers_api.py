"""Spec 09 §1.2: any OpenAI-compatible provider (or one more model of a known
one) is registered from the Settings while the server runs.

POST /api/providers saves the provider in the preferences (config/local.json,
"custom": true) and puts its models in the combos (the ones asked, or those
of their tier: profiler.combos_for); the router reads the config at every
call, so the next call can reach it. The key stays in .env: the registration
reads .env again for the variables it does not know yet (keys never travel
in a request). DELETE /api/providers/{id} removes a provider the owner added.

The rules of spec 07 hold: https (http only to this computer), no credentials
in the URL, a key variable of its own (*_KEY or *_TOKEN, not AGENT_WORLD_*,
not GITHUB_TOKEN, not the key of another provider: that would send that key
to another server). The tests read a .env of their own (AGENT_WORLD_ENV_FILE,
set by conftest.py): never the developer's real keys."""

import json
import os
import shutil
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def app(tmp_path, monkeypatch):
    from backend.app import create_app
    from backend.brain import Brain
    from backend.config import Config
    from backend.store import Store

    default = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    for section in (default["providers"], default["media"]["providers"]):
        for p in section.values():
            for k in ("keyEnv", "baseUrlEnv"):
                if p.get(k):
                    monkeypatch.delenv(p[k], raising=False)
    for name in ("EXAMPLE_API_KEY", "OTHER_TOKEN"):
        monkeypatch.delenv(name, raising=False)  # restored (removed) after the test, even if .env set it
    env = tmp_path / ".env"
    env.write_text("EXAMPLE_API_KEY=xyz-from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("AGENT_WORLD_ENV_FILE", str(env))
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / "config" / "default.json", tmp_path / "config" / "default.json")
    config = Config(tmp_path / "config")
    config.get()["router"]["logCalls"] = False
    return create_app(config=config, store=Store(tmp_path / "data"), brain=Brain(tmp_path / "brain.json"))


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


GOOD = {"id": "example", "baseUrl": "https://api.example.test/v1", "keyEnv": "EXAMPLE_API_KEY", "models": ["m-small", "m-large"], "combos": ["fast"]}


@pytest.mark.asyncio
async def test_a_provider_registered_now_answers_the_next_call(app):
    seen = []

    def upstream(request):
        seen.append((str(request.url), request.headers.get("authorization"), json.loads(request.content)["model"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}], "usage": {}})

    app.state.router.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    assert app.state.router.mode() == "demo"
    async with client(app) as c:
        res = await c.post("/api/providers", json=GOOD)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["ready"] is True and body["combos"] == {"m-small": ["fast"], "m-large": ["fast"]}
        assert os.environ["EXAMPLE_API_KEY"] == "xyz-from-dotenv"  # read from .env now, no restart
        cfg = app.state.config
        assert cfg.local["providers"]["example"] == {"kind": "openai", "baseUrl": "https://api.example.test/v1", "keyEnv": "EXAMPLE_API_KEY", "custom": True}
        assert cfg.get()["combos"]["fast"]["models"][-2:] == ["example/m-small", "example/m-large"]
        assert app.state.router.mode() == "live"
        out = await app.state.router.chat(use="example/m-small", messages=[{"role": "user", "content": "ping"}])
    assert out["text"] == "pong" and seen == [("https://api.example.test/v1/chat/completions", "Bearer xyz-from-dotenv", "m-small")]


@pytest.mark.asyncio
async def test_without_combos_each_model_joins_the_combos_of_its_tier(app):
    async with client(app) as c:
        res = await c.post("/api/providers", json={**GOOD, "combos": None, "models": ["deepseek-r1-distill-70b", "qwen2.5-coder-32b", "tiny-mini"]})
        assert res.status_code == 200, res.text
    combos = res.json()["combos"]
    assert combos["deepseek-r1-distill-70b"] == ["frontier"] and combos["qwen2.5-coder-32b"] == ["code"] and combos["tiny-mini"] == ["fast"]


@pytest.mark.asyncio
async def test_a_local_server_may_use_http_and_no_key(app):
    async with client(app) as c:
        res = await c.post("/api/providers", json={"id": "mybox", "baseUrl": "http://127.0.0.1:8080/v1", "keyless": True, "models": ["llama3"], "combos": ["local"]})
        assert res.status_code == 200, res.text
        assert res.json()["ready"] is True
    assert app.state.config.get()["providers"]["mybox"]["keyless"] is True


@pytest.mark.parametrize(
    "patch,why",
    [
        ({"id": "Bad Id"}, "id"),
        ({"id": "mock"}, "id"),
        ({"baseUrl": "http://api.example.test/v1"}, "https"),
        ({"baseUrl": "https://user:pass@api.example.test/v1"}, "credentials"),
        ({"baseUrl": "ftp://api.example.test/v1"}, "https"),
        ({"baseUrl": "https://api.example.test/v1?x=1"}, "URL"),
        ({"keyEnv": "OPENAI_API_KEY"}, "OPENAI_API_KEY"),
        ({"keyEnv": "AGENT_WORLD_API_KEY"}, "AGENT_WORLD"),
        ({"keyEnv": "GITHUB_TOKEN"}, "GITHUB_TOKEN"),
        ({"keyEnv": "EXAMPLE_SECRET"}, "_KEY"),
        ({"keyEnv": "lower_key"}, "_KEY"),
        ({"models": []}, "model"),
        ({"models": ["has space"]}, "model"),
        ({"combos": ["nope"]}, "nope"),
    ],
)
@pytest.mark.asyncio
async def test_what_a_registration_may_not_do(app, patch, why):
    async with client(app) as c:
        res = await c.post("/api/providers", json={**GOOD, **patch})
    assert res.status_code == 400 and why.lower() in res.json()["error"].lower(), res.text
    assert "example" not in app.state.config.get()["providers"] or patch.get("id") not in (None, "example")


@pytest.mark.asyncio
async def test_a_known_provider_takes_new_models_but_keeps_its_url_and_key(app):
    async with client(app) as c:
        ok = await c.post("/api/providers", json={"id": "groq", "models": ["moonshotai/kimi-k3"], "combos": ["fast"]})
        assert ok.status_code == 200, ok.text
        assert "groq/moonshotai/kimi-k3" in app.state.config.get()["combos"]["fast"]["models"]
        moved = await c.post("/api/providers", json={"id": "groq", "baseUrl": "https://evil.example/v1", "models": ["x"], "combos": ["fast"]})
        assert moved.status_code == 400
    assert app.state.config.get()["providers"]["groq"]["baseUrl"] == "https://api.groq.com/openai/v1"


@pytest.mark.asyncio
async def test_only_a_provider_the_owner_added_can_be_removed(app):
    async with client(app) as c:
        await c.post("/api/providers", json=GOOD)
        res = await c.delete("/api/providers/example")
        assert res.status_code == 200
        cfg = app.state.config.get()
        assert "example" not in cfg["providers"] and not any(m.startswith("example/") for c_ in cfg["combos"].values() for m in c_["models"])
        assert (await c.delete("/api/providers/groq")).status_code == 400
        assert (await c.delete("/api/providers/nope")).status_code == 404


def test_the_tests_read_their_own_env_file():
    """conftest.py points AGENT_WORLD_ENV_FILE away from the repository's .env."""
    from backend.app import env_file

    assert Path(env_file()).resolve() != (REPO / ".env").resolve()
