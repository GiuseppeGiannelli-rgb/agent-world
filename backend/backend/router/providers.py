"""Mirrors server/router/providers.js: OpenAI-compatible and Anthropic
adapters over httpx, plus the mock dispatch."""

import os
import re

from backend.plan import nz

THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
DEFAULT_TIMEOUT_S = 180.0


class ProviderError(Exception):
    """kind says why a call failed, so the router knows what to do (spec 08):
    quota (credit gone: the provider sits out for hours), model_not_found (that
    model is blacklisted, its aliases tried), auth, rate_limit and server/network
    (a short cooldown), bad_request and empty (nothing to wait for)."""

    def __init__(self, message: str, *, status: int = 0, retryable: bool = False, auth: bool = False, kind: str | None = None, retry_after_ms: int | None = None):
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.auth = auth
        self.kind = kind or ("auth" if auth else "network" if retryable and not status else "server" if retryable else "bad_request")
        self.retry_after_ms = retry_after_ms


# The body words that mean "no credit left", whatever the status: OpenAI's 429
# insufficient_quota, Anthropic's 400 "credit balance is too low", OpenRouter's
# 402, DeepSeek's "Insufficient Balance".
QUOTA_RE = re.compile(r"insufficient_quota|credit_balance_exhausted|credit balance|out of credits|insufficient (?:credits|balance|funds)|exceeded your current quota|billing|payment required", re.IGNORECASE)
# A quota counted per minute is a rate limit, not a dead credit: Gemini says
# "exceeded your current quota" for its free tier's 15 requests a minute too.
PER_MINUTE_RE = re.compile(r"per ?minute|retrydelay|please retry in|try again in", re.IGNORECASE)
MODEL_GONE_RE = re.compile(r"model_not_found|model[^\n]{0,80}(?:not found|does not exist|not available|no longer available|deprecated|decommissioned|not supported)|unknown model|invalid model", re.IGNORECASE)
RETRY_IN_RE = re.compile(r"(?:retry in|try again in)\s*([\d.]+)\s*(ms|s)\b|\"retryDelay\"\s*:\s*\"([\d.]+)s\"", re.IGNORECASE)


def _retry_after_ms(text: str) -> int | None:
    m = RETRY_IN_RE.search(text)
    if not m:
        return None
    if m.group(3):
        return int(float(m.group(3)) * 1000)
    value = float(m.group(1))
    return int(value if m.group(2).lower() == "ms" else value * 1000)


def _classify(status: int, body) -> ProviderError:
    raw = str(body)
    message = f"HTTP {status}: {raw[:400]}"
    per_minute = bool(PER_MINUTE_RE.search(raw))
    if status == 402 or (status in (400, 403, 429) and QUOTA_RE.search(raw) and not per_minute):
        return ProviderError(message, status=status, kind="quota")
    if status in (404, 410) or (status == 400 and MODEL_GONE_RE.search(raw)):
        return ProviderError(message, status=status, kind="model_not_found")
    if status in (401, 403):
        return ProviderError(message, status=status, auth=True, kind="auth")
    if status in (408, 409, 429):
        return ProviderError(message, status=status, retryable=True, kind="rate_limit", retry_after_ms=_retry_after_ms(raw))
    if status >= 500:
        return ProviderError(message, status=status, retryable=True, kind="server")
    return ProviderError(message, status=status, kind="bad_request")


# Spec 09: a URL may name a part of itself by variable (Cloudflare's account id).
# Only names that are never secrets: a "${OPENAI_API_KEY}" in a URL written
# through /api/config would send the key to whoever owns that URL.
PLACEHOLDER_RE = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")
SAFE_PLACEHOLDER_RE = re.compile(r"^[A-Z][A-Z0-9_]*_(?:ACCOUNT_ID|PROJECT_ID|REGION|HOST)$")


def _fill(url: str) -> str:
    def value(m):
        name = m.group(1)
        v = os.environ.get(name, "").strip() if SAFE_PLACEHOLDER_RE.match(name) else ""
        return v if v and "/" not in v and "?" not in v and "#" not in v else m.group(0)

    return PLACEHOLDER_RE.sub(value, url)


