"""Spec 08: the profiler reads a model's name (and the metadata of /models, when
there is any) and says what it is: its size in billions of parameters, its
family (reasoning, coder, vision, small), its context window, whether it is
free or local, whether its provider takes JSON mode, and the tier it belongs
to: frontier, smart, code, fast or local. The router puts a model found at
runtime (discover) at the tail of the combo of its tier; run.py and the
Tasker read the profile to size the RAG context (compact for small, free and
local models)."""

import httpx
import pytest

from backend.router import profiler


@pytest.mark.parametrize(
    "target,tier",
    [
        ("anthropic/claude-opus-5-5", "frontier"),
        ("openai/gpt-5", "frontier"),
        ("gemini/gemini-3.1-pro-preview", "frontier"),
        ("deepseek/deepseek-reasoner", "frontier"),
        ("openrouter/deepseek/deepseek-r1:free", "frontier"),
        ("groq/qwen-qwq-32b", "frontier"),
        ("openai/o3", "frontier"),
        ("together/meta-llama/Llama-3.3-70B-Instruct-Turbo", "frontier"),
        ("openrouter/qwen/qwen-2.5-coder-32b-instruct:free", "code"),
        ("mistral/codestral-latest", "code"),
        ("anthropic/claude-sonnet-5-5", "smart"),
        ("deepseek/deepseek-chat", "smart"),
        ("openai/gpt-4o", "smart"),
        ("cohere/command-a-03-2025", "smart"),
        ("cerebras/qwen-3.8-27b", "smart"),
        ("groq/llama-3.1-8b-instant", "fast"),
        ("gemini/gemini-2.5-flash", "fast"),
        ("gemini/gemini-2.5-flash-lite", "fast"),
        ("anthropic/claude-haiku-5-5", "fast"),
        ("openai/gpt-5-mini", "fast"),
        ("openrouter/openrouter/free", "fast"),
        ("ollama/qwen3:8b", "local"),
        ("lmstudio/local-model", "local"),
        ("localopenai/phi-4-mini", "local"),
    ],
)
def test_every_model_lands_on_its_tier(target, tier):
    assert profiler.profile(target)["tier"] == tier


@pytest.mark.parametrize(
    "target,params",
    [
        ("together/meta-llama/Llama-3.3-70B-Instruct-Turbo", 70),
        ("ollama/qwen3:8b", 8),
        ("ollama/qwen2.5:0.5b", 0.5),
        ("groq/llama-3.1-8b-instant", 8),
        ("mistral/mixtral-8x7b", 56),
        ("cerebras/qwen-3.8-27b", 27),
        ("openai/gpt-5", None),
        ("gemini/gemini-2.5-flash", None),
    ],
)
def test_the_size_is_read_from_the_name(target, params):
    assert profiler.profile(target)["paramsB"] == params


def test_the_families():
    p = profiler.profile("openrouter/deepseek/deepseek-r1:free")
    assert p["reasoning"] and p["free"] and not p["local"]
    assert profiler.profile("openrouter/qwen/qwen-2.5-coder-32b-instruct:free")["coder"]
    assert profiler.profile("openai/gpt-4o")["vision"]
    assert profiler.profile("anthropic/claude-haiku-5-5")["small"]
    assert profiler.profile("ollama/qwen3:8b")["local"]
    assert profiler.profile("gemini/gemini-2.5-flash")["free"]  # Gemini Flash has a free tier
    assert not profiler.profile("anthropic/claude-sonnet-5-5")["free"]


def test_the_context_comes_from_the_metadata_or_the_family():
    assert profiler.profile("anthropic/claude-sonnet-5-5")["context"] >= 200_000
    assert profiler.profile("gemini/gemini-2.5-flash")["context"] >= 1_000_000
    assert profiler.profile("ollama/qwen3:8b")["context"] <= 32_768
    assert profiler.profile("openrouter/x/y:free", {"context_length": 8192})["context"] == 8192


def test_json_mode_follows_the_provider():
    assert profiler.profile("groq/m", provider={"kind": "openai"})["json"] is True
    assert profiler.profile("x/m", provider={"kind": "openai", "jsonMode": False})["json"] is False


@pytest.mark.parametrize(
    "target,meta,compact",
    [
        ("anthropic/claude-opus-5-5", None, False),
        ("anthropic/claude-sonnet-5-5", None, False),
        ("openai/gpt-5", None, False),
        ("anthropic/claude-opus-5-5", {"context_length": 32768}, True),  # a small window, whatever the model
        ("gemini/gemini-2.5-flash", None, True),
        ("openrouter/meta-llama/llama-3.3-70b-instruct:free", None, True),
        ("ollama/qwen3:8b", None, True),
        ("groq/llama-3.1-8b-instant", None, True),
    ],
)
def test_compact_rag_mode_for_small_free_and_local_models(target, meta, compact):
    assert profiler.profile(target, meta)["compact"] is compact


