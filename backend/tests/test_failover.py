"""Spec 09 §1: a model that runs out of credit, hits a rate limit, disappears
(404) or times out never stops the work.

- Inside one call the router already moves to the next target (spec 08). The
  worker keeps its whole conversation: the new model gets every earlier step,
  then a MODEL SWITCH message with the run context sized for it.
- When every model of the cascade fails, Run.chat no longer raises: it waits
  for the soonest model to come back and tries again. After
  limits.modelRetries tries it opens a "model" request for the owner (add a
  key, register a provider, or just retry), and keeps trying in the
  background: the first answer from a model closes it.
- Every switch is visible: a "switch" note in the task, a message in the run,
  a model.switch event; for leads, the CEO and QA too.

The providers here are fake HTTP servers that answer like the demo
simulator (router/mock.answer), so the whole run goes through the real
router: classifier, benches, cascade."""

import asyncio
import json
import shutil
import types
from pathlib import Path

import httpx
import pytest

from backend.brain import Brain
from backend.bus import Bus
from backend.config import Config
from backend.media import Media
from backend.router.index import Router
from backend.router.mock import ROLE_RE, answer
from backend.store import Store
from backend.team import Team

REPO = Path(__file__).resolve().parents[2]
QUOTA = {"error": {"message": "You exceeded your current quota, please check your plan and billing details.", "type": "insufficient_quota", "code": "insufficient_quota"}}
GOAL = "Un documento di analisi per il bar"  # research, design, content: no media


class Upstream:
    """Two fake providers. `fail` decides, per call, whether a target answers:
    fail(provider, n) -> None (answer like the simulator) or (status, body)."""

    def __init__(self, fail=None):
        self.fail = fail or (lambda provider, n: None)
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        provider = request.url.host
        n = len([c for c in self.calls if c["provider"] == provider])
        messages = body.get("messages") or []
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        m = ROLE_RE.search(system)
        marker, team = (m.group(1), m.group(2) or "") if m else ("other", "")
        call = {"provider": provider, "model": body.get("model"), "marker": marker, "team": team, "messages": messages, "status": 200}
        self.calls.append(call)
        failure = self.fail(provider, n)
        if failure:
            call["status"] = failure[0]
            return httpx.Response(failure[0], json=failure[1])
        return httpx.Response(200, json={"model": body.get("model"), "choices": [{"message": {"content": answer(marker, messages, team)}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})


def live_ctx(tmp_path, monkeypatch, upstream: Upstream, *, limits=None):
    monkeypatch.setenv("AGENT_WORLD_FAST", "1")
    default = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    for section in (default["providers"], default["media"]["providers"]):
        for p in section.values():
            for k in ("keyEnv", "baseUrlEnv"):
                if p.get(k):
                    monkeypatch.delenv(p[k], raising=False)
    monkeypatch.setenv("ALPHA_KEY", "a")
    monkeypatch.setenv("BETA_KEY", "b")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(REPO / "config" / "default.json", config_dir / "default.json")
    config = Config(config_dir)
    cfg = config.get()
    cfg["router"]["logCalls"] = False
    cfg["router"]["emergencyMock"] = False  # the simulator never steps in: every answer is a real call
    cfg["providers"]["alpha"] = {"kind": "openai", "baseUrl": "http://alpha/v1", "keyEnv": "ALPHA_KEY"}
    cfg["providers"]["beta"] = {"kind": "openai", "baseUrl": "http://beta/v1", "keyEnv": "BETA_KEY"}
    for combo in cfg["combos"].values():
        combo["models"] = ["alpha/m1", "beta/m2"]
    cfg["limits"].update({"modelWaitMaxMs": 30, "modelRetries": 2, **(limits or {})})
    bus = Bus()
    events: list[tuple] = []
    bus.emit = lambda type_, payload=None, _emit=bus.emit: (events.append((type_, payload)), _emit(type_, payload))[1]
    router = Router(config, tmp_path / "data", bus, client=httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler)))
    team = Team(bus)
    team.load(cfg["staff"])
    skills = types.SimpleNamespace(skills=[], search=lambda *a, **k: [], summary=lambda: {"count": 0, "sources": []})
    ctx = types.SimpleNamespace(
        config=config, bus=bus, store=Store(tmp_path / "data"), router=router, team=team,
        brain=Brain(tmp_path / "data" / "brain.json", bus), skills=skills, media=Media(config=config, bus=bus),
        workspace_root=str(tmp_path / "workspace"), events=events,
    )
    return ctx


def _worker_calls(upstream, provider=None):
    return [c for c in upstream.calls if c["marker"] == "tasker" and (provider is None or c["provider"] == provider)]


