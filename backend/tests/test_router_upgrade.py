"""Spec 08: the router understands why a provider failed and never leaves a run
without an answer.

- Credit gone (402, or 400/403/429 whose body says so): the whole provider sits
  out for router.quotaCooldownMs (6 h), and none of its other models is tried.
  A per-minute limit (Gemini's 429 with a retry delay) is NOT a dead credit.
- Model gone (404, model_not_found): that provider/model is blacklisted and its
  aliases (router.aliases) are tried right away, before the next target.
- Cascade: when every target of a combo fails, the chain of router.cascade
  continues (frontier -> smart -> fast -> free -> local); only then the demo
  simulator answers, flagged as an emergency, if router.emergencyMock allows it.
  One explicit model, the router test button and the /v1 gateway keep their
  errors: they asked for that model, or they serve someone else."""

import json as jsonlib

import httpx
import pytest

QUOTA_OPENAI = {"error": {"message": "You exceeded your current quota, please check your plan and billing details.", "type": "insufficient_quota", "code": "insufficient_quota"}}
CREDIT_ANTHROPIC = {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}}
GEMINI_PER_MINUTE = {
    "error": {
        "code": 429,
        "message": "You exceeded your current quota, please check your plan and billing details. Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 15. Please retry in 7.5s.",
        "status": "RESOURCE_EXHAUSTED",
        "details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}, {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}],
    }
}
GEMINI_404 = {"error": {"code": 404, "message": "models/gemini-2.5-pro is no longer available to new users. Please use a newer model.", "status": "NOT_FOUND"}}


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


class FakeConfig:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


@pytest.fixture
def seen():
    return []


@pytest.fixture
def transport(seen):
    dead = {"gemini-2.5-pro", "gemini-3.1-pro-preview-old"}

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content or b"{}")
        path = request.url.path
        seen.append({"path": path, "model": body.get("model"), "body": body})
        if path.startswith("/quota"):
            return httpx.Response(429, json=QUOTA_OPENAI)
        if path.startswith("/badcredit"):
            return httpx.Response(400, json=QUOTA_OPENAI)
        if path.startswith("/credit"):
            return httpx.Response(402, json={"error": {"message": "credit_balance_exhausted"}})
        if path.startswith("/anthropic-credit"):
            return httpx.Response(400, json=CREDIT_ANTHROPIC)
        if path.startswith("/minute"):
            return httpx.Response(429, json=GEMINI_PER_MINUTE)
        if path.startswith("/rate"):
            return httpx.Response(429, json={"error": {"message": "Rate limit reached for requests"}})
        if path.startswith("/down"):
            return httpx.Response(503, json={"error": "overloaded"})
        if path.startswith("/models404") and body.get("model") in dead:
            return httpx.Response(404, json=GEMINI_404)
        return httpx.Response(200, json={"model": body.get("model"), "choices": [{"message": {"content": f'{{"via": "{path.split("/")[1]}/{body.get("model")}"}}'}}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})

    return httpx.MockTransport(handler)


def make_router(transport, tmp_path, *, combos, extra_router=None, providers=None):
    from backend.router.index import Router

    base = {
        "mock": {"kind": "mock", "latencyMs": [1, 2]},
        "quota": {"kind": "openai", "baseUrl": "http://up/quota", "keyEnv": "T_KEY"},
        "credit": {"kind": "openai", "baseUrl": "http://up/credit", "keyEnv": "T_KEY"},
        "badcredit": {"kind": "openai", "baseUrl": "http://up/badcredit", "keyEnv": "T_KEY"},
        "claudecredit": {"kind": "anthropic", "baseUrl": "http://up/anthropic-credit", "keyEnv": "T_KEY"},
        "minute": {"kind": "openai", "baseUrl": "http://up/minute", "keyEnv": "T_KEY"},
        "rate": {"kind": "openai", "baseUrl": "http://up/rate", "keyEnv": "T_KEY"},
        "down": {"kind": "openai", "baseUrl": "http://up/down", "keyEnv": "T_KEY"},
        "gemini": {"kind": "openai", "baseUrl": "http://up/models404", "keyEnv": "T_KEY"},
        "nokey": {"kind": "openai", "baseUrl": "http://up/ok", "keyEnv": "T_MISSING"},
        "good": {"kind": "openai", "baseUrl": "http://up/good", "keyEnv": "T_KEY"},
        "local": {"kind": "openai", "baseUrl": "http://up/local", "keyless": True},
    }
    value = {
        "router": {"defaultCombo": "fast", "demoFallback": True, "cooldownBaseMs": 60000, "cooldownMaxMs": 60000, "authCooldownMs": 60000, "quotaCooldownMs": 6 * 3600 * 1000, "logCalls": False, "cascade": ["frontier", "smart", "fast", "free", "local"], **(extra_router or {})},
        "providers": {**base, **(providers or {})},
        "combos": {name: {"strategy": "fallback", "models": models} for name, models in combos.items()},
        "teams": {},
    }
    client = httpx.AsyncClient(transport=transport, base_url="http://up")
    return Router(config=FakeConfig(value), data_dir=tmp_path, bus=Bus(), client=client)


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setenv("T_KEY", "secret")
    monkeypatch.delenv("T_MISSING", raising=False)


MESSAGES = [{"role": "system", "content": "[[role:advisor]]"}, {"role": "user", "content": "hi"}]


# ---------- the classifier ----------


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (429, QUOTA_OPENAI, "quota"),
        (402, {"error": "credit_balance_exhausted"}, "quota"),
        (400, CREDIT_ANTHROPIC, "quota"),
        (403, {"error": {"message": "Your account is out of credits"}}, "quota"),
        (429, GEMINI_PER_MINUTE, "rate_limit"),
        (429, {"error": {"message": "Rate limit reached for requests"}}, "rate_limit"),
        (404, GEMINI_404, "model_not_found"),
        (400, {"error": {"code": "model_not_found", "message": "The model `gpt-9` does not exist"}}, "model_not_found"),
        (401, {"error": "bad key"}, "auth"),
        (503, {"error": "overloaded"}, "server"),
        (400, {"error": "response_format not supported"}, "bad_request"),
    ],
)
def test_the_classifier_names_why_a_call_failed(status, body, kind):
    from backend.router.providers import _classify

    err = _classify(status, jsonlib.dumps(body))
    assert err.kind == kind
    assert err.retryable is (kind in ("rate_limit", "server"))
    assert err.auth is (kind == "auth")


