"""Spec 09 §4: after the site is built (or half-way through), the owner says
"I don't like this section: use this photo instead and change the title".

POST /api/runs/{id}/refine {text, attachments} works on a live or a stored
run. The CEO names the tasks the change touches (a model that names tasks
that do not exist, or answers no JSON, falls back to the task that owns the
page, then to the last one done). Those tasks go back in the queue with the
directive and the files; their workers redo the part, QA reviews it again,
the report is written again, and the run ends completed again -- as many
rounds as the owner wants (run.refinements keeps them)."""

import asyncio
from pathlib import Path

import pytest

from test_attachments import app, client, ctx, jpeg  # noqa: F401 -- fixtures
from test_resume import until

LANDING = "Una landing page per il bar con immagini"


async def finished_run(c, app, goal=LANDING):
    rid = (await c.post("/api/runs", json={"goal": goal})).json()["id"]
    await until(lambda: not app.state.live, timeout=120)
    return rid


@pytest.mark.asyncio
async def test_a_change_after_the_end_redoes_the_page_and_qa_reviews_it_again(app, ctx):  # noqa: F811
    async with client(app) as c:
        rid = await finished_run(c, app)
        d = ctx.store.get(rid)
        assert d["status"] == "completed"
        page_task = next(t for t in d["tasks"] if "index.html" in t["files"])
        before = (page_task["attempts"], len(page_task["verdicts"]), d["finishedAt"])
        up = (await c.post(f"/api/runs/{rid}/attachments", params={"name": "nuova-hero.jpg"}, content=jpeg(1600, 900))).json()
        res = await c.post(f"/api/runs/{rid}/refine", json={"text": "Non mi piace la hero: usa questa foto al suo posto", "attachments": [up["id"]]})
        assert res.status_code == 200, res.text
        body = res.json()
        assert page_task["id"] in [t["taskId"] for t in body["targets"]] and body["resumed"] is True
        await until(lambda: not app.state.live, timeout=120)
    e = ctx.store.get(rid)
    assert e["status"] == "completed", e["error"]
    t = next(x for x in e["tasks"] if x["id"] == page_task["id"])
    assert t["attempts"] > before[0] and len(t["verdicts"]) > before[1]  # redone, and reviewed again
    assert e["finishedAt"] != before[2] and e["report"]
    page = (Path(e["workspace"]) / "index.html").read_text(encoding="utf-8")
    steps = [(h.get("tool"), h.get("target")) for h in t["history"] if h["kind"] == "step"][-7:]
    assert 'src="assets/hero-owner.jpg"' in page, steps  # the owner's photo, in place of the generated one
    assert e["refinements"][-1]["text"].startswith("Non mi piace la hero") and e["refinements"][-1]["targets"] == [x["taskId"] for x in body["targets"]]
    assert any(i["from"] == "user" and i["text"].startswith("Non mi piace la hero") for i in t["interactions"])


@pytest.mark.asyncio
async def test_round_after_round(app, ctx):  # noqa: F811
    async with client(app) as c:
        rid = await finished_run(c, app)
        for text in ("Testi più brevi nella pagina", "Ora un tono più caldo nella pagina"):
            assert (await c.post(f"/api/runs/{rid}/refine", json={"text": text})).status_code == 200
            await until(lambda: not app.state.live, timeout=120)
            assert ctx.store.get(rid)["status"] == "completed"
    assert [r["text"] for r in ctx.store.get(rid)["refinements"]] == ["Testi più brevi nella pagina", "Ora un tono più caldo nella pagina"]


