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
    # spec 09: the coders come right after the frontier models, before smart
    assert chain == ["frontier", "code", "smart", "fast", "free", "local"]
    for name in chain:
        assert name in CFG["combos"]
    for name, combo in CFG["combos"].items():
        if name not in chain:
            # the vision combo never cascades: a model without vision fails on the images
            assert combo.get("joins") in chain or combo.get("cascade") is False, name


@pytest.mark.parametrize("name", ["frontier", "smart", "fast"])
def test_the_main_combos_end_with_free_fallbacks(name):
    models = CFG["combos"][name]["models"]
    tail = [m for m in models[-4:] if _is_free(m)]
    assert len(tail) >= 3, models
    assert any(m.startswith("openrouter/") for m in tail)


def test_the_free_combo_is_free_only():
    # spec 09: NVIDIA NIM (free credits) and Cloudflare Workers AI (a free daily allowance) too
    assert all(_is_free(m) or m.split("/", 1)[0] in ("huggingface", "together", "cohere", "nvidia", "cloudflare") for m in CFG["combos"]["free"]["models"])
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


# ---------- spec 09: more providers, the TypeSafe arbiter, vision ----------


@pytest.mark.parametrize(
    "provider,base,key",
    [
        ("xai", "https://api.x.ai/v1", "XAI_API_KEY"),
        ("perplexity", "https://api.perplexity.ai", "PPLX_API_KEY"),
        ("nvidia", "https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
        ("novita", "https://api.novita.ai/openai", "NOVITA_API_KEY"),
        ("hyperbolic", "https://api.hyperbolic.xyz/v1", "HYPERBOLIC_API_KEY"),
        ("cloudflare", "https://api.cloudflare.com/client/v4/accounts/${CLOUDFLARE_ACCOUNT_ID}/ai/v1", "CLOUDFLARE_API_TOKEN"),
    ],
)
def test_the_spec09_chat_providers(provider, base, key):
    p = CFG["providers"][provider]
    assert p["kind"] == "openai" and p["baseUrl"] == base and p["keyEnv"] == key
    used = {m.split("/", 1)[0] for c in CFG["combos"].values() for m in c["models"]}
    assert provider in used, f"{provider} is in no combo"


def test_perplexity_gets_no_json_mode():
    # Sonar takes a json_schema response_format, not json_object: no wasted 400 per call
    assert CFG["providers"]["perplexity"]["jsonMode"] is False


def test_typesafe_is_the_arbiter_not_a_chat_model():
    """Jev answers typed questions (a choice among options, with probabilities):
    it picks among solutions, it never writes text, so it is in no combo."""
    p = CFG["providers"]["typesafe"]
    assert p == {"kind": "typesafe", "baseUrl": "https://api.typesafe.ai/v1", "baseUrlEnv": "TYPESAFE_BASE_URL", "keyEnv": "TYPESAFE_API_KEY"}
    assert not any(m.startswith("typesafe/") for c in CFG["combos"].values() for m in c["models"])
    arbiter = CFG["router"]["arbiter"]
    assert arbiter["provider"] == "typesafe" and arbiter["model"] == "jev-latest" and 0 < arbiter["minConfidence"] < 1


def _router(monkeypatch, tmp_path, cfg=None):
    from backend.router.index import Router

    class Cfg:
        def get(self):
            return cfg or CFG

    for p in CFG["providers"].values():
        for k in ("keyEnv", "baseUrlEnv"):
            if p.get(k):
                monkeypatch.delenv(p[k], raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    return Router(Cfg(), tmp_path)


def test_a_typesafe_key_alone_keeps_the_demo(monkeypatch, tmp_path):
    router = _router(monkeypatch, tmp_path)
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    assert router.provider_ready("typesafe") is True
    assert router.mode() == "demo"  # no model can write: the simulator still answers


def test_typesafe_base_url_can_be_moved_by_its_variable(monkeypatch):
    from backend.router.providers import base_url

    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    assert base_url(CFG["providers"]["typesafe"]) == "https://api.typesafe.ai/v1"
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://eu.typesafe.example/v1/")
    assert base_url(CFG["providers"]["typesafe"]) == "https://eu.typesafe.example/v1"


def test_cloudflare_needs_its_account_id_and_puts_it_in_the_url(monkeypatch, tmp_path):
    from backend.router.providers import base_url

    router = _router(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-test")
    assert router.provider_ready("cloudflare") is False  # the URL names an account that is not set
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "abc123")
    assert router.provider_ready("cloudflare") is True
    assert base_url(CFG["providers"]["cloudflare"]) == "https://api.cloudflare.com/client/v4/accounts/abc123/ai/v1"


def test_a_placeholder_never_reads_an_unrelated_variable(monkeypatch):
    from backend.router.providers import base_url

    monkeypatch.setenv("SECRET_THING", "leak")
    assert "leak" not in base_url({"baseUrl": "https://x.example/${SECRET_THING}/v1"})  # only *_ACCOUNT_ID / *_URL / *_HOST names


def test_the_vision_combo_holds_vision_models():
    from backend.router import profiler

    models = CFG["combos"]["vision"]["models"]
    assert len(models) >= 4
    assert all(profiler.profile(m)["vision"] for m in models), [m for m in models if not profiler.profile(m)["vision"]]
    assert CFG["combos"]["vision"]["cascade"] is False and "vision" not in CFG["router"]["cascade"]


def test_the_spec09_keys_are_documented():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("XAI_API_KEY", "PPLX_API_KEY", "NVIDIA_API_KEY", "NOVITA_API_KEY", "HYPERBOLIC_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "TYPESAFE_API_KEY", "TYPESAFE_BASE_URL"):
        assert f"\n{name}=" in example, name
