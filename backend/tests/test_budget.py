"""Spec 11 T01: the budget of a run and its circuit breaker.

- limits.maxCallsPerRun (250) and limits.maxCostUSD (5) are frozen in the run
  when it is created (run.budget); 0 or null is off.
- Only the answers of a real provider count (D1): the simulator's never trip.
- The cost is an estimate from router.pricing (D2): exact key, glob, tier.
- At a limit the run does not fail: it pauses, emits `waiting` with a "budget"
  request and every call of its work waits. Approving (the button, a text
  answer or the Resume button) adds one more block; rejecting stops the run,
  which a resume from the block point takes up again (D3).
- Each call holds its slot while it runs: parallel workers never pass the
  call limit together (D4). A call the owner asked for is counted, never held.

Three levels: the pure functions of backend/budget.py, a Run on a fake paid
provider, and demo missions whose answers are relabelled as a paid model's."""

import asyncio
import json
import types
from pathlib import Path

import pytest

from backend import budget
from test_attachments import app, client, ctx  # noqa: F401 -- fixtures too

REPO = Path(__file__).resolve().parents[2]


async def until(pred, timeout=60.0, step=0.01):
    for _ in range(int(timeout / step)):
        v = pred()
        if v:
            return v
        await asyncio.sleep(step)
    raise AssertionError("timed out")


# ---------- the pure functions ----------


def test_the_shipped_limits_and_prices():
    cfg = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    assert cfg["limits"]["maxCallsPerRun"] == 250
    assert cfg["limits"]["maxCostUSD"] == 5
    assert budget.initial(cfg["limits"]) == {"step": {"calls": 250, "costUSD": 5.0}, "limit": {"calls": 250, "costUSD": 5.0}, "approvals": 0}
    pricing = cfg["router"]["pricing"]
    assert pricing["tiers"]["local"] == [0, 0] and pricing["tiers"]["free"] == [0, 0]
    # every pattern is a pair of non-negative USD per million tokens
    assert all(len(p) == 2 and min(p) >= 0 for p in [*pricing["tiers"].values(), *pricing["models"].values()])


@pytest.mark.parametrize("limits, step", [
    ({}, {"calls": None, "costUSD": None}),
    ({"maxCallsPerRun": 0, "maxCostUSD": 0}, {"calls": None, "costUSD": None}),
    ({"maxCallsPerRun": None, "maxCostUSD": "x"}, {"calls": None, "costUSD": None}),
    ({"maxCallsPerRun": -3, "maxCostUSD": -1}, {"calls": None, "costUSD": None}),
    ({"maxCallsPerRun": 40.0, "maxCostUSD": 0.5}, {"calls": 40, "costUSD": 0.5}),
])
def test_a_limit_of_zero_or_nothing_is_off(limits, step):
    b = budget.initial(limits)
    assert b["step"] == step and b["limit"] == step and b["approvals"] == 0
    assert budget.over({"providerCalls": 10**6, "costUSD": 10.0**6}, b) is (None if step["calls"] is None else "calls")


PRICING = {"router": {"pricing": {
    "tiers": {"local": [0, 0], "free": [0, 0], "low": [1, 5], "high": [5, 25]},
    "models": {"openai/gpt-5": [1.25, 10], "openai/gpt-5-mini*": [0.25, 2], "openai/gpt-5*": [9, 9], "anthropic/claude-sonnet-*": [3, 15]},
}}, "providers": {"ollama": {"local": True}}}


