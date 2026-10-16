"""Spec 08: what config/default.json guarantees the router.

- Every combo model names a provider that exists; the chain of router.cascade
  is made of real combos, and a combo outside it says where it joins.
- frontier, smart and fast end with free fallbacks (OpenRouter :free, Gemini
  Flash, Groq, Cerebras), so a run with only free keys still has a model.
- Retired models (gemini-2.5-pro, Groq's llama-3.3-70b-versatile and the old
  reasoning models) are not in the combos but have aliases, so a local.json
  that still names them heals itself on the first 404.
- The new providers (Together, Fireworks, SambaNova, Cohere, Hugging Face, a
  generic local OpenAI-compatible URL) are there; GitHub Models is not: GitHub
  retired it on 2026-07-30.
- Each role lands on the tier of the spec: CEO and QA frontier, development
  code, Prompt Lab and generative AI smart, research, content, design and Skill
  Hub fast; a lead plans on smart, a sub-agent works on fast."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
FREE = ("openrouter/openrouter/free", ":free", "gemini/gemini-2.5-flash", "groq/", "cerebras/")


def _is_free(target: str) -> bool:
    return any(target.endswith(f) if f.startswith(":") else target.startswith(f) or target == f for f in FREE)


def test_every_combo_model_names_a_provider():
    for name, combo in CFG["combos"].items():
        for target in combo["models"]:
            provider = target.split("/", 1)[0]
            assert provider in CFG["providers"], f"{name}: {target}"


def test_the_cascade_is_made_of_real_combos():
    chain = CFG["router"]["cascade"]
    assert chain == ["frontier", "smart", "fast", "free", "local"]
    for name in chain:
        assert name in CFG["combos"]
    for name, combo in CFG["combos"].items():
        if name not in chain:
            assert combo.get("joins") in chain, name
    assert CFG["combos"]["code"]["joins"] == "smart"


@pytest.mark.parametrize("name", ["frontier", "smart", "fast"])
def test_the_main_combos_end_with_free_fallbacks(name):
    models = CFG["combos"][name]["models"]
    tail = [m for m in models[-4:] if _is_free(m)]
    assert len(tail) >= 3, models
    assert any(m.startswith("openrouter/") for m in tail)


def test_the_free_combo_is_free_only():
    assert all(_is_free(m) or m.split("/", 1)[0] in ("huggingface", "together", "cohere") for m in CFG["combos"]["free"]["models"])
    assert "openrouter/openrouter/free" in CFG["combos"]["free"]["models"]


def test_retired_models_are_aliased_not_used():
    aliases = CFG["router"]["aliases"]
    assert aliases["gemini/gemini-2.5-pro"][:2] == ["gemini/gemini-3.1-pro-preview", "gemini/gemini-2.5-flash"]
    for old in ("groq/llama-3.3-70b-versatile", "groq/qwen-qwq-32b", "groq/deepseek-r1-distill-llama-70b", "cerebras/llama-3.3-70b"):
        assert aliases[old], old
    retired = {"gemini/gemini-2.5-pro", "gemini/gemini-2.5-pro-preview", "groq/llama-3.3-70b-versatile", "groq/qwen-qwq-32b", "groq/deepseek-r1-distill-llama-70b", "groq/qwen/qwen3-32b", "cerebras/llama-3.3-70b", "cerebras/qwen-3-32b"}
    used = {m for c in CFG["combos"].values() for m in c["models"]}
    assert not used & retired, used & retired  # fragile models in use (previews, :free) may have aliases too
    for targets in aliases.values():
        for t in targets:
            assert t.split("/", 1)[0] in CFG["providers"], t


def test_current_gemini_models_are_in_the_combos():
    used = {m for c in CFG["combos"].values() for m in c["models"]}
    for model in ("gemini/gemini-3.1-pro-preview", "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash-lite"):
        assert model in used, model


@pytest.mark.parametrize(
    "provider,base,key",
    [
        ("together", "https://api.together.xyz/v1", "TOGETHER_API_KEY"),
        ("fireworks", "https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
        ("sambanova", "https://api.sambanova.ai/v1", "SAMBANOVA_API_KEY"),
        ("cohere", "https://api.cohere.ai/compatibility/v1", "COHERE_API_KEY"),
        ("huggingface", "https://router.huggingface.co/v1", "HF_TOKEN"),
    ],
)
def test_the_new_providers(provider, base, key):
    p = CFG["providers"][provider]
    assert p["kind"] == "openai" and p["baseUrl"] == base and p["keyEnv"] == key


def test_github_models_is_not_configured():
    assert not any("github" in p.get("baseUrl", "") or "inference.ai.azure.com" in p.get("baseUrl", "") for p in CFG["providers"].values())


def test_local_providers():
    assert CFG["providers"]["ollama"]["baseUrl"] == "http://127.0.0.1:11434/v1"
    assert CFG["providers"]["lmstudio"]["baseUrl"] == "http://127.0.0.1:1234/v1"
    local = CFG["providers"]["localopenai"]
    assert local["baseUrlEnv"] == "LOCAL_OPENAI_URL" and local["keyless"] is True
    assert {"ollama/qwen3:8b", "lmstudio/local-model", "localopenai/local-model"} <= set(CFG["combos"]["local"]["models"])


def test_a_local_url_provider_is_ready_only_with_its_url(monkeypatch, tmp_path):
    from backend.router.index import Router

    class Cfg:
        def get(self):
            return CFG

    router = Router(Cfg(), tmp_path)
    monkeypatch.delenv("LOCAL_OPENAI_URL", raising=False)
    assert router.provider_ready("localopenai") is False
    monkeypatch.setenv("LOCAL_OPENAI_URL", "http://127.0.0.1:8000/v1")
    assert router.provider_ready("localopenai") is True


@pytest.mark.asyncio
async def test_a_local_url_provider_calls_that_url(monkeypatch):
    import httpx

    from backend.router.providers import call_provider

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setenv("LOCAL_OPENAI_URL", "http://127.0.0.1:8000/v1/")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await call_provider(CFG["providers"]["localopenai"], "localopenai", "m", {"messages": []}, client)
    assert seen == ["http://127.0.0.1:8000/v1/chat/completions"]


def test_every_role_lands_on_its_tier():
    teams = CFG["teams"]
    assert CFG["ceo"]["combo"] == "frontier"
    assert teams["qa"]["combo"] == "frontier"
    assert teams["dev"]["combo"] == "code"
    assert teams["prompt"]["combo"] == "smart" and teams["genai"]["combo"] == "smart"
    for team in ("research", "content", "design", "skills"):
        assert teams[team]["combo"] == "fast", team
    assert CFG["router"]["roles"] == {"lead": "smart", "sub": "fast"}
    assert CFG["router"]["escalationCombo"] == "frontier"


def test_the_new_keys_are_documented_and_blanked_for_tests():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("TOGETHER_API_KEY", "FIREWORKS_API_KEY", "SAMBANOVA_API_KEY", "COHERE_API_KEY", "HF_TOKEN", "LOCAL_OPENAI_URL"):
        assert f"\n{name}=" in example, name
    launcher = (ROOT / "scripts" / "lib" / "backend-launcher.js").read_text(encoding="utf-8")
    assert "baseUrlEnv" in launcher  # demoEnv blanks LOCAL_OPENAI_URL too: a test server must stay in demo


def test_discovery_lists_local_servers_and_free_openrouter_models():
    providers = CFG["providers"]
    assert providers["openrouter"]["discover"] == "free"
    for local in ("ollama", "lmstudio", "localopenai"):
        assert providers[local]["local"] is True  # a local server is listed when it runs
    assert CFG["router"]["discoverMax"] == 6