@pytest.mark.asyncio
async def test_a_worker_keeps_its_steps_when_its_model_runs_out_of_credit(tmp_path, monkeypatch):
    """alpha answers the first worker steps, then its credit is gone (429
    insufficient_quota): beta takes the very next step of the same task."""
    from backend.run import Run

    seen_worker = {"n": 0}

    def fail(provider, n):
        if provider != "alpha":
            return None
        # every call before the third worker step answers; from then on alpha has no credit
        return (429, QUOTA) if seen_worker["n"] >= 3 else None

    upstream = Upstream(fail)
    real = upstream.handler

    def handler(request):
        body = json.loads(request.content or b"{}")
        if "[[role:tasker" in json.dumps(body.get("messages", [])[:1]) and request.url.host == "alpha":
            seen_worker["n"] += 1
        return real(request)

    upstream.handler = handler
    # one task at a time: alpha's third worker step is the middle of the first task
    ctx = live_ctx(tmp_path, monkeypatch, upstream, limits={"maxParallel": 1})
    run = Run(goal=GOAL, ctx=ctx)
    assert run.data["mode"] == "live"
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] == "completed", d["error"]
    assert all(t["status"] == "done" for t in d["tasks"])

    # the task that lost alpha mid-way finished on beta, with its earlier steps
    swapped = next(t for t in d["tasks"] if any(h["kind"] == "switch" for h in t["history"]))
    note = next(h for h in swapped["history"] if h["kind"] == "switch")
    assert note["frm"] == "alpha/m1" and note["to"] == "beta/m2" and note["reason"] == "quota"
    first_beta = next(c for c in _worker_calls(upstream, "beta") if f"TASK ID: {swapped['id']}" in c["messages"][1]["content"])
    assert any(m["role"] == "assistant" for m in first_beta["messages"]), "beta got the task without the steps alpha already took"
    later = [c for c in _worker_calls(upstream, "beta") if f"TASK ID: {swapped['id']}" in c["messages"][1]["content"]][1:]
    assert any(m["content"].startswith("MODEL SWITCH: you now run on beta/m2") for c in later for m in c["messages"] if m["role"] == "user")
    # alpha was benched for its credit: after its first 429 it only saw the calls
    # already in flight (parallel tasks), and never answered again
    first_quota = next(i for i, c in enumerate(upstream.calls) if c["provider"] == "alpha" and c["status"] == 429)
    after = [c for c in upstream.calls[first_quota + 1 :] if c["provider"] == "alpha"]
    assert all(c["status"] == 429 for c in after)
    assert len(after) <= 3  # a lead or two splitting another workstream at that moment
    assert ctx.router.provider_cooldowns["alpha"]["reason"] == "quota_exhausted"
    # and the owner sees it
    assert any(m["kind"] == "switch" and "alpha/m1" in m["text"] and "beta/m2" in m["text"] for m in d["messages"])
    assert any(t == "model.switch" and p["from"] == "alpha/m1" and p["to"] == "beta/m2" for t, p in ctx.events)


@pytest.mark.asyncio
async def test_when_every_model_is_down_the_run_waits_instead_of_failing(tmp_path, monkeypatch):
    """Both providers answer 503 to the first 6 calls: no task fails, the
    run waits for a model and goes on when one comes back."""
    from backend.run import Run

    total = {"n": 0}

    def fail(provider, n):
        total["n"] += 1
        return (503, {"error": "overloaded"}) if total["n"] <= 6 else None

    upstream = Upstream(fail)
    ctx = live_ctx(tmp_path, monkeypatch, upstream, limits={"modelRetries": 10})
    run = Run(goal=GOAL, ctx=ctx)
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] == "completed", d["error"]
    assert d["usage"]["modelWaits"] >= 1
    assert not [w for w in d["waiting"] if w["kind"] == "model"]  # it came back before the owner was needed


@pytest.mark.asyncio
async def test_after_the_retries_the_owner_is_asked_and_the_first_answer_closes_it(tmp_path, monkeypatch):
    from backend.run import Run

    state = {"down": True}
    upstream = Upstream(lambda provider, n: (503, {"error": "overloaded"}) if state["down"] else None)
    ctx = live_ctx(tmp_path, monkeypatch, upstream, limits={"modelRetries": 1})
    run = Run(goal=GOAL, ctx=ctx)
    task = asyncio.ensure_future(run.start())
    for _ in range(400):
        await asyncio.sleep(0.01)
        items = [w for w in run.data["waiting"] if w["kind"] == "model" and w["status"] == "open"]
        if items:
            break
    assert items, "no 'model' request reached the owner"
    item = items[0]
    assert item["from"] == run.ceo["id"]  # the CEO's planning call: zero-stop holds for every role
    assert run.data["status"] == "planning"
    state["down"] = False  # a key was added, a cooldown ended...: the background retry finds a model
    await asyncio.wait_for(task, timeout=60)
    assert run.data["status"] == "completed", run.data["error"]
    assert item["status"] == "resolved"


