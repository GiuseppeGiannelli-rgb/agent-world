"""Spec 08 §4.1: how much context a model gets, from its profile (router/profiler.py).

- full (a large model: frontier or smart, >= 128k context, not free, not local):
  up to 5 Brain notes, the whole assigned skills (up to 3, 9000 characters in
  all), the detailed run context (12 delivered files, 6 related events).
- compact (fast, free or local, or a small window): the top-2 passages of the
  assigned skills (RRF of BM25 and cosine, with a minCosine stricter than
  rag.minCosine), 3 Brain and QA notes as short bullets, a short run context,
  and an explicit JSON output contract at the end of the system prompt."""

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


def budget(profile: dict | None, rag: dict | None = None) -> dict:
    rag = rag or {}
    if not profile or not profile.get("compact"):
        out = dict(FULL)
        out["minCosine"] = float(rag.get("minCosine", 0.25))
    else:
        out = dict(COMPACT)
        out["minCosine"] = max(0.35, float(rag.get("minCosine", 0.25)) + STRICTER_COSINE)
    out["passageChars"] = int((rag.get("chunk") or {}).get("maxChars", out["passageChars"]))
    return out