@pytest.mark.parametrize("key, price", [
    ("openai/gpt-5", (1.25, 10.0)),  # the exact key wins over the glob listed after it
    ("openai/gpt-5-mini", (0.25, 2.0)),  # the first matching pattern wins
    ("openai/gpt-5.1", (9.0, 9.0)),
    ("Anthropic/Claude-Sonnet-5-5", (3.0, 15.0)),  # patterns ignore the case
    ("anthropic/claude-opus-5-5", (5.0, 25.0)),  # no pattern: the profiler says flagship, "high"
    ("mistral/mistral-small-latest", (1.0, 5.0)),  # a paid model of no pattern: "low"
    ("openrouter/deepseek/deepseek-r1:free", (0.0, 0.0)),
    ("groq/openai/gpt-oss-120b", (0.0, 0.0)),  # a free tier
    ("ollama/qwen3:8b", (0.0, 0.0)),  # local
])
def test_the_price_of_a_model_exact_glob_then_tier(key, price):
    assert budget.price(key, PRICING) == price


def test_without_tiers_in_the_config_the_default_tier_prices_apply():
    assert budget.price("anthropic/claude-opus-5-5", {}) == budget.DEFAULT_TIER_PRICES["high"]
    assert budget.price("openrouter/x:free", {}) == (0.0, 0.0)


def test_the_simulator_counts_as_a_call_but_never_as_a_provider_call_or_a_cost():
    usage = {"calls": 0, "tokensIn": 0, "tokensOut": 0}
    for res in ({"target": "mock/mock-dev", "usage": {"in": 900, "out": 90}}, {"target": "openai/gpt-5", "demo": True, "usage": {"in": 900, "out": 90}}):
        assert budget.simulated(res) and budget.cost(res, PRICING) == 0.0
        budget.spend(usage, res, PRICING)
    assert usage == {"calls": 2, "tokensIn": 1800, "tokensOut": 180, "providerCalls": 0, "costUSD": 0.0}
    paid = {"target": "openai/gpt-5", "demo": False, "usage": {"in": 1_000_000, "out": 1_000_000}}
    assert budget.cost(paid, PRICING) == pytest.approx(11.25)
    budget.spend(usage, paid, PRICING)
    assert usage["calls"] == 3 and usage["providerCalls"] == 1 and usage["costUSD"] == pytest.approx(11.25)


def test_over_says_which_limit_and_extend_counts_from_where_the_run_is():
    b = budget.initial({"maxCallsPerRun": 10, "maxCostUSD": 2})
    assert budget.over({"providerCalls": 9, "costUSD": 1.99}, b) is None
    assert budget.over({"providerCalls": 10, "costUSD": 0}, b) == "calls"
    assert budget.over({"providerCalls": 3, "costUSD": 2.0}, b) == "cost"
    # 12 calls already sent when the owner said yes: they are not charged to the new block
    assert budget.extend({"providerCalls": 12, "costUSD": 2.5}, b) == {"calls": 22, "costUSD": 4.5}
    assert b["approvals"] == 1 and b["step"] == {"calls": 10, "costUSD": 2.0}
    only_cost = budget.initial({"maxCostUSD": 1})
    assert budget.extend({"providerCalls": 99, "costUSD": 1.2}, only_cost) == {"calls": None, "costUSD": 2.2}


def test_a_run_stored_before_spec_11_gets_its_budget():
    data = {"usage": {"calls": 7, "tokensIn": 1, "tokensOut": 1}}
    b = budget.ensure(data, {"maxCallsPerRun": 5})
    assert data["usage"]["providerCalls"] == 0 and data["usage"]["costUSD"] == 0.0
    assert b == data["budget"] and b["limit"] == {"calls": 5, "costUSD": None}
    assert budget.ensure(data, {"maxCallsPerRun": 99}) is b  # a run that has one keeps it


# ---------- a run on a paid provider ----------


class PaidRouter:
    """Every answer comes from a paid model, after `latency` seconds."""

    def __init__(self, target="openai/gpt-5", tokens=(1000, 200), latency=0.0, demo=False):
        self.target, self.tokens, self.latency, self.demo = target, tokens, latency, demo
        self.calls = 0

    def mode(self):
        return "live"

    async def chat(self, **kwargs):
        self.calls += 1
        if self.latency:
            await asyncio.sleep(self.latency)
        return {"text": "ok", "usage": {"in": self.tokens[0], "out": self.tokens[1]}, "target": self.target, "demo": self.demo}


