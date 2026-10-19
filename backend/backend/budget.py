"""Spec 11 T01: the budget of a run and its circuit breaker.

A run counts its model calls and estimates what they cost. When it reaches
limits.maxCallsPerRun calls or limits.maxCostUSD dollars it does not fail: it
pauses and asks the owner (a "budget" request, the `waiting` event). Approving
gives one more block of the same size, counted from where the run is;
rejecting stops the run, which can be resumed from where it stopped.

- Only the answers of a real provider count (D1). The simulator's answers (the
  demo, an emergency answer in live mode) cost nothing and never trip it.
- The cost is an estimate (D2): router.pricing gives the USD per million
  tokens [input, output] of a model (its exact key, else the first glob
  pattern that matches it), else of its profiler cost tier. A local or free
  model costs 0.
- The limits are frozen in the run when it is created (data.budget.step), like
  its language: a change in the Settings applies to the next run.
- A limit of 0 or null is off.

No network, no clock: pure functions over the run's usage and budget."""

import fnmatch

from backend.router import profiler

# USD per million tokens [input, output] when router.pricing has no tiers
DEFAULT_TIER_PRICES = {"local": (0.0, 0.0), "free": (0.0, 0.0), "low": (1.0, 5.0), "high": (5.0, 25.0)}


def _limit(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def initial(limits: dict) -> dict:
    """The budget of a new run: the block size (step) and the current limit."""
    calls = _limit((limits or {}).get("maxCallsPerRun"))
    cost = _limit((limits or {}).get("maxCostUSD"))
    step = {"calls": int(calls) if calls else None, "costUSD": cost}
    return {"step": step, "limit": dict(step), "approvals": 0}


def ensure(data: dict, limits: dict) -> dict:
    """A run stored before spec 11 gets its budget and counters (a resume)."""
    usage = data.setdefault("usage", {})
    usage.setdefault("providerCalls", 0)
    usage.setdefault("costUSD", 0.0)
    if not isinstance(data.get("budget"), dict):
        data["budget"] = initial(limits)
    return data["budget"]


def simulated(res: dict) -> bool:
    """The simulator answered (demo, or an emergency in live mode)."""
    return bool(res.get("demo")) or str(res.get("target") or "").startswith("mock/")


def price(key: str, cfg: dict) -> tuple[float, float]:
    """USD per million tokens [input, output] of one model."""
    pricing = (cfg.get("router") or {}).get("pricing") or {}
    models = pricing.get("models") or {}
    hit = models.get(key)
    if hit is None:
        low = key.lower()
        hit = next((p for pattern, p in models.items() if fnmatch.fnmatchcase(low, pattern.lower())), None)
    if hit is None:
        provider = key.partition("/")[0]
        tier = profiler.profile(key, None, (cfg.get("providers") or {}).get(provider))["costTier"]
        hit = (pricing.get("tiers") or {}).get(tier) or DEFAULT_TIER_PRICES.get(tier) or DEFAULT_TIER_PRICES["high"]
    return float(hit[0]), float(hit[1])


def cost(res: dict, cfg: dict) -> float:
    """The estimated USD of one answered call."""
    if simulated(res):
        return 0.0
    u = res.get("usage") or {}
    pin, pout = price(str(res.get("target") or ""), cfg)
    return (u.get("in", 0) * pin + u.get("out", 0) * pout) / 1_000_000


def spend(usage: dict, res: dict, cfg: dict) -> None:
    """One answered call in the run's usage: the call, its tokens and, when a
    real provider answered, the provider call and its estimated cost."""
    u = res.get("usage") or {}
    usage["calls"] = usage.get("calls", 0) + 1
    usage["tokensIn"] = usage.get("tokensIn", 0) + u.get("in", 0)
    usage["tokensOut"] = usage.get("tokensOut", 0) + u.get("out", 0)
    usage.setdefault("providerCalls", 0)
    usage.setdefault("costUSD", 0.0)
    if not simulated(res):
        usage["providerCalls"] = usage.get("providerCalls", 0) + 1
        usage["costUSD"] = round(usage.get("costUSD", 0.0) + cost(res, cfg), 6)


def over(usage: dict, budget: dict | None) -> str | None:
    """Which limit the run has reached: "calls", "cost" or None."""
    limit = (budget or {}).get("limit") or {}
    if limit.get("calls") is not None and usage.get("providerCalls", 0) >= limit["calls"]:
        return "calls"
    if limit.get("costUSD") is not None and usage.get("costUSD", 0.0) >= limit["costUSD"]:
        return "cost"
    return None


def extend(usage: dict, budget: dict) -> dict:
    """The owner said go on: one more block of each limit, from where the run is
    (the calls that were already running when it tripped are not charged twice)."""
    step = budget["step"]
    budget["limit"] = {
        "calls": usage.get("providerCalls", 0) + step["calls"] if step.get("calls") else None,
        "costUSD": round(usage.get("costUSD", 0.0) + step["costUSD"], 6) if step.get("costUSD") else None,
    }
    budget["approvals"] = budget.get("approvals", 0) + 1
    return budget["limit"]
