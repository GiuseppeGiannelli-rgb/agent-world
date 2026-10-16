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
local model up to 8B is local."""

import re

REASONING_RE = re.compile(r"(?:^|[/\-_.:])(?:r1|qwq|o1|o3|o4|reasoner|reasoning|thinking|gpt-oss)(?:$|[\-_.:/])|deepseek-r1|qwq-", re.IGNORECASE)
CODER_RE = re.compile(r"coder|codestral|devstral|codellama|starcoder|code-", re.IGNORECASE)
VISION_RE = re.compile(r"vision|(?:^|[\-_/])vl(?:$|[\-_.:])|gpt-4o|gpt-5|gemini|claude|llava|pixtral", re.IGNORECASE)
SMALL_RE = re.compile(r"flash|haiku|mini|lite|nano|instant|small|tiny|(?:^|[\-_/])(?:phi)", re.IGNORECASE)
FLAGSHIP_RE = re.compile(r"opus|(?:^|[/\-])gpt-5(?![\-.]?(?:mini|nano))|gemini-[\d.]+-pro|grok-4|claude-opus|mistral-large-3", re.IGNORECASE)
MID_RE = re.compile(r"sonnet|gpt-4o(?!-mini)|gpt-4\.1(?!-mini|-nano)|deepseek-chat|deepseek-v3|command-a|command-r\+|mistral-large|mistral-medium|llama-4", re.IGNORECASE)
PARAMS_RE = re.compile(r"(?<![a-z0-9.])(?:(\d+)x)?(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)

LOCAL_PROVIDERS = {"ollama", "lmstudio", "localopenai"}
FREE_TIER_PROVIDERS = {"groq", "cerebras"}
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
        return p
    p["tier"] = _tier(p)
    p["compact"] = p["tier"] in ("fast", "local") or p["free"] or p["local"] or p["context"] < LARGE_CONTEXT or (p["paramsB"] is not None and p["paramsB"] <= 14)
    return p


def combos_for(p: dict) -> list[str]:
    """The combos a model found at runtime joins: a local one joins "local"
    (and the combo of its tier, when it is bigger than a utility model), a
    free cloud one joins "free", any other the combo of its tier."""
    if p["local"]:
        return ["local"] + ([p["tier"]] if p["tier"] != "local" else [])
    if p["free"]:
        return ["free"]
    return [p["tier"]]
