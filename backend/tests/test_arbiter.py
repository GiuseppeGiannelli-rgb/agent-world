"""Spec 09 §2.3: no bottleneck. A question the owner does not answer in
limits.askUserTimeoutMs (or one they hand back with "Find a solution
yourself") is decided for them, so a run never waits for hours.

- The lead of the task's team (the CEO, when the lead is the one asking)
  writes 2-4 options and picks one.
- When TypeSafe is configured (TYPESAFE_API_KEY), its Jev model picks among
  those options (a "choice" question, POST {base}/systemone). Its pick wins
  when its confidence reaches router.arbiter.minConfidence; below it, or on
  any error, the lead's pick stands.
- The worker gets the decision and why; the question is "auto", the run says
  who decided. limits.autoAnswer false keeps the old rule (the worker decides
  alone). A stopped run's question can be solved too, and resumed.

No test reaches api.typesafe.ai: the router's HTTP client is a MockTransport."""

import asyncio
import json

import httpx
import pytest

from test_attachments import app, client, ctx  # noqa: F401 -- fixtures
from test_resume import DOC, ask_once, until

JEV = "https://api.typesafe.ai/v1/systemone"


class Jev:
    """A fake TypeSafe: answers the choice question with `choice` at `confidence`."""

    def __init__(self, choice="b", confidence=0.91, status=200):
        self.choice, self.confidence, self.status = choice, confidence, status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "down"})
        body = json.loads(request.content)
        options = list(body["questions"]["solution"]["criteria"])
        probs = {o: (self.confidence if o == self.choice else (1 - self.confidence) / max(1, len(options) - 1)) for o in options}
        return httpx.Response(200, json={"model": "jev-1.13.0", "answers": {"solution": {"type": "choice", "choice": self.choice, "confidence": self.confidence, "probabilities": probs}}, "usage": {"input_tokens": 120, "output_tokens": 3}})


def with_jev(ctx, monkeypatch, jev):  # noqa: F811
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-test")
    monkeypatch.delenv("TYPESAFE_BASE_URL", raising=False)
    ctx.router.client = httpx.AsyncClient(transport=httpx.MockTransport(jev.handler))


def a_task(run):
    from backend.plan import new_task

    run.data["workstreams"] = [{"id": "w1", "team": "research", "title": "Ricerca", "objective": "o", "deliverables": [], "acceptance": [], "dependsOn": [], "status": "running"}]
    task = new_task({"id": "w1.1", "wsId": "w1", "team": "research", "title": "Analisi dei concorrenti", "description": "d", "acceptance": [], "outputs": [], "dependsOn": []})
    run.data["tasks"] = [task]
    return task


def worker(ctx):  # noqa: F811
    return next(a for a in ctx.team.list() if a["team"] == "research" and a["kind"] == "worker")


# ---------- the lead decides ----------