@pytest.mark.asyncio
async def test_the_targets_come_from_the_ceo_and_are_checked(ctx, monkeypatch):  # noqa: F811
    from backend.plan import new_task
    from backend.run import Run

    run = Run(goal=LANDING, ctx=ctx)
    run.data["status"] = "completed"
    run.data["workstreams"] = [{"id": "w1", "team": "content", "title": "Testi", "objective": "o", "deliverables": [], "acceptance": [], "dependsOn": [], "status": "done"},
                               {"id": "w2", "team": "dev", "title": "Pagina", "objective": "o", "deliverables": [], "acceptance": [], "dependsOn": ["w1"], "status": "done"}]
    run.data["tasks"] = [new_task({"id": "w1.1", "wsId": "w1", "team": "content", "title": "Testi della pagina", "description": "d", "acceptance": [], "outputs": ["content/copy.md"], "dependsOn": [], "status": "done", "files": ["content/copy.md"]}),
                         new_task({"id": "w2.1", "wsId": "w2", "team": "dev", "title": "Pagina", "description": "d", "acceptance": [], "outputs": ["index.html"], "dependsOn": [], "status": "done", "files": ["index.html"]})]

    async def ceo_says(opts, validate=None, tries=2):
        return {"targets": [{"taskId": "w9.9", "instruction": "x"}, {"taskId": "w1.1", "instruction": "Accorcia i testi"}]}

    monkeypatch.setattr(run, "chat_json", ceo_says)
    targets = await run.refine_targets("Accorcia i testi", [])
    assert targets == [{"taskId": "w1.1", "instruction": "Accorcia i testi"}]  # an id that does not exist is dropped

    async def ceo_mute(opts, validate=None, tries=2):
        return None

    monkeypatch.setattr(run, "chat_json", ceo_mute)
    assert [t["taskId"] for t in await run.refine_targets("Qualcosa non va", [])] == ["w2.1"]  # the page's owner


@pytest.mark.asyncio
async def test_refine_checks_its_input(app, ctx):  # noqa: F811
    async with client(app) as c:
        rid = await finished_run(c, app)
        assert (await c.post(f"/api/runs/{rid}/refine", json={"text": ""})).status_code == 400
        assert (await c.post(f"/api/runs/{rid}/refine", json={"text": "x", "attachments": ["zzz"]})).status_code == 400
        assert (await c.post("/api/runs/nope/refine", json={"text": "x"})).status_code == 404


@pytest.mark.asyncio
async def test_a_change_during_a_live_run_reopens_a_done_task(app, ctx):  # noqa: F811
    async with client(app) as c:
        rid = (await c.post("/api/runs", json={"goal": "Un documento di analisi per il bar"})).json()["id"]
        run = app.state.live[rid]
        await until(lambda: any(t["status"] == "done" and t["team"] == "research" for t in run.data["tasks"]))
        research = next(t for t in run.data["tasks"] if t["team"] == "research")
        attempts = research["attempts"]
        res = await c.post(f"/api/runs/{rid}/refine", json={"text": f"Nella parte '{research['title']}' aggiungi i prezzi della concorrenza"})
        if res.status_code == 409:  # the run reached its report first: then it is a stored run, and resumes
            pytest.skip("the demo was faster than the request")
        assert res.status_code == 200 and research["id"] in [t["taskId"] for t in res.json()["targets"]]
        await until(lambda: not app.state.live, timeout=120)
    e = ctx.store.get(rid)
    assert e["status"] == "completed"
    assert next(t for t in e["tasks"] if t["id"] == research["id"])["attempts"] > attempts


@pytest.mark.asyncio
async def test_the_box_of_a_done_task_changes_that_task(app, ctx):  # noqa: F811
    """From a delivered task's own box the change goes to that task, not to the CEO's pick."""
    async with client(app) as c:
        rid = await finished_run(c, app, goal="Un documento di analisi per il bar")
        d = ctx.store.get(rid)
        first = d["tasks"][0]
        res = await c.post(f"/api/runs/{rid}/refine", json={"text": "Aggiungi una sezione sui prezzi", "taskId": first["id"]})
        assert res.status_code == 200 and [t["taskId"] for t in res.json()["targets"]] == [first["id"]]
        await until(lambda: not app.state.live, timeout=120)
        assert (await c.post(f"/api/runs/{rid}/refine", json={"text": "x", "taskId": "w9.9"})).status_code == 404
    assert ctx.store.get(rid)["status"] == "completed"
