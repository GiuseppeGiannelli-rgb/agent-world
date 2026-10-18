"""Spec 08: what a model is, read from its name and, when /models gives it, its
metadata. No network here: discovery (Router.discover) asks the providers and
hands the answers to profile().

A profile says:
- paramsB: billions of parameters, from the name ("70b", "qwen3:8b", "8x7b" = 56);
- reasoning (r1, qwq, o1/o3/o4, reasoner, thinking, gpt-oss), coder (coder,
  codestral, devstral), vision (vision, vl, gpt-4o, gemini, claude), small
  (flash, haiku, mini, lite, nano, instant, small), flagship (opus, gpt-5,
  a *-pro Gemini, grok-4);
- context: the context window, from the metadata or the family;
- free (":free", OpenRouter's free router, the free tiers of Gemini Flash,
  Groq, Cerebras), local (Ollama, LM Studio, a local server), json (the
  provider takes response_format);
- tier: frontier, smart, code, fast or local, the combo the model fits;
- compact: whether the RAG context has to be small (spec 08, §4.1).

The tier follows the spec: reasoning, flagship and >= 70B models are frontier;
coders are code; 24-69B and the mid-size names (sonnet, gpt-4o, deepseek-chat,
command, mistral-large) are smart; small names and 7-23B models are fast; a
local model up to 8B is local.

Spec 10 adds the competence matrix the hiring matcher (router/hiring.py) reads:
- sizeB: paramsB when the name says it, else the class of the family (a closed
  flagship or reasoning model counts as 400B, a mid-size name as 120B, a coder
  as 32B, a small name as 24B, otherwise the size of its tier); sizeSource
  says which ("name" or "family");
- specialties, each from 0 to 1: a base from the size (0.2 + 0.1 * log2 of
  the billions), moved by the families (a coder codes, a reasoning model
  reasons, Perplexity searches, a model without vision sees nothing) and by
  the provider (Groq, Cerebras and SambaNova are fast);
- costTier: local, free (the free tiers above), high (a flagship, or a
  reasoning model of a premium provider), low (any other paid model).
None of it needs the network; the health of a model comes from the router."""

import math

import re