def test_a_per_minute_limit_carries_its_retry_delay():
    from backend.router.providers import _classify

    assert _classify(429, jsonlib.dumps(GEMINI_PER_MINUTE)).retry_after_ms == 7500


# ---------- credit gone ----------


@pytest.mark.asyncio
async def test_a_dead_credit_benches_the_whole_provider(transport, tmp_path, seen):
    router = make_router(transport, tmp_path, combos={"frontier": ["quota/gpt-5", "quota/gpt-5-mini", "good/m"]})
    r = await router.chat(use="frontier", messages=MESSAGES)
    assert r["target"] == "good/m"
    assert [s["model"] for s in seen if s["path"].startswith("/quota")] == ["gpt-5"]  # the other quota model is not tried
    snap = {t["key"]: t for c in router.snapshot()["combos"] for t in c["targets"]}
    for key in ("quota/gpt-5", "quota/gpt-5-mini"):
        assert snap[key]["reason"] == "quota_exhausted"
        assert snap[key]["coolingMs"] > 5.9 * 3600 * 1000
    seen.clear()
    await router.chat(use="frontier", messages=MESSAGES)
    assert not any(s["path"].startswith("/quota") for s in seen)  # still benched on the next call


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["credit", "claudecredit"])
async def test_402_and_anthropic_credit_are_dead_credit_too(transport, tmp_path, provider):
    router = make_router(transport, tmp_path, combos={"smart": [f"{provider}/m", "good/m"]})
    assert (await router.chat(use="smart", messages=MESSAGES))["target"] == "good/m"
    assert router.provider_cooldown(provider)["reason"] == "quota_exhausted"


@pytest.mark.asyncio
async def test_a_per_minute_limit_is_only_a_short_pause(transport, tmp_path):
    router = make_router(transport, tmp_path, combos={"fast": ["minute/gemini-2.5-flash", "good/m"]})
    await router.chat(use="fast", messages=MESSAGES)
    assert router.provider_cooldown("minute") is None
    cd = router.cooldowns["minute/gemini-2.5-flash"]
    assert 7000 <= cd["until"] - __import__("time").time() * 1000 <= 7600


@pytest.mark.asyncio
async def test_a_dead_credit_400_is_not_retried_without_json_mode(transport, tmp_path, seen):
    router = make_router(transport, tmp_path, combos={"smart": ["badcredit/m", "good/m"]})
    await router.chat(use="smart", messages=MESSAGES, json=True)
    calls = [s for s in seen if s["path"].startswith("/badcredit")]
    assert len(calls) == 1 and calls[0]["body"]["response_format"] == {"type": "json_object"}
    assert router.provider_cooldown("badcredit")["reason"] == "quota_exhausted"


