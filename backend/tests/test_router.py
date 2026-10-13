"""Mirrors scenarios 1-6 of scripts/router-test.js against a fake upstream
(httpx.MockTransport instead of a real http.Server: no sockets, no keys)."""

import json as jsonlib
import os

import httpx
import pytest


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


@pytest.fixture
def seen():
    return []


@pytest.fixture
def transport(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content or b"{}")
        seen.append({"url": request.url.path, "headers": dict(request.headers), "body": body})
        path = request.url.path
        if path.startswith("/busy"):
            return httpx.Response(429, json={"error": "rate limited"})
        if path.startswith("/denied"):
            return httpx.Response(401, json={"error": "bad key"})
        if path.startswith("/strict") and body.get("response_format"):
            return httpx.Response(400, json={"error": "response_format not supported"})
        if path.endswith("/messages"):
            return httpx.Response(
                200,
                json={
                    "model": body.get("model"),
                    "content": [{"type": "text", "text": '{"ok": true, "via": "anthropic"}'}],
                    "usage": {"input_tokens": 11, "output_tokens": 7},
                },
            )
        return httpx.Response(
            200,
            json={
                "model": body.get("model"),
                "choices": [{"message": {"content": '<think>scratch</think>```json\n{"ok": true, "via": "openai"}\n```'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
            },
        )

    return httpx.MockTransport(handler)


class FakeConfig:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


@pytest.fixture
def router(transport, monkeypatch, tmp_path):
    from backend.router.index import Router

    monkeypatch.setenv("T_KEY", "secret")
    monkeypatch.delenv("T_MISSING", raising=False)
    value = {
        "router": {"defaultCombo": "main", "demoFallback": True, "cooldownBaseMs": 60000, "cooldownMaxMs": 60000, "authCooldownMs": 60000, "logCalls": False},
        "providers": {
            "mock": {"kind": "mock", "latencyMs": [1, 2]},
            "busy": {"kind": "openai", "baseUrl": "http://up/busy", "keyEnv": "T_KEY"},
            "denied": {"kind": "openai", "baseUrl": "http://up/denied", "keyEnv": "T_KEY"},
            "nokey": {"kind": "openai", "baseUrl": "http://up/ok", "keyEnv": "T_MISSING"},
            "strict": {"kind": "openai", "baseUrl": "http://up/strict", "keyEnv": "T_KEY"},
            "good": {"kind": "openai", "baseUrl": "http://up/ok", "keyEnv": "T_KEY"},
            "claude": {"kind": "anthropic", "baseUrl": "http://up/anthropic", "keyEnv": "T_KEY"},
        },
        "combos": {
            "main": {"strategy": "fallback", "models": ["nokey/m", "busy/m", "denied/m", "good/m1"]},
            "strict": {"strategy": "fallback", "models": ["strict/m"]},
            "claude": {"strategy": "fallback", "models": ["claude/claude-sonnet-5-5"]},
            "empty": {"strategy": "fallback", "models": ["nokey/m"]},
            "rr": {"strategy": "round-robin", "models": ["good/a", "good/b"]},
        },
        "teams": {},
    }
    client = httpx.AsyncClient(transport=transport, base_url="http://up")
    return Router(config=FakeConfig(value), data_dir=tmp_path, bus=Bus(), client=client)


MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}, {"role": "user", "content": "again"}]


@pytest.mark.asyncio
async def test_fallback_skips_missing_keys_429_and_401(router, seen):
    r1 = await router.chat(role="builder", messages=MESSAGES, json=True)
    assert r1["target"] == "good/m1"
    assert r1["usage"]["in"] == 5
    assert not any(s["url"].startswith("/ok") and s["body"].get("model") == "m" for s in seen)
    ok_call = next(s for s in seen if s["url"] == "/ok/chat/completions")
    assert ok_call["headers"]["authorization"] == "Bearer secret"
    assert ok_call["body"]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_cooling_targets_tried_last(router, seen):
    await router.chat(role="builder", messages=MESSAGES, json=True)
    seen.clear()
    await router.chat(role="builder", messages=MESSAGES)
    assert seen[0]["url"] == "/ok/chat/completions"


@pytest.mark.asyncio
async def test_json_mode_falls_back_when_unsupported(router, seen):
    r3 = await router.chat(use="strict", messages=MESSAGES, json=True)
    assert len(seen) == 2
    assert "response_format" not in seen[1]["body"]
    assert '"ok"' in r3["text"]


@pytest.mark.asyncio
async def test_anthropic_adapter(router, seen):
    r4 = await router.chat(use="claude", messages=MESSAGES)
    a = seen[0]
    assert a["url"] == "/anthropic/messages"
    assert a["headers"]["x-api-key"] == "secret"
    assert a["headers"]["anthropic-version"] == "2023-06-01"
    assert a["body"]["system"] == "sys"
    assert a["body"]["messages"] == [{"role": "user", "content": "hi\n\nagain"}]
    assert r4["usage"]["out"] == 7


@pytest.mark.asyncio
async def test_demo_fallback_when_nothing_configured(router):
    r5 = await router.chat(use="empty", messages=[{"role": "system", "content": "[[role:advisor]]"}, {"role": "user", "content": "q"}])
    assert r5["provider"] == "mock"
    assert r5["demo"] is True


@pytest.mark.asyncio
async def test_round_robin_rotates(router):
    t1 = (await router.chat(use="rr", messages=MESSAGES))["target"]
    t2 = (await router.chat(use="rr", messages=MESSAGES))["target"]
    assert t1 != t2