REASONING_RE = re.compile(r"(?:^|[/\-_.:])(?:r1|qwq|o1|o3|o4|reasoner|reasoning|thinking|gpt-oss)(?:$|[\-_.:/])|deepseek-r1|qwq-", re.IGNORECASE)
CODER_RE = re.compile(r"coder|codestral|devstral|codellama|starcoder|code-", re.IGNORECASE)
VISION_RE = re.compile(r"vision|(?:^|[\-_/])vl(?:$|[\-_.:])|gpt-4o|gpt-5|gemini|claude|llava|pixtral", re.IGNORECASE)
SMALL_RE = re.compile(r"flash|haiku|mini|lite|nano|instant|small|tiny|(?:^|[\-_/])(?:phi)", re.IGNORECASE)
FLAGSHIP_RE = re.compile(r"opus|(?:^|[/\-])gpt-5(?![\-.]?(?:mini|nano))|gemini-[\d.]+-pro|grok-4|claude-opus|mistral-large-3", re.IGNORECASE)
MID_RE = re.compile(r"sonnet|gpt-4o(?!-mini)|gpt-4\.1(?!-mini|-nano)|deepseek-chat|deepseek-v3|command-a|command-r\+|mistral-large|mistral-medium|llama-4", re.IGNORECASE)
PARAMS_RE = re.compile(r"(?<![a-z0-9.])(?:(\d+)x)?(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)
# spec 10: the families known for one strength, on top of their size
CODING_STRONG_RE = re.compile(r"claude-(?:sonnet|opus)|gpt-5|gpt-4\.1|deepseek|qwen[\w.\-]*coder|codestral|devstral|kimi|glm", re.IGNORECASE)
TOOL_STRONG_RE = re.compile(r"claude|gpt-4o|gpt-4\.1|gpt-5|gemini|qwen|deepseek-(?:chat|v3)|mistral-large|llama-3\.3|llama-4|command-a|gpt-oss", re.IGNORECASE)
CREATIVE_STRONG_RE = re.compile(r"claude|gpt-4o|gpt-5|gemini|mistral-large|llama-3\.3|llama-4|command-a", re.IGNORECASE)
RESEARCH_RE = re.compile(r"sonar|perplexity", re.IGNORECASE)
# the models /models lists that do not write text: never hired for a worker
NON_CHAT_RE = re.compile(r"embed|whisper|tts|dall-e|gpt-image|flux|stable-diffusion|sdxl|rerank|moderation|guard", re.IGNORECASE)
PREMIUM_PROVIDERS = {"openai", "anthropic", "gemini", "xai"}
SPECIALTIES = ("reasoning", "coding", "creative", "research", "vision", "toolUse", "speed")
TIER_SIZE = {"frontier": 400, "smart": 120, "code": 32, "fast": 24, "local": 8}

LOCAL_PROVIDERS = {"ollama", "lmstudio", "localopenai"}
FREE_TIER_PROVIDERS = {"groq", "cerebras", "nvidia", "cloudflare"}  # spec 09: NIM credits, the Workers AI daily allowance
FAST_PROVIDERS = {"groq", "cerebras", "sambanova"}

# context windows by family, when /models says nothing (first match wins)
CONTEXT = [
    (re.compile(r"gemini", re.I), 1_048_576),
    (re.compile(r"gpt-5|gpt-4\.1", re.I), 400_000),
    (re.compile(r"claude", re.I), 200_000),
    (re.compile(r"o1|o3|o4", re.I), 200_000),
    (re.compile(r"gpt-4o|llama-3\.[13]|llama-4|mistral|codestral|command-a|gpt-oss|deepseek|qwen-?3", re.I), 128_000),
    (re.compile(r"qwen", re.I), 32_768),
]
DEFAULT_CONTEXT = 32_768
LOCAL_CONTEXT = 8_192  # Ollama and LM Studio load models with a small window unless told otherwise
LARGE_CONTEXT = 128_000


def _params(model: str) -> float | None:
    best = None
    for m in PARAMS_RE.finditer(model):
        experts, size = m.group(1), float(m.group(2))
        value = size * int(experts) if experts else size
        best = value if best is None else max(best, value)
    if best is None:
        return None
    return int(best) if best == int(best) else best


def _context(provider_id: str, model: str, meta: dict) -> int:
    for key in ("context_length", "contextLength", "context_window", "max_context_length"):
        if isinstance(meta.get(key), int) and meta[key] > 0:
            return meta[key]
    if provider_id in LOCAL_PROVIDERS:
        return LOCAL_CONTEXT
    for pattern, size in CONTEXT:
        if pattern.search(model):
            return size
    return DEFAULT_CONTEXT


def _tier(p: dict) -> str:
    params = p["paramsB"]
    if p["local"] and (params is None or params <= 8) and not p["reasoning"]:
        return "local"
    if p["reasoning"] or p["flagship"]:
        return "frontier"
    if p["coder"]:
        return "code"
    if p["small"]:
        return "fast"
    if params is not None:
        if params >= 70:
            return "frontier"
        if params >= 24:
            return "smart"
        return "fast"
    if MID_RE.search(p["model"]):
        return "smart"
    if p["free"] or p["provider"] in FAST_PROVIDERS:
        return "fast"
    return "smart"


def profile(target: str, meta: dict | None = None, provider: dict | None = None) -> dict:
    """The profile of "provider/model" (meta: one entry of /models, if any;
    provider: its config entry, for JSON mode and the local flag)."""
    meta = meta or {}
    provider = provider or {}
    provider_id, _, model = str(target).partition("/")
    name = model.lower()
    p = {
        "key": target,
        "provider": provider_id,
        "model": model,
        "paramsB": _params(name),
        "reasoning": bool(REASONING_RE.search(name)),
        "coder": bool(CODER_RE.search(name)),
        "vision": bool(VISION_RE.search(name)),
        "small": bool(SMALL_RE.search(name)),
        "flagship": bool(FLAGSHIP_RE.search(name)),
        "local": provider_id in LOCAL_PROVIDERS or bool(provider.get("local")),
        "free": name.endswith(":free") or name == "openrouter/free" or provider_id in FREE_TIER_PROVIDERS or (provider_id == "gemini" and "flash" in name),
        "json": provider.get("jsonMode") is not False and provider.get("kind", "openai") != "mock",
    }
    p["context"] = _context(provider_id, name, meta)
    if provider_id == "mock":
        # the demo simulator has no window and no tier: it keeps the full context,
        # so demo prompts stay what they were
        p.update(context=1_000_000, tier="smart", compact=False)
        # spec 10: never hired (it is not in the catalog); a matrix of zeros for the readers
        p.update(sizeB=None, sizeSource=None, specialties=dict.fromkeys(SPECIALTIES, 0.0), costTier="free")
        return p
    p["tier"] = _tier(p)
    p["compact"] = p["tier"] in ("fast", "local") or p["free"] or p["local"] or p["context"] < LARGE_CONTEXT or (p["paramsB"] is not None and p["paramsB"] <= 14)
    p["sizeB"], p["sizeSource"] = size_of(p)
    p["specialties"] = specialties(p)
    p["costTier"] = cost_tier(p)
    return p


# ---------- spec 10: the competence matrix ----------


def size_of(p: dict) -> tuple[float, str]:
    """(billions, "name" | "family"): the size the matcher compares."""
    if p["paramsB"] is not None:
        return p["paramsB"], "name"
    if p["flagship"] or (p["reasoning"] and not p["local"]):
        return 400, "family"
    if MID_RE.search(p["model"]):
        return 120, "family"
    if p["small"]:
        return 24, "family"
    if p["coder"]:
        return 32, "family"
    return TIER_SIZE.get(p.get("tier"), 24), "family"


def _clamp(v: float) -> float:
    return float(round(min(1.0, max(0.0, v)), 2))


def specialties(p: dict) -> dict:
    model, size = p["model"], max(float(p["sizeB"]), 1.0)
    cap = min(0.95, max(0.2, 0.2 + 0.1 * math.log2(size)))
    return {
        "reasoning": _clamp(cap + (0.15 if p["reasoning"] else 0) + (0.05 if p["flagship"] else 0) - (0.05 if p["small"] else 0)),
        "coding": _clamp(cap + (0.2 if p["coder"] else 0) + (0.1 if CODING_STRONG_RE.search(model) else 0)),
        "creative": _clamp(cap + (0.1 if CREATIVE_STRONG_RE.search(model) else 0) - (0.15 if p["coder"] else 0) - (0.05 if p["reasoning"] else 0)),
        "research": _clamp(cap + (0.1 if p["context"] >= LARGE_CONTEXT else 0) + (0.2 if RESEARCH_RE.search(f"{p['provider']}/{model}") else 0) - (0.1 if p["context"] < 16_000 else 0)),
        "vision": _clamp(cap) if p["vision"] else 0.0,
        "toolUse": _clamp(cap + (0.1 if TOOL_STRONG_RE.search(model) else 0) - (0.2 if not p["json"] else 0)),
        "speed": _clamp(1.05 - 0.12 * math.log2(size) + (0.25 if p["provider"] in FAST_PROVIDERS else 0) + (0.1 if p["small"] else 0) - (0.2 if p["reasoning"] else 0)),
    }


def cost_tier(p: dict) -> str:
    if p["local"]:
        return "local"
    if p["free"]:
        return "free"
    if p["flagship"] or (p["reasoning"] and p["provider"] in PREMIUM_PROVIDERS):
        return "high"
    return "low"


def combos_for(p: dict) -> list[str]:
    """The combos a model found at runtime joins: a local one joins "local"
    (and the combo of its tier, when it is bigger than a utility model), a
    free cloud one joins "free", any other the combo of its tier."""
    if p["local"]:
        return ["local"] + ([p["tier"]] if p["tier"] != "local" else [])
    if p["free"]:
        return ["free"]
    return [p["tier"]]