def paid_run(tmp_path, *, calls=None, cost=None, router=None):
    from backend.bus import Bus
    from backend.run import Run
    from backend.store import Store

    cfg = {
        "limits": {"approvePlan": False, "maxParallel": 8, "maxSteps": 4, "maxRevisions": 3, "escalateAfter": 2, "askUserTimeoutMs": 300000, "maxCallsPerRun": calls, "maxCostUSD": cost},
        "pacing": {"fetchMs": 0, "pickupMs": 0, "reviewWalkMs": 0, "verdictMs": 0, "deliverMs": 0},
        "router": {"escalationCombo": "frontier", **PRICING["router"]},
        "providers": {},
        "combos": {},
        "teams": {},
        "ui": {"language": "en"},
    }
    bus = Bus()
    events = []
    bus.emit = lambda t, p=None, _e=bus.emit: (events.append((t, p)), _e(t, p))[1]
    ceo = {"id": "ada", "name": "Ada", "kind": "ceo", "state": "thinking", "text": "planning"}
    sets = []

    def team_set(id, patch):
        sets.append((id, dict(patch)))
        if id == "ada":
            ceo.update(patch)

    team = types.SimpleNamespace(ceo=lambda: ceo, set=team_set, get=lambda id: ceo if id == "ada" else None, abort_waiters=lambda run_id: None)
    ctx = types.SimpleNamespace(config=types.SimpleNamespace(get=lambda: cfg), bus=bus, store=Store(tmp_path / "data"), router=router or PaidRouter(), team=team, workspace_root=str(tmp_path / "ws"), events=events, sets=sets)
    run = Run(goal="A budget test", ctx=ctx, options={"language": "en"})
    run.data["status"] = "running"
    return run


def budget_items(run, status=None):
    return [w for w in run.data["waiting"] if w["kind"] == "budget" and (status is None or w["status"] == status)]


async def ask(run, n=1, **kw):
    return await asyncio.gather(*(run.chat(role="dev", messages=[], **kw) for _ in range(n)))


@pytest.mark.asyncio
async def test_at_the_call_limit_the_run_pauses_and_asks_instead_of_failing(tmp_path):
    run = paid_run(tmp_path, calls=2)
    await ask(run, 2)
    assert run.data["usage"]["providerCalls"] == 2 and not run.data["paused"]
    third = asyncio.ensure_future(run.chat(role="dev", messages=[], agent={"id": "nina"}))
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    await asyncio.sleep(0.05)
    assert not third.done() and run.ctx.router.calls == 2  # the third call never reached the provider
    assert run.data["paused"] is True and run.data["status"] == "running" and run.data["error"] is None
    assert item["reason"] == "calls" and item["spent"]["calls"] == 2 and item["limit"] == {"calls": 2, "costUSD": None} and item["from"] == "ada"
    assert item["text"].startswith("Budget reached: 2 model calls (limit 2).") and "one more block (2 calls)" in item["text"]
    # the SSE `waiting` event carries the request, the timeline says it, the CEO asks
    assert ("waiting", {"runId": run.data["id"], "item": item}) in run.ctx.events
    assert any(m["kind"] == "system" and m["text"].startswith("Budget reached") for m in run.data["messages"])
    assert run.ctx.team.ceo()["state"] == "asking"
    assert ("nina", {"state": "paused"}) in run.ctx.sets
    third.cancel()


