"""Spec 09 §2: the owner talks to a blocked task, its questions survive the
end of the run (and a restart of the server), and a stopped run resumes from
where it stopped.

- A question still open when the run ends is "pending", not "expired": it can
  be answered while the run is stopped, and the answer reaches the task when
  the run resumes. A plan approval or a model request does expire.
- POST /api/runs/{id}/tasks/{task}/interact records the owner's words in the
  task (task.interactions). The worker gets them at its next step (working),
  at its first step (queued), or when the run resumes (stopped). A failed task
  of a live run goes back in the queue, with the tasks it had blocked.
- POST /api/runs/{id}/resume on a stored run (stopped, completed with
  failures, failed) runs again only what is not done: done tasks keep their
  files, attempts and history. A worker that was mid-task starts again from
  its own conversation, saved when the run ended (data/runs/sessions/).
- The scenario of the spec: the images fail (no credit), the site waits; the
  owner gives the photos to the blocked image task and resumes; the images
  become theirs and the site shows them."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from test_attachments import app, client, ctx, jpeg  # noqa: F401 -- fixtures too

WEB = "Il sito completo della pizzeria con foto e galleria"
DOC = "Un documento di analisi per il bar"


async def until(pred, timeout=60.0, step=0.01):
    for _ in range(int(timeout / step)):
        if pred():
            return True
        await asyncio.sleep(step)
    raise AssertionError("condition not reached")


def done_ids(d):
    return {t["id"] for t in d["tasks"] if t["status"] == "done"}


# ---------- resume ----------


@pytest.mark.asyncio
async def test_a_stopped_run_resumes_from_where_it_stopped(ctx):  # noqa: F811
    from backend.run import Run

    run = Run(goal=WEB, ctx=ctx)
    started = asyncio.ensure_future(run.start())
    await until(lambda: len(done_ids(run.data)) >= 3)
    run.stop()
    await asyncio.wait_for(started, timeout=30)
    d = run.data
    assert d["status"] == "stopped"
    before = {t["id"]: (t["attempts"], len(t["history"]), t["finishedAt"]) for t in d["tasks"] if t["status"] == "done"}
    files = {p: (Path(d["workspace"]) / p).stat().st_mtime_ns for t in d["tasks"] if t["status"] == "done" for p in t["files"] if (Path(d["workspace"]) / p).exists()}
    todo = [t["id"] for t in d["tasks"] if t["status"] != "done"] + [w["id"] for w in d["workstreams"] if not any(t["wsId"] == w["id"] for t in d["tasks"])]
    assert todo, "nothing was left to do"

    again = Run.from_data(json.loads(json.dumps(d)), ctx)
    await asyncio.wait_for(again.resume_from_block(), timeout=120)
    e = again.data
    assert e["status"] == "completed", (e["error"], [(t["id"], t["status"]) for t in e["tasks"]])
    assert e["resumes"] == 1 and e["report"]
    for tid, snap in before.items():
        t = again.task_by_id(tid)
        assert (t["attempts"], len(t["history"]), t["finishedAt"]) == snap, tid  # done work is not done again
    for p, mtime in files.items():
        assert (Path(e["workspace"]) / p).stat().st_mtime_ns == mtime, p
    assert all(t["status"] == "done" for t in e["tasks"])
    assert any(m["kind"] == "system" and "resum" in m["text"].lower() for m in e["messages"])


@pytest.mark.asyncio
async def test_a_worker_stopped_mid_task_resumes_its_own_conversation(ctx, monkeypatch):  # noqa: F811
    from backend.run import Run

    run = Run(goal=DOC, ctx=ctx)
    started = asyncio.ensure_future(run.start())
    mid = {}

    def mid_task():
        for t in run.data["tasks"]:
            if t["status"] == "working" and len([h for h in t["history"] if h["kind"] == "step"]) >= 2:
                mid["id"] = t["id"]
                return True
        return False

    await until(mid_task)
    run.stop()
    await asyncio.wait_for(started, timeout=30)
    sessions = Path(ctx.store.dir) / "sessions" / f"{run.data['id']}.json"
    saved = json.loads(sessions.read_text(encoding="utf-8"))
    assert any(m["role"] == "assistant" for m in saved[mid["id"]]["messages"])

    sent = []
    real = ctx.router.chat

    async def spy(**kw):
        sent.append(kw)
        return await real(**kw)

    monkeypatch.setattr(ctx.router, "chat", spy)
    again = Run.from_data(json.loads(json.dumps(run.data)), ctx)
    await asyncio.wait_for(again.resume_from_block(), timeout=120)
    assert again.data["status"] == "completed", again.data["error"]
    first = next(kw["messages"] for kw in sent if kw["messages"][0]["content"].startswith("[[role:tasker") and f"TASK ID: {mid['id']}" in kw["messages"][1]["content"])
    assert any(m["role"] == "assistant" for m in first), "the worker started from scratch"
    assert any(m["role"] == "user" and m["content"].startswith("RUN RESUMED") for m in first)


# ---------- questions that survive ----------


def ask_once(monkeypatch, task_id="w1.1", question="Che tono vuoi per i testi?"):
    """The demo worker of one task asks the owner first (ask_user), once."""
    from backend.router import mock

    real = mock.worker_turn

    def turn(messages, team, lang="en"):
        brief = messages[1]["content"] if len(messages) > 1 else ""
        asked = any(m["role"] == "user" and str(m["content"]).startswith("RESULT of ask_user") for m in messages)
        if f"TASK ID: {task_id}" in brief and not asked and not any("ask_user" in str(m["content"]) for m in messages if m["role"] == "assistant"):
            return {"thought": "I need the owner.", "tool": "ask_user", "args": {"question": question}}
        return real(messages, team, lang)

    monkeypatch.setattr(mock, "worker_turn", turn)


@pytest.mark.asyncio
async def test_an_open_question_survives_the_end_of_the_run_and_a_restart(app, ctx, monkeypatch, tmp_path):  # noqa: F811
    from backend.store import Store

    ctx.config.get()["limits"]["askUserTimeoutMs"] = 600000
    ask_once(monkeypatch)
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": DOC})).json()["id"]
        run = app.state.live[rid]
        await until(lambda: any(w["kind"] == "question" and w["status"] == "open" for w in run.data["waiting"]))
        assert (await c.post(f"/api/runs/{rid}/stop")).status_code == 200
        await until(lambda: not app.state.live)
        item = next(w for w in run.data["waiting"] if w["kind"] == "question")
        assert item["status"] == "pending"
        # a new session, or a restarted server: the question is still there
        fresh = Store(Path(ctx.store.dir).parent)
        again = next(w for w in fresh.get(rid)["waiting"] if w["id"] == item["id"])
        assert again["status"] == "pending" and again["taskId"] == "w1.1"
        res = await c.post(f"/api/runs/{rid}/answer", json={"itemId": item["id"], "text": "Tono caldo e familiare"})
        assert res.status_code == 200 and res.json()["resumable"] is True
        stored = ctx.store.get(rid)
        answered = next(w for w in stored["waiting"] if w["id"] == item["id"])
        assert answered["status"] == "answered" and answered["answer"]["text"] == "Tono caldo e familiare"
        task = next(t for t in stored["tasks"] if t["id"] == "w1.1")
        assert task["interactions"][-1]["text"] == "Tono caldo e familiare"

        sent = []
        real = ctx.router.chat

        async def spy(**kw):
            sent.append(kw)
            return await real(**kw)

        monkeypatch.setattr(ctx.router, "chat", spy)
        assert (await c.post(f"/api/runs/{rid}/resume")).status_code == 200
        await until(lambda: not app.state.live, timeout=120)
        final = ctx.store.get(rid)
        assert final["status"] == "completed", final["error"]
        assert any("Tono caldo e familiare" in m["content"] for kw in sent for m in kw["messages"] if m["role"] == "user" and "TASK ID: w1.1" in kw["messages"][1]["content"])


@pytest.mark.asyncio
async def test_a_plan_approval_does_not_survive(ctx):  # noqa: F811
    from backend.run import Run

    run = Run(goal=DOC, ctx=ctx, options={"approvePlan": True})
    started = asyncio.ensure_future(run.start())
    await until(lambda: any(w["kind"] == "plan" and w["status"] == "open" for w in run.data["waiting"]))
    run.stop()
    await asyncio.wait_for(started, timeout=30)
    assert next(w for w in run.data["waiting"] if w["kind"] == "plan")["status"] == "expired"


# ---------- talking to one task ----------


@pytest.mark.asyncio
async def test_the_owner_talks_to_a_working_task(app, ctx, monkeypatch):  # noqa: F811
    sent = []
    real = ctx.router.chat

    async def spy(**kw):
        sent.append(kw)
        return await real(**kw)

    monkeypatch.setattr(ctx.router, "chat", spy)
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": DOC})).json()["id"]
        run = app.state.live[rid]
        await until(lambda: any(t["status"] == "working" for t in run.data["tasks"]))
        task = next(t for t in run.data["tasks"] if t["status"] == "working")
        res = await c.post(f"/api/runs/{rid}/tasks/{task['id']}/interact", json={"text": "Metti in evidenza i prezzi bassi"})
        assert res.status_code == 200
        body = res.json()
        assert body["delivered"] == "next_step" and body["reply"]
        assert task["interactions"][0]["from"] == "user" and task["interactions"][0]["text"] == "Metti in evidenza i prezzi bassi"
        assert task["interactions"][1]["from"] == task["agentId"] or task["interactions"][1]["from"] != "user"
        await until(lambda: not app.state.live, timeout=120)
    assert any(m["content"].startswith("MESSAGE FROM THE OWNER about this task: Metti in evidenza i prezzi bassi") for kw in sent for m in kw["messages"] if m["role"] == "user")
    assert any(m["kind"] == "direct" for m in ctx.store.get(rid)["messages"])


@pytest.mark.asyncio
async def test_a_queued_task_gets_the_words_when_it_starts(app, ctx, monkeypatch):  # noqa: F811
    sent = []
    real = ctx.router.chat

    async def spy(**kw):
        sent.append(kw)
        return await real(**kw)

    monkeypatch.setattr(ctx.router, "chat", spy)
    async with client(app) as c:
        # a complex mission: its leads split the work, and the last part waits for the others
        rid = (await c.post("/api/runs", json={"goal": "Un documento completo di analisi per il bar"})).json()["id"]
        run = app.state.live[rid]
        await until(lambda: any(t["status"] == "queued" and t["dependsOn"] for t in run.data["tasks"]))
        task = next(t for t in run.data["tasks"] if t["status"] == "queued" and t["dependsOn"])
        res = await c.post(f"/api/runs/{rid}/tasks/{task['id']}/interact", json={"text": "Chiudi con una tabella riassuntiva"})
        assert res.json()["delivered"] == "when_it_starts"
        await until(lambda: not app.state.live, timeout=120)
    firsts = [kw["messages"] for kw in sent if kw["messages"][0]["content"].startswith("[[role:tasker") and f"TASK ID: {task['id']}" in kw["messages"][1]["content"]]
    assert any(m["content"].startswith("MESSAGE FROM THE OWNER about this task: Chiudi con una tabella riassuntiva") for m in firsts[0])


@pytest.mark.asyncio
async def test_interact_checks_its_input(app, ctx):  # noqa: F811
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": DOC})).json()["id"]
        await until(lambda: app.state.live[rid].data["tasks"] if rid in app.state.live else True)
        assert (await c.post(f"/api/runs/{rid}/tasks/nope/interact", json={"text": "x"})).status_code == 404
        assert (await c.post("/api/runs/nope/tasks/w1.1/interact", json={"text": "x"})).status_code == 404
        if rid in app.state.live and app.state.live[rid].data["tasks"]:
            tid = app.state.live[rid].data["tasks"][0]["id"]
            assert (await c.post(f"/api/runs/{rid}/tasks/{tid}/interact", json={"text": ""})).status_code == 400
            assert (await c.post(f"/api/runs/{rid}/tasks/{tid}/interact", json={"text": "ok", "attachments": ["zzz"]})).status_code == 400
        await until(lambda: not app.state.live, timeout=120)


@pytest.mark.asyncio
async def test_resume_is_refused_while_another_run_works(app, ctx):  # noqa: F811
    async with client(app) as c:
        first = (await c.post("/api/runs", json={"goal": DOC})).json()["id"]
        await until(lambda: any(t["status"] == "done" for t in app.state.live[first].data["tasks"]) if first in app.state.live else True)
        await c.post(f"/api/runs/{first}/stop")
        await until(lambda: not app.state.live)
        second = (await c.post("/api/runs", json={"goal": "Una nota breve per il bar"})).json()["id"]
        res = await c.post(f"/api/runs/{first}/resume")
        assert res.status_code == 409
        await c.post(f"/api/runs/{second}/stop")
        await until(lambda: not app.state.live)
        completed = (await c.post(f"/api/runs/{first}/resume")).status_code
        assert completed == 200
        await until(lambda: not app.state.live, timeout=120)
        assert ctx.store.get(first)["status"] == "completed"
        assert (await c.post(f"/api/runs/{first}/resume")).status_code == 409  # nothing left to resume


# ---------- the scenario of the spec ----------


@pytest.mark.asyncio
async def test_the_owner_photos_unblock_the_images_and_the_site_shows_them(app, ctx, monkeypatch):  # noqa: F811
    """'Generazione immagini 0/4' and 'Sviluppo e integrazione' stuck in queued:
    no credit for images. The owner gives the photos to the blocked task, says
    to use them, resumes: the images are theirs, the site goes on and shows them."""
    cfg = ctx.config.get()
    cfg["limits"].update({"maxRevisions": 1, "maxSteps": 6})

    async def no_credit(*a, **k):
        raise RuntimeError("HTTP 429: insufficient_quota")

    monkeypatch.setattr(ctx.media, "image", no_credit)
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": WEB})).json()["id"]
        await until(lambda: not app.state.live, timeout=120)
        d = ctx.store.get(rid)
        assert d["status"] == "completed_with_failures"
        images = [t for t in d["tasks"] if t["team"] == "genai"]
        assert images and all(t["status"] == "failed" for t in images)
        dev = next(w for w in d["workstreams"] if w["team"] == "dev")
        assert dev["status"] == "skipped"  # it never started: it waited for the images

        blocked = images[0]
        for name in ("facciata.jpg", "forno.jpg"):
            up = await c.post(f"/api/runs/{rid}/attachments", params={"name": name, "taskId": blocked["id"]}, content=jpeg(1600, 900))
            assert up.status_code == 201
        res = await c.post(f"/api/runs/{rid}/tasks/{blocked['id']}/interact", json={"text": "Non usare l'API immagini: usa le mie foto per la hero e la galleria", "resume": True})
        assert res.status_code == 200 and res.json()["resumed"] is True
        await until(lambda: not app.state.live, timeout=120)
    e = ctx.store.get(rid)
    assert e["status"] == "completed", (e["error"], [(t["id"], t["status"], t["error"]) for t in e["tasks"] if t["status"] != "done"], [(w["id"], w["team"], w["status"], w.get("error")) for w in e["workstreams"]])
    genai = [t for t in e["tasks"] if t["team"] == "genai"]
    assert all(t["status"] == "done" for t in genai)
    assert any(h.get("tool") == "use_attachment" for t in genai for h in t["history"])
    page = (Path(e["workspace"]) / "index.html").read_text(encoding="utf-8")
    assert 'src="assets/hero.jpg"' in page


# ---------- the store after a crash, the words that come at the last moment ----------


def test_after_a_crash_the_store_keeps_the_questions_and_marks_the_work_interrupted(tmp_path):
    """The server died with a run in flight: on disk it is still "running", its
    question "open". Loaded again, the question waits for the owner, the plan
    approval expires, and what was in flight is interrupted (a resume runs it)."""
    from backend.store import Store

    runs = tmp_path / "runs"
    runs.mkdir()
    run = {
        "id": "abc12345", "status": "running", "createdAt": "2026-10-16T10:00:00.000Z", "error": None,
        "workstreams": [{"id": "w1", "status": "running"}, {"id": "w2", "status": "done"}],
        "tasks": [{"id": "w1.1", "status": "working"}, {"id": "w1.2", "status": "queued"}, {"id": "w2.1", "status": "done"}],
        "waiting": [{"id": "q1", "kind": "question", "status": "open"}, {"id": "p1", "kind": "plan", "status": "open"}, {"id": "m1", "kind": "model", "status": "open"}],
    }
    (runs / "abc12345.json").write_text(json.dumps(run), encoding="utf-8")
    d = Store(tmp_path).get("abc12345")
    assert d["status"] == "stopped"
    assert {w["id"]: w["status"] for w in d["waiting"]} == {"q1": "pending", "p1": "expired", "m1": "expired"}
    assert [(t["id"], t["status"], t.get("stopped")) for t in d["tasks"]] == [("w1.1", "skipped", True), ("w1.2", "skipped", True), ("w2.1", "done", None)]
    assert d["workstreams"][0]["stopped"] is True and d["workstreams"][1]["status"] == "done"


@pytest.mark.asyncio
async def test_words_that_come_while_the_worker_finishes_are_never_lost(ctx, monkeypatch):  # noqa: F811
    """The owner writes while the worker is sending its finish: the task is not
    delivered until its worker has read the words and finished again."""
    from backend.plan import new_task
    from backend.run import Run

    run = Run(goal=DOC, ctx=ctx)
    run.data["workstreams"] = [{"id": "w1", "team": "research", "title": "t", "objective": "o", "deliverables": [], "acceptance": [], "dependsOn": [], "status": "running"}]
    task = new_task({"id": "w1.1", "wsId": "w1", "team": "research", "title": "Analisi", "description": "d", "acceptance": [], "outputs": [], "dependsOn": []})
    run.data["tasks"] = [task]
    real = run.chat
    seen = []

    async def chat(**kw):
        if kw.get("role") != "research" or not kw["messages"][0]["content"].startswith("[[role:tasker"):
            return await real(**kw)
        seen.append([m["content"] for m in kw["messages"] if m["role"] == "user"])
        if len(seen) == 1:
            run.add_interaction(task, "user", "Aggiungi i prezzi della concorrenza")  # arrives during the finish
        return {"text": json.dumps({"thought": "done", "tool": "finish", "args": {"summary": f"round {len(seen)}", "files": []}}), "target": "mock/mock-research", "profile": {"key": "mock/mock-research", "compact": False, "tier": "smart"}}

    monkeypatch.setattr(run, "chat", chat)
    agent = next(a for a in ctx.team.list() if a["team"] == "research" and a["kind"] == "worker")
    await asyncio.wait_for(run.run_task(task, agent), timeout=30)
    assert task["status"] == "done" and task["summary"] == "round 2"
    assert len(task["verdicts"]) == 1  # read before QA: round 1 never went to review
    assert any(c.startswith("MESSAGE FROM THE OWNER about this task: Aggiungi i prezzi della concorrenza") for c in seen[1])