# ---------- model gone ----------

ALIASES = {"gemini/gemini-2.5-pro": ["gemini/gemini-3.1-pro-preview-old", "gemini/gemini-3.1-pro-preview", "gemini/gemini-2.5-flash"]}


@pytest.mark.asyncio
async def test_a_missing_model_is_blacklisted_and_its_alias_tried_first(transport, tmp_path, seen):
    router = make_router(transport, tmp_path, combos={"frontier": ["gemini/gemini-2.5-pro", "good/m"]}, extra_router={"aliases": ALIASES})
    r = await router.chat(use="frontier", messages=MESSAGES)
    # the dead model, a dead alias, then the first live alias: never good/m
    assert [s["model"] for s in seen] == ["gemini-2.5-pro", "gemini-3.1-pro-preview-old", "gemini-3.1-pro-preview"]
    assert r["target"] == "gemini/gemini-3.1-pro-preview"
    snap = {t["key"]: t for c in router.snapshot()["combos"] for t in c["targets"]}
    assert snap["gemini/gemini-2.5-pro"]["reason"] == "model_not_found"
    seen.clear()
    r2 = await router.chat(use="frontier", messages=MESSAGES)
    assert [s["model"] for s in seen] == ["gemini-3.1-pro-preview"]  # straight to the alias next time
    assert r2["target"] == "gemini/gemini-3.1-pro-preview"


@pytest.mark.asyncio
async def test_a_missing_model_without_aliases_moves_on(transport, tmp_path):
    router = make_router(transport, tmp_path, combos={"frontier": ["gemini/gemini-2.5-pro", "good/m"]})
    assert (await router.chat(use="frontier", messages=MESSAGES))["target"] == "good/m"


# ---------- the cascade ----------


@pytest.mark.asyncio
async def test_a_failing_combo_cascades_down_the_chain(transport, tmp_path, seen):
    router = make_router(
        transport,
        tmp_path,
        combos={"frontier": ["quota/gpt-5"], "smart": ["nokey/m"], "fast": ["rate/m"], "free": ["down/m"], "local": ["local/qwen3:8b"]},
    )
    r = await router.chat(use="frontier", messages=MESSAGES)
    assert r["target"] == "local/qwen3:8b"
    assert r["combo"] == "local" and r["requested"] == "frontier"
    assert r["cascade"] == ["frontier", "smart", "fast", "free", "local"]
    assert r["demo"] is False and r["emergency"] is False
    assert [s["path"].split("/")[1] for s in seen] == ["quota", "rate", "down", "local"]


@pytest.mark.asyncio
async def test_the_cascade_starts_after_the_requested_combo(transport, tmp_path, seen):
    router = make_router(transport, tmp_path, combos={"frontier": ["good/big"], "smart": ["good/mid"], "fast": ["down/m"], "free": ["good/free"]})
    r = await router.chat(use="fast", messages=MESSAGES)
    assert r["target"] == "good/free"  # fast -> free, never up to smart or frontier


@pytest.mark.asyncio
async def test_a_combo_outside_the_chain_joins_it_where_it_says(transport, tmp_path):
    router = make_router(transport, tmp_path, combos={"frontier": ["good/big"], "smart": ["good/mid"], "code": ["down/coder"]})
    router.cfg["combos"]["code"]["joins"] = "smart"
    assert (await router.chat(use="code", messages=MESSAGES))["target"] == "good/mid"


@pytest.mark.asyncio
async def test_when_nothing_answers_the_simulator_steps_in_as_an_emergency(transport, tmp_path):
    router = make_router(transport, tmp_path, combos={"frontier": ["quota/m"], "smart": ["down/m"], "local": ["rate/m"]})
    r = await router.chat(use="frontier", messages=MESSAGES)
    assert r["provider"] == "mock"
    assert r["demo"] is True and r["emergency"] is True
    assert any(t == "router.emergency" for t, _ in router.bus.events)


@pytest.mark.asyncio
async def test_the_emergency_simulator_can_be_turned_off(transport, tmp_path):
    from backend.router.providers import ProviderError

    router = make_router(transport, tmp_path, combos={"frontier": ["quota/m"]}, extra_router={"emergencyMock": False})
    with pytest.raises(ProviderError, match="quota/m"):
        await router.chat(use="frontier", messages=MESSAGES)