@pytest.mark.asyncio
async def test_approving_adds_one_block_and_the_owner_words_reach_the_team(tmp_path):
    run = paid_run(tmp_path, calls=2)
    await ask(run, 2)
    third = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    assert run.answer(item["id"], {"text": "ok, but keep it short", "decision": "approve"}) is True
    await asyncio.wait_for(third, 5)
    assert item["status"] == "answered" and item["answer"]["decision"] == "approve"
    assert run.data["budget"]["limit"] == {"calls": 4, "costUSD": None} and run.data["budget"]["approvals"] == 1
    assert run.data["paused"] is False and run.ctx.router.calls == 3
    assert run.steering[-1]["scope"] == "all" and run.steering[-1]["text"] == "ok, but keep it short"
    assert run.ctx.team.ceo()["state"] == "thinking"  # back to what the CEO was doing
    assert any(m["text"] == "Budget extended: the run goes on up to 4 calls." for m in run.data["messages"])
    assert run.answer(item["id"], {"text": "again", "decision": "approve"}) is False  # closed
    await ask(run, 1)  # the 4th call fits the new block
    trip = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    await until(lambda: len(budget_items(run, "open")) == 1)  # the 5th trips again
    trip.cancel()


@pytest.mark.asyncio
async def test_a_text_answer_and_the_resume_button_are_a_go_ahead_too(tmp_path):
    run = paid_run(tmp_path, calls=1)
    await ask(run, 1)
    call = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    first = await until(lambda: (budget_items(run, "open") or [None])[0])
    assert run.answer(first["id"], {"text": "go on"}) is True  # no decision: not a rejection
    await asyncio.wait_for(call, 5)
    call = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    second = await until(lambda: (budget_items(run, "open") or [None])[0])
    run.resume()  # the Pause / Resume button of the panel
    await asyncio.wait_for(call, 5)
    assert second["status"] == "answered" and second["answer"]["decision"] == "approve"
    assert run.data["budget"]["approvals"] == 2 and run.data["paused"] is False


@pytest.mark.asyncio
async def test_rejecting_stops_the_run_with_the_reason(tmp_path):
    from backend.run import RunStopped

    run = paid_run(tmp_path, calls=1)
    await ask(run, 1)
    call = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    run.answer(item["id"], {"text": "", "decision": "reject"})
    with pytest.raises(RunStopped):
        await asyncio.wait_for(call, 5)
    assert run.data["error"] == "Stopped at the budget: 1 model calls (limit 1)."
    assert run.ctx.router.calls == 1 and run.data["budget"]["approvals"] == 0


@pytest.mark.asyncio
async def test_the_cost_limit_trips_on_the_estimate(tmp_path):
    # 100k in + 20k out on openai/gpt-5 at [1.25, 10] = 0.125 + 0.2 = $0.325 a call
    run = paid_run(tmp_path, cost=0.5, router=PaidRouter(tokens=(100_000, 20_000)))
    await ask(run, 2)
    assert run.data["usage"]["costUSD"] == pytest.approx(0.65)
    call = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    assert item["reason"] == "cost" and item["text"].startswith("Budget reached: $0.65 estimated (limit $0.50).")
    run.answer(item["id"], {"text": "", "decision": "approve"})
    await asyncio.wait_for(call, 5)
    assert run.data["budget"]["limit"]["costUSD"] == pytest.approx(1.15)


@pytest.mark.asyncio
async def test_the_amounts_follow_the_language_of_the_run(tmp_path):
    run = paid_run(tmp_path, cost=0.5, router=PaidRouter(tokens=(100_000, 20_000)))
    run.data["language"] = "it"
    await ask(run, 2)
    call = asyncio.ensure_future(run.chat(role="dev", messages=[]))
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    assert item["text"].startswith("Budget raggiunto: 0,65 $ stimati (limite 0,50 $).")
    call.cancel()


@pytest.mark.asyncio
async def test_parallel_workers_never_pass_the_call_limit_together(tmp_path):
    # 8 workers ask at once on a slow provider: without the slots all 8 would pass a limit of 3
    run = paid_run(tmp_path, calls=3, router=PaidRouter(latency=0.05))
    calls = asyncio.ensure_future(ask(run, 8))
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    await asyncio.sleep(0.2)
    assert run.ctx.router.calls == 3 and len(budget_items(run)) == 1  # one request, however many wait
    run.answer(item["id"], {"text": "", "decision": "approve"})
    nxt = await until(lambda: [w for w in budget_items(run, "open") if w["id"] != item["id"]])
    await asyncio.sleep(0.2)
    assert run.ctx.router.calls == 6 and nxt[0]["limit"]["calls"] == 6
    run.answer(nxt[0]["id"], {"text": "", "decision": "approve"})
    await asyncio.wait_for(calls, 5)
    assert run.ctx.router.calls == 8 and run.data["usage"]["providerCalls"] == 8 and run._in_flight == 0


