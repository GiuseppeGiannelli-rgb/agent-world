"""Mirrors server/router/providers.js: OpenAI-compatible and Anthropic
adapters over httpx, plus the mock dispatch."""

import os
import re

from backend.plan import nz

THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
DEFAULT_TIMEOUT_S = 180.0


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int = 0, retryable: bool = False, auth: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.auth = auth


def _classify(status: int, body) -> ProviderError:
    text = str(body)[:400]
    return ProviderError(
        f"HTTP {status}: {text}",
        status=status,
        retryable=status in (408, 409, 429) or status >= 500,
        auth=status in (401, 403),
    )


def strip_thinking(text) -> str:
    return THINK_RE.sub("", text or "").strip()


def parts_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p if isinstance(p, str) else (p or {}).get("text", "") for p in content)
    return ""


async def _post(client, url, headers, body, timeout_s):
    try:
        res = await client.post(url, headers=headers, json=body, timeout=timeout_s)
    except Exception as err:  # noqa: BLE001 -- any transport failure is a retryable network error
        raise ProviderError(f"Network error: {err}", retryable=True) from err
    if res.status_code >= 400:
        raise _classify(res.status_code, res.text)
    try:
        return res.json()
    except ValueError as err:
        raise ProviderError(f"Invalid JSON from provider: {res.text[:200]}", retryable=True) from err


async def openai_chat(provider: dict, provider_id: str, model: str, req: dict, client) -> dict:
    key = os.environ.get(provider["keyEnv"]) if provider.get("keyEnv") else None
    headers = {"authorization": f"Bearer {key}"} if key else {}
    if provider_id == "openrouter":
        headers["http-referer"] = "http://localhost/agent-world"
        headers["x-title"] = "Agent World"
    body = {"model": model, "messages": req["messages"], "max_tokens": nz(req.get("maxTokens"), 4096)}
    if req.get("temperature") is not None:
        body["temperature"] = req["temperature"]
    want_json = req.get("json") and provider.get("jsonMode") is not False
    if want_json:
        body["response_format"] = {"type": "json_object"}

    url = provider["baseUrl"].rstrip("/") + "/chat/completions"
    timeout_s = provider.get("timeoutMs", DEFAULT_TIMEOUT_S * 1000) / 1000
    try:
        data = await _post(client, url, headers, body, timeout_s)
    except ProviderError as err:
        # Some OpenAI-compatible servers reject response_format: retry once without it.
        if not (want_json and err.status == 400):
            raise
        body.pop("response_format", None)
        data = await _post(client, url, headers, body, timeout_s)

    choices = data.get("choices") or [{}]
    text = strip_thinking(parts_to_text((choices[0].get("message") or {}).get("content")))
    if not text:
        raise ProviderError("Empty answer from provider", retryable=True)
    usage = data.get("usage") or {}
    return {"text": text, "model": data.get("model", model), "usage": {"in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)}}


def to_anthropic_messages(messages: list[dict]):
    system = []
    out = []
    for m in messages:
        text = parts_to_text(m.get("content"))
        if m["role"] == "system":
            system.append(text)
            continue
        role = "assistant" if m["role"] == "assistant" else "user"
        if out and out[-1]["role"] == role:
            out[-1]["content"] += f"\n\n{text}"
        else:
            out.append({"role": role, "content": text})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": "(start)"})
    return "\n\n".join(system), out


async def anthropic_chat(provider: dict, model: str, req: dict, client) -> dict:
    key = os.environ.get(provider["keyEnv"])
    system, messages = to_anthropic_messages(req["messages"])
    body = {"model": model, "max_tokens": nz(req.get("maxTokens"), 4096), "messages": messages}
    if system:
        body["system"] = system
    if req.get("temperature") is not None:
        body["temperature"] = req["temperature"]
    timeout_s = provider.get("timeoutMs", DEFAULT_TIMEOUT_S * 1000) / 1000
    data = await _post(client, provider["baseUrl"].rstrip("/") + "/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, body, timeout_s)
    text = strip_thinking("".join(b.get("text", "") for b in (data.get("content") or []) if b.get("type") == "text"))
    if not text:
        raise ProviderError("Empty answer from provider", retryable=True)
    usage = data.get("usage") or {}
    return {"text": text, "model": data.get("model", model), "usage": {"in": usage.get("input_tokens", 0), "out": usage.get("output_tokens", 0)}}


async def call_provider(provider: dict, provider_id: str, model: str, req: dict, client) -> dict:
    kind = provider["kind"]
    if kind == "mock":
        from backend.router.mock import mock_chat

        return await mock_chat(provider, model, req)
    if kind == "anthropic":
        return await anthropic_chat(provider, model, req, client)
    if kind == "openai":
        return await openai_chat(provider, provider_id, model, req, client)
    raise ProviderError(f'Unknown provider kind "{kind}"')