def base_url(provider: dict) -> str:
    """The URL in the environment variable baseUrlEnv when it is set (spec 08: a
    local OpenAI-compatible server at LOCAL_OPENAI_URL; spec 09: TypeSafe moved
    by TYPESAFE_BASE_URL), otherwise baseUrl, with its ${..._ACCOUNT_ID}-style
    placeholders filled in. A placeholder left unfilled stays in the URL: the
    router never calls it (Router.provider_ready)."""
    env = os.environ.get(provider["baseUrlEnv"], "").strip() if provider.get("baseUrlEnv") else ""
    url = env or provider.get("baseUrl") or ""
    return _fill(url.strip()).rstrip("/")


def unfilled(provider: dict) -> bool:
    """True when the provider's URL still names a variable that is not set."""
    return bool(PLACEHOLDER_RE.search(base_url(provider)))


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
        raise ProviderError(f"Network error: {err}", retryable=True, kind="network") from err
    if res.status_code >= 400:
        raise _classify(res.status_code, res.text)
    try:
        return res.json()
    except ValueError as err:
        raise ProviderError(f"Invalid JSON from provider: {res.text[:200]}", retryable=True, kind="server") from err


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

    url = base_url(provider) + "/chat/completions"
    timeout_s = provider.get("timeoutMs", DEFAULT_TIMEOUT_S * 1000) / 1000
    try:
        data = await _post(client, url, headers, body, timeout_s)
    except ProviderError as err:
        # Some OpenAI-compatible servers reject response_format: retry once without it
        # (not when the 400 says the credit is gone or the model does not exist).
        if not (want_json and err.status == 400 and err.kind == "bad_request"):
            raise
        body.pop("response_format", None)
        data = await _post(client, url, headers, body, timeout_s)

    choices = data.get("choices") or [{}]
    text = strip_thinking(parts_to_text((choices[0].get("message") or {}).get("content")))
    if not text:
        raise ProviderError("Empty answer from provider", retryable=True, kind="empty")
    usage = data.get("usage") or {}
    return {"text": text, "model": data.get("model", model), "usage": {"in": usage.get("prompt_tokens", 0), "out": usage.get("completion_tokens", 0)}}


DATA_URL_RE = re.compile(r"^data:(image/[a-z0-9+.\-]+);base64,(.+)$", re.IGNORECASE | re.DOTALL)


def _anthropic_content(content):
    """Spec 09: OpenAI image parts become Anthropic image blocks (inspect_image);
    a message without images stays a plain string, as before."""
    if not (isinstance(content, list) and any(isinstance(p, dict) and p.get("type") == "image_url" for p in content)):
        return parts_to_text(content)
    blocks = []
    for p in content:
        if isinstance(p, str):
            blocks.append({"type": "text", "text": p})
        elif p.get("type") == "text":
            blocks.append({"type": "text", "text": p.get("text", "")})
        elif p.get("type") == "image_url":
            m = DATA_URL_RE.match(str((p.get("image_url") or {}).get("url") or ""))
            if m:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": m.group(1).lower(), "data": m.group(2)}})
    return blocks


def to_anthropic_messages(messages: list[dict]):
    system = []
    out = []
    for m in messages:
        if m["role"] == "system":
            system.append(parts_to_text(m.get("content")))
            continue
        content = _anthropic_content(m.get("content"))
        role = "assistant" if m["role"] == "assistant" else "user"
        if out and out[-1]["role"] == role:
            prev = out[-1]["content"]
            if isinstance(prev, str) and isinstance(content, str):
                out[-1]["content"] = f"{prev}\n\n{content}"
            else:
                as_blocks = lambda c: c if isinstance(c, list) else [{"type": "text", "text": c}]  # noqa: E731
                out[-1]["content"] = as_blocks(prev) + as_blocks(content)
        else:
            out.append({"role": role, "content": content})
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
    data = await _post(client, base_url(provider) + "/messages", {"x-api-key": key, "anthropic-version": "2023-06-01"}, body, timeout_s)
    text = strip_thinking("".join(b.get("text", "") for b in (data.get("content") or []) if b.get("type") == "text"))
    if not text:
        raise ProviderError("Empty answer from provider", retryable=True, kind="empty")
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