@pytest.mark.asyncio
async def test_a_call_the_owner_asked_for_is_counted_never_held(tmp_path):
    run = paid_run(tmp_path, calls=1)
    await ask(run, 1)
    await asyncio.wait_for(run.chat(role="ceo", messages=[], owner=True), 5)
    assert run.data["usage"]["providerCalls"] == 2 and not budget_items(run) and not run.data["paused"]


@pytest.mark.asyncio
async def test_the_simulator_never_trips_the_breaker(tmp_path):
    run = paid_run(tmp_path, calls=1, cost=0.01, router=PaidRouter(demo=True, tokens=(10**6, 10**6)))
    await asyncio.wait_for(ask(run, 6), 5)
    assert run.data["usage"]["calls"] == 6 and run.data["usage"]["providerCalls"] == 0 and run.data["usage"]["costUSD"] == 0.0
    assert not budget_items(run) and not run.data["paused"]


@pytest.mark.asyncio
async def test_a_stored_run_or_a_finished_one_never_waits(tmp_path):
    from backend.run import Run

    run = paid_run(tmp_path, calls=1)
    await ask(run, 1)
    stored = Run.from_data(run.data, run.ctx)
    await asyncio.wait_for(stored.chat(role="dev", messages=[]), 5)  # "find a solution" on a stopped run
    run.data["status"] = "completed"
    await asyncio.wait_for(run.chat(role="dev", messages=[]), 5)
    assert not budget_items(run) and run.ctx.router.calls == 3


@pytest.mark.asyncio
async def test_a_stop_while_the_budget_asks_ends_the_waiting_calls(tmp_path):
    from backend.run import RunStopped

    run = paid_run(tmp_path, calls=1)
    await ask(run, 1)
    calls = [asyncio.ensure_future(run.chat(role="dev", messages=[])) for _ in range(3)]
    await until(lambda: budget_items(run, "open"))
    run.stop()
    for c in calls:
        with pytest.raises(RunStopped):
            await asyncio.wait_for(c, 5)
    assert run.ctx.router.calls == 1 and run._in_flight == 0


# ---------- whole missions, answered as by a paid model ----------


def paid_answers(ctx, target="openai/gpt-5", tokens=(2000, 400)):
    """The demo simulator writes the answers, relabelled as a paid model's:
    the mission is the demo one, the budget sees a live run."""
    real = ctx.router.chat

    async def chat(**kwargs):
        res = await real(**kwargs)
        return {**res, "demo": False, "target": target, "provider": target.split("/")[0], "usage": {"in": tokens[0], "out": tokens[1]}}

    ctx.router.chat = chat


async def approve_until_done(run, timeout=120):
    """The owner approves every budget request until the run ends; returns how many."""
    approved = 0
    for _ in range(int(timeout / 0.01)):
        if run.data["status"] in ("completed", "completed_with_failures", "failed", "stopped"):
            return approved
        for item in budget_items(run, "open"):
            # the calls sent before the limit tripped land, then nothing goes out while it is open
            await until(lambda: run._in_flight == 0, timeout=10)
            sent = run.data["usage"]["providerCalls"]
            await asyncio.sleep(0.1)
            assert run.data["usage"]["providerCalls"] == sent and run._in_flight == 0
            assert sent == item["limit"]["calls"]  # exactly at the limit, never past it
            run.answer(item["id"], {"text": "", "decision": "approve"})
            approved += 1
        await asyncio.sleep(0.01)
    raise AssertionError("the run did not finish")