def test_the_combos_a_found_model_joins():
    assert profiler.combos_for(profiler.profile("ollama/qwen3:8b")) == ["local"]
    assert profiler.combos_for(profiler.profile("ollama/qwen2.5-coder:32b")) == ["local", "code"]
    assert profiler.combos_for(profiler.profile("ollama/llama3.3:70b")) == ["local", "frontier"]
    assert profiler.combos_for(profiler.profile("openrouter/x/y-70b:free")) == ["free"]
    assert profiler.combos_for(profiler.profile("together/Qwen/Qwen2.5-Coder-32B-Instruct")) == ["code"]


# ---------- discovery ----------


class FakeConfig:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


@pytest.fixture
def discovery_router(tmp_path, monkeypatch):
    from backend.router.index import Router

    monkeypatch.setenv("OR_KEY", "k")
    monkeypatch.delenv("NO_KEY", raising=False)
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path == "/ollama/v1/models":
            return httpx.Response(200, json={"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "qwen2.5-coder:32b"}, {"id": "llama3.3:70b"}]})
        if request.url.path == "/or/v1/models":
            return httpx.Response(200, json={"data": [{"id": "meta/llama-x-70b:free", "context_length": 65536}, {"id": "paid/model-x"}]})
        if request.url.path == "/broken/v1/models":
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(404)

    value = {
        "router": {"defaultCombo": "fast", "demoFallback": True, "cooldownBaseMs": 1, "cooldownMaxMs": 1, "authCooldownMs": 1, "logCalls": False, "discoverMax": 6},
        "providers": {
            "mock": {"kind": "mock", "latencyMs": [1, 2]},
            "ollama": {"kind": "openai", "baseUrl": "http://up/ollama/v1", "keyless": True, "local": True},
            "openrouter": {"kind": "openai", "baseUrl": "http://up/or/v1", "keyEnv": "OR_KEY", "discover": "free"},
            "broken": {"kind": "openai", "baseUrl": "http://up/broken/v1", "keyless": True, "local": True},
            "nokey": {"kind": "openai", "baseUrl": "http://up/nokey/v1", "keyEnv": "NO_KEY", "discover": True},
            "off": {"kind": "openai", "baseUrl": "http://up/off/v1", "keyless": True, "local": True, "enabled": False},
            "cloud": {"kind": "openai", "baseUrl": "http://up/cloud/v1", "keyEnv": "OR_KEY"},
        },
        "combos": {
            "frontier": {"models": ["cloud/big"]},
            "code": {"models": ["cloud/coder"]},
            "free": {"models": ["openrouter/openrouter/free"]},
            "local": {"models": ["ollama/qwen3:8b"]},
        },
        "teams": {},
    }
    router = Router(config=FakeConfig(value), data_dir=tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    router.asked = asked
    return router


@pytest.mark.asyncio
async def test_discovery_puts_found_models_at_the_tail_of_their_combo(discovery_router):
    r = discovery_router
    found = await r.discover()
    assert set(found) == {"ollama", "openrouter"}  # broken answered 500, nokey has no key, off is disabled
    assert not any(p.startswith(("/nokey", "/off")) for p in r.asked)
    keys = lambda combo: [t["key"] for t in r.expand(combo)["targets"]]  # noqa: E731
    assert keys("local") == ["ollama/qwen3:8b", "ollama/qwen2.5-coder:32b", "ollama/llama3.3:70b"]  # configured first, no duplicate
    assert keys("code") == ["cloud/coder", "ollama/qwen2.5-coder:32b"]
    assert keys("frontier") == ["cloud/big", "ollama/llama3.3:70b"]
    assert keys("free") == ["openrouter/openrouter/free", "openrouter/meta/llama-x-70b:free"]
    assert [p["model"] for p in r.discovered["openrouter"]] == ["meta/llama-x-70b:free"]  # "discover": "free" lists only those
    assert r.profile("openrouter/meta/llama-x-70b:free")["context"] == 65536  # the metadata is kept


@pytest.mark.asyncio
async def test_discovery_respects_the_limit_per_combo(discovery_router):
    r = discovery_router
    r.cfg["router"]["discoverMax"] = 1
    await r.discover()
    assert [t["key"] for t in r.expand("local")["targets"]] == ["ollama/qwen3:8b", "ollama/qwen2.5-coder:32b"]


@pytest.mark.asyncio
async def test_the_answer_carries_the_profile_of_its_model(discovery_router):
    r = discovery_router
    r.cfg["providers"]["mock"]["latencyMs"] = [1, 2]
    res = await r.chat(use="mock/m", messages=[{"role": "system", "content": "[[role:advisor]]"}, {"role": "user", "content": "?"}])
    assert res["profile"]["key"] == "mock/m"


def test_discovery_is_off_in_the_tests():
    import os

    assert os.environ.get("AGENT_WORLD_DISCOVER") == "0"