@pytest.mark.asyncio
async def test_an_unanswered_question_is_decided_by_the_lead(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    ctx.config.get()["limits"]["askUserTimeoutMs"] = 50
    ask_once(monkeypatch)
    sent = []
    real = ctx.router.chat

    async def spy(**kw):
        sent.append(kw)
        return await real(**kw)

    monkeypatch.setattr(ctx.router, "chat", spy)
    run = Run(goal=DOC, ctx=ctx)
    await asyncio.wait_for(run.start(), timeout=120)
    assert run.data["status"] == "completed", run.data["error"]
    item = next(w for w in run.data["waiting"] if w["kind"] == "question")
    lead = ctx.team.lead("research")
    assert item["status"] == "auto" and item["answer"]["by"] == lead["id"] and item["answer"]["text"]
    assert any(m["kind"] == "decision" and m["from"] == lead["id"] for m in run.data["messages"])
    result = next(m["content"] for kw in sent for m in kw["messages"] if m["role"] == "user" and m["content"].startswith("RESULT of ask_user"))
    assert f"{lead['name']} decided for you" in result and item["answer"]["text"] in result


@pytest.mark.asyncio
async def test_find_a_solution_answers_at_once(app, ctx, monkeypatch):  # noqa: F811
    ctx.config.get()["limits"]["askUserTimeoutMs"] = 600000
    ask_once(monkeypatch)
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": DOC})).json()["id"]
        run = app.state.live[rid]
        await until(lambda: any(w["kind"] == "question" and w["status"] == "open" for w in run.data["waiting"]))
        item = next(w for w in run.data["waiting"] if w["kind"] == "question")
        res = await c.post(f"/api/runs/{rid}/answer", json={"itemId": item["id"], "solve": True})
        assert res.status_code == 200 and res.json()["decision"]
        assert item["status"] == "auto"
        await until(lambda: not app.state.live, timeout=120)
    assert ctx.store.get(rid)["status"] == "completed"


@pytest.mark.asyncio
async def test_with_auto_answer_off_the_worker_decides_alone(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    ctx.config.get()["limits"].update({"askUserTimeoutMs": 50, "autoAnswer": False})
    ask_once(monkeypatch)
    run = Run(goal=DOC, ctx=ctx)
    await asyncio.wait_for(run.start(), timeout=120)
    item = next(w for w in run.data["waiting"] if w["kind"] == "question")
    assert item["status"] == "expired" and not any(m["kind"] == "decision" for m in run.data["messages"])


# ---------- TypeSafe picks ----------


@pytest.mark.asyncio
async def test_typesafe_picks_among_the_lead_options(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    jev = Jev(choice="b", confidence=0.91)
    with_jev(ctx, monkeypatch, jev)
    run = Run(goal=DOC, ctx=ctx)
    assert run.data["mode"] == "demo"  # a TypeSafe key alone writes nothing
    task = a_task(run)
    decision = await run.auto_answer(task, worker(ctx), "Che tono vuoi per i testi?")
    assert decision["pick"] == "b" and decision["arbiter"] == "typesafe" and decision["confidence"] == 0.91
    assert decision["solution"] in decision["text"] and "TypeSafe" in decision["text"]
    (req,) = jev.requests
    assert str(req.url) == JEV and req.headers["authorization"] == "Bearer ts-test"
    body = json.loads(req.content)
    assert body["model"] == "jev-latest"
    assert body["state"]["question"] == "Che tono vuoi per i testi?" and body["state"]["task"].startswith("w1.1")
    q = body["questions"]["solution"]
    assert q["type"] == "choice" and set(q["criteria"]) == {"a", "b"} and q["instructions"]


@pytest.mark.asyncio
async def test_a_doubtful_typesafe_keeps_the_lead_pick(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    with_jev(ctx, monkeypatch, Jev(choice="b", confidence=0.3))
    run = Run(goal=DOC, ctx=ctx)
    decision = await run.auto_answer(a_task(run), worker(ctx), "Che tono vuoi?")
    assert decision["pick"] == "a" and decision["arbiter"] == "lead"


@pytest.mark.asyncio
async def test_a_typesafe_failure_keeps_the_lead_pick(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    jev = Jev(status=500)
    with_jev(ctx, monkeypatch, jev)
    run = Run(goal=DOC, ctx=ctx)
    decision = await run.auto_answer(a_task(run), worker(ctx), "Che tono vuoi?")
    assert decision["pick"] == "a" and decision["arbiter"] == "lead" and len(jev.requests) == 1


@pytest.mark.asyncio
async def test_typesafe_is_never_called_without_its_key(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    jev = Jev()
    with_jev(ctx, monkeypatch, jev)
    monkeypatch.delenv("TYPESAFE_API_KEY")
    run = Run(goal=DOC, ctx=ctx)
    decision = await run.auto_answer(a_task(run), worker(ctx), "Che tono vuoi?")
    assert decision["arbiter"] == "lead" and jev.requests == []


@pytest.mark.asyncio
async def test_the_ceo_decides_when_the_lead_is_the_one_asking(ctx):  # noqa: F811
    from backend.run import Run

    run = Run(goal=DOC, ctx=ctx)
    decision = await run.auto_answer(a_task(run), ctx.team.lead("research"), "Quale fonte usiamo?")
    assert decision["by"] == run.ceo["id"]


# ---------- a stopped run ----------


@pytest.mark.asyncio
async def test_a_stopped_run_question_can_be_solved_and_resumed(app, ctx, monkeypatch):  # noqa: F811
    ctx.config.get()["limits"]["askUserTimeoutMs"] = 600000
    ask_once(monkeypatch)
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": DOC})).json()["id"]
        run = app.state.live[rid]
        await until(lambda: any(w["kind"] == "question" and w["status"] == "open" for w in run.data["waiting"]))
        await c.post(f"/api/runs/{rid}/stop")
        await until(lambda: not app.state.live)
        item = next(w for w in ctx.store.get(rid)["waiting"] if w["kind"] == "question")
        assert item["status"] == "pending"
        res = await c.post(f"/api/runs/{rid}/answer", json={"itemId": item["id"], "solve": True})
        assert res.status_code == 200 and res.json()["resumable"] is True and res.json()["decision"]
        stored = next(w for w in ctx.store.get(rid)["waiting"] if w["id"] == item["id"])
        assert stored["status"] == "auto"
        assert (await c.post(f"/api/runs/{rid}/resume")).status_code == 200
        await until(lambda: not app.state.live, timeout=120)
    assert ctx.store.get(rid)["status"] == "completed"