WEB = "Il sito completo della pizzeria con foto e galleria"


@pytest.mark.asyncio
async def test_a_live_mission_pauses_at_each_block_and_completes(ctx):  # noqa: F811
    from backend.run import Run

    ctx.config.get()["limits"]["maxCallsPerRun"] = 25
    paid_answers(ctx)
    run = Run(goal=WEB, ctx=ctx)
    started = asyncio.ensure_future(run.start())
    approved = await approve_until_done(run)
    await asyncio.wait_for(started, 30)
    d = run.data
    assert d["status"] == "completed", d["error"]
    assert d["usage"]["providerCalls"] == d["usage"]["calls"] > 25
    assert approved == d["budget"]["approvals"] == (d["usage"]["providerCalls"] - 1) // 25 >= 2
    # each request went out twice on the `waiting` event: when it opened, when it was answered
    sent = [p["item"]["id"] for t, p in ctx.events if t == "waiting" and p["item"]["kind"] == "budget"]
    assert len(set(sent)) == approved and all(sent.count(i) == 2 for i in set(sent))
    # 2000 in + 400 out at [1.25, 10] = $0.0065 a call
    assert d["usage"]["costUSD"] == pytest.approx(0.0065 * d["usage"]["providerCalls"])


@pytest.mark.asyncio
async def test_a_mission_stopped_at_its_budget_resumes_with_one_more_block(ctx):  # noqa: F811
    from backend.run import Run

    ctx.config.get()["limits"].update(maxCallsPerRun=30, maxCostUSD=0)  # the calls only: the texts below are exact
    paid_answers(ctx)
    run = Run(goal=WEB, ctx=ctx)
    started = asyncio.ensure_future(run.start())
    item = await until(lambda: (budget_items(run, "open") or [None])[0])
    run.answer(item["id"], {"text": "", "decision": "reject"})
    await asyncio.wait_for(started, 30)
    await until(lambda: run._in_flight == 0, timeout=10)  # a stop does not wait for the calls already sent
    d = run.data
    assert d["status"] == "stopped" and d["error"] == "Stopped at the budget: 30 model calls (limit 30)."
    assert d["usage"]["providerCalls"] == 30
    assert any(t["stopped"] for t in d["tasks"]) or any(w.get("stopped") for w in d["workstreams"])

    again = Run.from_data(json.loads(json.dumps(d)), ctx)
    resumed = asyncio.ensure_future(again.resume_from_block())
    await until(lambda: again.data["status"] == "running")
    approved = await approve_until_done(again)
    await asyncio.wait_for(resumed, 30)
    e = again.data
    assert e["status"] == "completed", e["error"]
    assert any(m["text"] == "Resuming adds one more block of budget: the run can go up to 60 calls." for m in e["messages"])
    assert e["budget"]["approvals"] == 1 + approved


@pytest.mark.asyncio
async def test_the_answer_route_takes_the_budget_decision(app, ctx):  # noqa: F811
    ctx.config.get()["limits"]["maxCallsPerRun"] = 10
    paid_answers(ctx)
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": "Un documento di analisi per il bar"})).json()["id"]
        run = app.state.live[rid]
        item = await until(lambda: (budget_items(run, "open") or [None])[0])
        got = (await c.get(f"/api/runs/{rid}")).json()
        assert got["paused"] is True and [w["kind"] for w in got["waiting"] if w["status"] == "open"] == ["budget"]
        assert (await c.post(f"/api/runs/{rid}/answer", json={"itemId": item["id"], "decision": "reject"})).json() == {"ok": True}
        await until(lambda: rid not in app.state.live, timeout=30)
        stored = (await c.get(f"/api/runs/{rid}")).json()
        assert stored["status"] == "stopped" and stored["error"].startswith("Stopped at the budget")
        assert (await c.post(f"/api/runs/{rid}/answer", json={"itemId": item["id"], "decision": "approve"})).status_code == 409