@pytest.mark.asyncio
async def test_the_owner_can_retry_a_model_request_right_away(tmp_path, monkeypatch):
    from backend.run import Run

    state = {"down": True}
    upstream = Upstream(lambda provider, n: (503, {"error": "overloaded"}) if state["down"] else None)
    ctx = live_ctx(tmp_path, monkeypatch, upstream, limits={"modelRetries": 0, "modelWaitMaxMs": 60000})  # the request opens at the first failure
    run = Run(goal=GOAL, ctx=ctx)
    task = asyncio.ensure_future(run.start())
    for _ in range(400):
        await asyncio.sleep(0.01)
        items = [w for w in run.data["waiting"] if w["kind"] == "model" and w["status"] == "open"]
        if items:
            break
    assert items
    state["down"] = False
    calls_before = len(upstream.calls)
    assert run.answer(items[0]["id"], {"text": "added a key, try again"}) is True  # not 60 s later
    for _ in range(100):
        await asyncio.sleep(0.01)
        if len(upstream.calls) > calls_before:
            break
    assert len(upstream.calls) > calls_before
    run.stop()
    await asyncio.wait_for(task, timeout=10)


@pytest.mark.asyncio
async def test_a_lead_or_qa_switch_is_reported_too(tmp_path, monkeypatch):
    """QA (frontier) loses alpha to a 404: the judge goes on with beta, and says so."""
    from backend.run import Run

    upstream = Upstream(lambda provider, n: (404, {"error": {"message": "The model `m1` does not exist"}}) if provider == "alpha" else None)
    ctx = live_ctx(tmp_path, monkeypatch, upstream)
    run = Run(goal=GOAL, ctx=ctx)
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] == "completed", d["error"]
    switches = [m for m in d["messages"] if m["kind"] == "switch"]
    assert switches and switches[0]["from"] == run.ceo["id"]  # the very first call was the CEO's plan
    assert "model_not_found" in switches[0]["text"] or "404" in switches[0]["text"] or "beta/m2" in switches[0]["text"]
    # one message per agent and pair, not one per call
    pairs = [(m["from"], m["text"]) for m in switches]
    assert len(pairs) == len(set(pairs))


@pytest.mark.asyncio
async def test_the_router_says_which_targets_failed(tmp_path, monkeypatch):
    upstream = Upstream(lambda provider, n: (429, QUOTA) if provider == "alpha" else None)
    ctx = live_ctx(tmp_path, monkeypatch, upstream)
    res = await ctx.router.chat(use="fast", messages=[{"role": "system", "content": "[[role:advisor]]"}, {"role": "user", "content": "hi"}])
    assert res["target"] == "beta/m2"
    assert res["failed"] == [{"target": "alpha/m1", "kind": "quota"}]


def test_the_router_knows_when_the_next_model_comes_back(tmp_path, monkeypatch):
    upstream = Upstream()
    ctx = live_ctx(tmp_path, monkeypatch, upstream)
    router = ctx.router
    assert router.next_ready_ms("fast") == 0
    now = router._now()
    router.cooldowns["alpha/m1"] = {"until": now + 5000, "failures": 1, "reason": "x"}
    router.cooldowns["beta/m2"] = {"until": now + 9000, "failures": 1, "reason": "x"}
    assert 4000 < router.next_ready_ms("fast") <= 5000
    router.provider_cooldowns["alpha"] = {"until": now + 6 * 3600 * 1000, "reason": "quota_exhausted"}
    assert 8000 < router.next_ready_ms("fast") <= 9000  # a benched provider counts with its bench
    monkeypatch.delenv("ALPHA_KEY")
    monkeypatch.delenv("BETA_KEY")
    assert router.next_ready_ms("fast") is None  # nothing can come back on its own: no key at all


@pytest.mark.asyncio
async def test_a_flapping_rate_limit_is_reported_once_per_agent(tmp_path, monkeypatch):
    """alpha answers 429 to every call and its cooldown is over at once, so it is
    tried (and fails) again and again: the owner reads it once per agent."""
    from backend.run import Run

    upstream = Upstream(lambda provider, n: (429, {"error": {"message": "Rate limit reached for requests"}}) if provider == "alpha" else None)
    ctx = live_ctx(tmp_path, monkeypatch, upstream)
    ctx.config.get()["router"].update({"cooldownBaseMs": 1, "cooldownMaxMs": 1})
    run = Run(goal=GOAL, ctx=ctx)
    await asyncio.wait_for(run.start(), timeout=60)
    assert run.data["status"] == "completed", run.data["error"]
    assert len([c for c in upstream.calls if c["provider"] == "alpha"]) > 10  # it kept failing
    switches = [m["from"] for m in run.data["messages"] if m["kind"] == "switch"]
    assert switches and len(switches) == len(set(switches))