@pytest.mark.asyncio
async def test_one_explicit_model_keeps_its_error(transport, tmp_path):
    from backend.router.providers import ProviderError

    router = make_router(transport, tmp_path, combos={"smart": ["good/m"]})
    with pytest.raises(ProviderError, match="down/m"):
        await router.chat(use="down/m", messages=MESSAGES)


@pytest.mark.asyncio
async def test_the_gateway_and_the_test_button_never_get_the_simulator(transport, tmp_path):
    from backend.router.providers import ProviderError

    router = make_router(transport, tmp_path, combos={"fast": ["down/m"], "free": ["good/free"]})
    # the gateway may cascade (a combo was asked), but gets no invented answer
    assert (await router.chat(use="fast", messages=MESSAGES, emergency=False))["target"] == "good/free"
    router2 = make_router(transport, tmp_path, combos={"fast": ["down/m"]})
    with pytest.raises(ProviderError):
        await router2.chat(use="fast", messages=MESSAGES, emergency=False)
    # the test button checks that one combo: no cascade, no simulator
    with pytest.raises(ProviderError):
        await router.chat(use="fast", messages=MESSAGES, cascade=False, emergency=False)


@pytest.mark.asyncio
async def test_demo_mode_is_unchanged_with_no_provider_at_all(transport, tmp_path):
    from backend.router.index import Router

    value = {"router": {"defaultCombo": "fast", "demoFallback": True, "cooldownBaseMs": 1, "cooldownMaxMs": 1, "authCooldownMs": 1, "logCalls": False}, "providers": {"mock": {"kind": "mock", "latencyMs": [1, 2]}, "nokey": {"kind": "openai", "baseUrl": "http://up/ok", "keyEnv": "T_MISSING"}}, "combos": {"fast": {"models": ["nokey/m"]}}, "teams": {}}
    router = Router(config=FakeConfig(value), data_dir=tmp_path, bus=Bus(), client=httpx.AsyncClient(transport=transport))
    r = await router.chat(use="fast", messages=MESSAGES)
    assert r["provider"] == "mock" and r["demo"] is True and r["emergency"] is False


@pytest.mark.asyncio
async def test_the_routes_ask_what_they_need(tmp_path, monkeypatch):
    """The test button checks one combo as it is (no cascade, no simulator);
    the /v1 gateway may cascade but never hands an invented answer to a client."""
    from backend.app import ROOT, create_app
    from backend.config import Config
    from backend.router.index import Router
    from backend.store import Store

    monkeypatch.setenv("AGENT_WORLD_HOME", str(tmp_path))
    config = Config(ROOT / "config")
    router = Router(config, tmp_path, None)
    calls = []
    real = router.chat

    async def spy(**kw):
        calls.append(kw)
        return await real(**kw)

    router.chat = spy
    app = create_app(config=config, store=Store(tmp_path), router=router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as c:
        await c.post("/api/router/test", json={"use": "fast"})
        assert calls[-1].get("cascade") is False and calls[-1].get("emergency") is False
        await c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        assert calls[-1].get("emergency") is False and calls[-1].get("cascade") is not False


# ---------- spec 09: images reach a vision model ----------


def test_images_reach_anthropic_as_image_blocks():
    from backend.router.providers import to_anthropic_messages

    png = "iVBORw0KGgo="
    system, out = to_anthropic_messages(
        [
            {"role": "system", "content": "[[role:vision]] describe"},
            {"role": "user", "content": [{"type": "text", "text": "What is in this photo?"}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}}]},
        ]
    )
    assert system == "[[role:vision]] describe"
    assert out == [{"role": "user", "content": [{"type": "text", "text": "What is in this photo?"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}}]}]


def test_text_only_messages_stay_plain_strings_for_anthropic():
    from backend.router.providers import to_anthropic_messages

    _, out = to_anthropic_messages([{"role": "user", "content": "a"}, {"role": "user", "content": "b"}])
    assert out == [{"role": "user", "content": "a\n\nb"}]


@pytest.mark.asyncio
async def test_a_vision_combo_that_fails_does_not_cascade(transport, tmp_path, seen):
    """A model without vision would fail on the image: the vision combo keeps its own error."""
    from backend.router.providers import ProviderError

    router = make_router(transport, tmp_path, combos={"vision": ["down/gpt-5-mini"], "frontier": ["good/big"], "smart": ["good/mid"], "fast": ["good/small"]})
    router.config.value["combos"]["vision"]["cascade"] = False
    with pytest.raises(ProviderError):
        await router.chat(use="vision", messages=MESSAGES, emergency=False)
    assert [s["path"].split("/")[1] for s in seen] == ["down"]
