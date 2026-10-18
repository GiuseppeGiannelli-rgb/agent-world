"""Spec 08 §4.1: how much context a model gets, from its profile (router/profiler.py).

- full (a large model: frontier or smart, >= 128k context, not free, not local):
  up to 5 Brain notes, the whole assigned skills (up to 3, 9000 characters in
  all), the detailed run context (12 delivered files, 6 related events).
- compact (fast, free or local, or a small window): the top-2 passages of the
  assigned skills (RRF of BM25 and cosine, with a minCosine stricter than
  rag.minCosine), 3 Brain and QA notes as short bullets, a short run context,
  and an explicit JSON output contract at the end of the system prompt.

Spec 10 §R4: the shape of the prompt, from the profile of the hired model, in
this order (D6):
- small: local, free (":free", the free tiers) or 14B and less -- atomic steps,
  one example from the skill, the JSON contract and the validator every turn;
- reasoning: r1, qwq, o1/o3/o4, a reasoner, thinking, a *-pro Gemini -- the QA
  checklist, the constraints and the Brain lessons first;
- coder: a coder, DeepSeek, Claude Sonnet, GPT-5, Codestral, Devstral -- the
  snippets of the skills, the exact tree and the interfaces to respect;
- general: the prompt of before. The demo simulator is always here."""

import re

SMALL_MAX_B = 14
REASONING_SHAPE_RE = re.compile(r"gemini-[\d.]+-pro", re.IGNORECASE)
CODER_SHAPE_RE = re.compile(r"deepseek|claude-sonnet|(?:^|[/\-])gpt-5|codestral|devstral", re.IGNORECASE)

FULL = {
    "mode": "full",
    "brainNotes": 5,
    "noteChars": 400,
    "skills": 3,
    "skillBudget": 9000,
    "passages": 0,
    "passageChars": 1200,
    "files": 12,
    "shared": 6,
    "sharedChars": 300,
    "jsonContract": False,
}
COMPACT = {
    "mode": "compact",
    "brainNotes": 3,
    "noteChars": 140,
    "skills": 0,
    "skillBudget": 0,
    "passages": 2,
    "passageChars": 1200,
    "files": 6,
    "shared": 3,
    "sharedChars": 160,
    "jsonContract": True,
}
STRICTER_COSINE = 0.1  # compact mode keeps only the passages this much closer than rag.minCosine


def shape(profile: dict | None) -> str:
    """small, reasoning, coder or general (spec 10 §R4, D6)."""
    if not profile or profile.get("provider") == "mock":
        return "general"
    size = profile.get("sizeB") if profile.get("sizeB") is not None else profile.get("paramsB")
    if profile.get("local") or profile.get("free") or profile.get("costTier") in ("local", "free") or (size is not None and size <= SMALL_MAX_B):
        return "small"
    model = str(profile.get("model") or "")
    if profile.get("reasoning") or REASONING_SHAPE_RE.search(model):
        return "reasoning"
    if profile.get("coder") or CODER_SHAPE_RE.search(model):
        return "coder"
    return "general"


def budget(profile: dict | None, rag: dict | None = None) -> dict:
    rag = rag or {}
    if not profile or not profile.get("compact"):
        out = dict(FULL)
        out["minCosine"] = float(rag.get("minCosine", 0.25))
    else:
        out = dict(COMPACT)
        out["minCosine"] = max(0.35, float(rag.get("minCosine", 0.25)) + STRICTER_COSINE)
    out["passageChars"] = int((rag.get("chunk") or {}).get("maxChars", out["passageChars"]))
    out["shape"] = shape(profile)
    if out["shape"] == "small":
        out["jsonContract"] = True  # a small model reads the contract whatever its window
    return out
