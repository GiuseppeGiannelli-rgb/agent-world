"""Spec 09 §3.2-3.3: the agents use the owner's files instead of generating
them, and understand what is in them.

- use_attachment puts an owner's file where the plan expects it. It keeps its
  real format (a .jpg asked as assets/hero.png is saved as assets/hero.jpg) and
  counts as the expected file: missing_outputs accepts a sibling with another
  image or audio extension, and the task delivers the real path, so the next
  workstream (the site) links the file that exists.
- read_document gives the text of a PDF, DOCX, CSV or text file (with a query,
  only the passages that match); inspect_image asks a vision model what a
  photo shows, or describes it from its header when no vision model answers.
- Every brief lists the owner's files (and the CEO's and the lead's), the
  tools appear only in a run that has them, and QA takes them as valid.
- The demo simulator plays it all: with owner photos the AI Generativa team
  copies them instead of calling generate_image, and the page shows them."""

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from test_attachments import SVG, ctx, docx, jpeg, pdf, png, wav  # noqa: F401 -- the ctx fixture too

# ---------- prompts ----------


def _cfg():
    cfg = json.loads((Path(__file__).resolve().parents[2] / "config" / "default.json").read_text(encoding="utf-8"))
    cfg["limits"]["allowShell"] = False
    return cfg


def test_the_owner_tools_appear_only_with_owner_files():
    from backend.prompts import OWNER_TOOLS, tools_for

    cfg = _cfg()
    assert OWNER_TOOLS == ["use_attachment", "read_document", "inspect_image"]
    assert not set(OWNER_TOOLS) & set(tools_for(cfg, "genai"))
    with_files = tools_for(cfg, "genai", owner_files=True)
    assert with_files[:6] == ["list_files", "read_file", "write_file", "generate_image", "generate_speech", "use_attachment"]
    assert with_files[-1] == "finish" and set(OWNER_TOOLS) <= set(with_files)


def test_the_brief_lists_the_owner_files():
    from backend.prompts import tasker_brief

    ws = {"title": "Immagini", "objective": "o"}
    task = {"id": "w4.1", "team": "genai", "title": "Hero", "description": "d", "acceptance": [], "outputs": ["assets/hero.png"], "skills": []}
    brief = tasker_brief(goal="g", ws=ws, task=task, inputs=[], files="", memory="", owner_files="- attachments/foto.jpg (image jpeg 1600x900, landscape 16:9): la facciata")
    assert "FILES FROM THE OWNER" in brief and "- attachments/foto.jpg (image jpeg 1600x900" in brief
    assert brief.index("FILES FROM THE OWNER") < brief.index("PROJECT FILES:")
    assert "FILES FROM THE OWNER" not in tasker_brief(goal="g", ws=ws, task=task, inputs=[], files="", memory="")


def test_the_ceo_and_the_lead_plan_with_the_owner_files():
    from backend.prompts import ceo_plan_prompt, lead_plan_prompt

    cfg = _cfg()
    ceo = ceo_plan_prompt(cfg=cfg, ceo={"name": "Ada"}, goal="Il sito della pizzeria", memory="", owner_files="- attachments/menu.pdf (document pdf)")
    assert "OWNER FILES" in ceo[1]["content"] and "attachments/menu.pdf" in ceo[1]["content"]
    ws = {"id": "w4", "title": "Immagini", "objective": "o", "deliverables": ["assets/hero.png"], "acceptance": []}
    lead = lead_plan_prompt(cfg=cfg, lead={"name": "Luna"}, team="genai", goal="g", ws=ws, upstream=[], owner_files="- attachments/foto.jpg (image)")
    assert "OWNER FILES" in lead[1]["content"]


def test_qa_takes_the_owner_files_as_valid():
    from backend.prompts import judge_prompt

    msgs = judge_prompt(judge={"name": "Bruno"}, goal="g", task={"id": "w4.1", "team": "genai", "title": "t", "description": "d", "acceptance": []}, attempt=1, summary="", file_dump="", checks="", security=False)
    assert "provided by the owner" in msgs[0]["content"] and "never ask to regenerate" in msgs[0]["content"]


# ---------- the tools ----------


@pytest.fixture
def run(ctx):  # noqa: F811
    from backend.plan import new_task
    from backend.run import Run

    r = Run(goal="Il sito della pizzeria", ctx=ctx)
    r.data["workstreams"] = [{"id": "w4", "title": "Immagini", "objective": "o", "team": "genai", "deliverables": [], "acceptance": [], "dependsOn": [], "status": "running"}]
    r.data["tasks"] = [new_task({"id": "w4.1", "wsId": "w4", "team": "genai", "title": "Hero e galleria", "description": "d", "acceptance": [], "outputs": ["assets/hero.png", "audio/spot.mp3"], "dependsOn": []})]
    return r


def agent(ctx):  # noqa: F811
    return ctx.team.get("luna") or next(a for a in ctx.team.list() if a["team"] == "genai")


async def tool(run, name, **args):
    return await run.exec_tool(run.data["tasks"][0], agent(run.ctx), {"thought": "", "tool": name, "args": args})


@pytest.mark.asyncio
async def test_use_attachment_keeps_the_real_format_and_counts_as_the_expected_file(run):
    await run.add_attachment("Facciata.JPG", jpeg(1600, 900))
    task = run.data["tasks"][0]
    assert await run.missing_outputs(task) == ["assets/hero.png", "audio/spot.mp3"]
    out = await tool(run, "use_attachment", **{"from": "attachments/facciata.jpg", "path": "assets/hero.png"})
    assert "assets/hero.jpg" in out and "ERROR" not in out
    assert (Path(run.data["workspace"]) / "assets" / "hero.jpg").read_bytes()[:3] == b"\xff\xd8\xff"
    assert await run.missing_outputs(task) == ["audio/spot.mp3"]  # a .jpg is the expected image
    assert run.data["ownerFiles"]["assets/hero.jpg"] == "attachments/facciata.jpg"
    assert run.delivered_paths(["assets/hero.png", "audio/spot.mp3"]) == ["assets/hero.jpg", "audio/spot.mp3"]


@pytest.mark.asyncio
async def test_use_attachment_takes_a_bare_name_and_checks_everything(run):
    await run.add_attachment("voce.wav", wav())
    assert "audio/spot.wav" in await tool(run, "use_attachment", **{"from": "voce.wav", "path": "audio/spot.mp3"})
    assert (await tool(run, "use_attachment", **{"from": "attachments/nope.jpg", "path": "assets/x.jpg"})).startswith("ERROR")
    assert "cannot become assets/hero.png" in await tool(run, "use_attachment", **{"from": "attachments/voce.wav", "path": "assets/hero.png"})  # audio is not an image
    assert (await tool(run, "use_attachment", **{"from": "attachments/voce.wav", "path": "../../outside.wav"})).startswith("ERROR")
    assert (await tool(run, "use_attachment", **{"from": "../../../etc/passwd", "path": "a.txt"})).startswith("ERROR")


@pytest.mark.asyncio
async def test_read_document_gives_the_text_or_the_passages(run):
    await run.add_attachment("menu.pdf", pdf())
    await run.add_attachment("testi.docx", docx(["Chi siamo: dal 1980 a Napoli", "Orari: 19-23"]))
    whole = await tool(run, "read_document", path="attachments/menu.pdf")
    assert "Margherita 7 euro" in whole
    passages = await tool(run, "read_document", path="attachments/testi.docx", query="orari di apertura")
    assert "Orari: 19-23" in passages
    assert (await tool(run, "read_document", path="attachments/none.pdf")).startswith("ERROR")


@pytest.mark.asyncio
async def test_inspect_image_in_a_demo_run_describes_and_remembers(run):
    rec = await run.add_attachment("facciata.jpg", jpeg(1600, 900))
    out = await tool(run, "inspect_image", path="attachments/facciata.jpg")
    assert "1600" in out and "900" in out
    assert rec["summary"] and rec["summary"] in out
    assert any(h["path"] == "attachments/facciata.jpg" for h in run.memory.search("facciata foto orizzontale", 3, kinds=("attachment",)))


@pytest.mark.asyncio
async def test_inspect_image_falls_back_to_the_header_without_a_vision_model(run, monkeypatch):
    from backend.router.providers import ProviderError

    async def no_vision(**kw):
        raise ProviderError('No provider with a key in "vision"')

    monkeypatch.setattr(run.ctx.router, "chat", no_vision)
    await run.add_attachment("logo.png", png(512, 512))
    out = await tool(run, "inspect_image", path="attachments/logo.png")
    assert "512x512" in out and "square" in out and "no vision model" in out


@pytest.mark.asyncio
async def test_inspect_image_sends_the_image_to_a_vision_model(run, monkeypatch):
    seen = {}

    async def vision(**kw):
        seen.update(kw)
        return {"text": "A wood-fired oven, warm orange light, the pizzaiolo on the left.", "target": "gemini/gemini-2.5-flash", "usage": {"in": 900, "out": 20}}

    monkeypatch.setattr(run.ctx.router, "chat", vision)
    await run.add_attachment("forno.jpg", jpeg(1200, 800))
    out = await tool(run, "inspect_image", path="attachments/forno.jpg", question="what is the mood?")
    assert "wood-fired oven" in out
    assert seen["use"] == "vision" and seen["cascade"] is False
    parts = seen["messages"][1]["content"]
    image = next(p for p in parts if p["type"] == "image_url")["image_url"]["url"]
    assert image.startswith("data:image/jpeg;base64,") and base64.b64decode(image.split(",", 1)[1])[:3] == b"\xff\xd8\xff"
    assert "what is the mood?" in next(p for p in parts if p["type"] == "text")["text"]


@pytest.mark.asyncio
async def test_an_svg_is_never_sent_to_a_vision_model(run, monkeypatch):
    async def vision(**kw):
        raise AssertionError("an SVG went to the vision model")

    monkeypatch.setattr(run.ctx.router, "chat", vision)
    await run.add_attachment("logo.svg", SVG)
    out = await tool(run, "inspect_image", path="attachments/logo.svg")
    assert "300x150" in out and "#c0392b" in out


@pytest.mark.asyncio
async def test_qa_sees_which_files_come_from_the_owner(run):
    await run.add_attachment("facciata.jpg", jpeg(1600, 900))
    await tool(run, "use_attachment", **{"from": "attachments/facciata.jpg", "path": "assets/hero.png"})
    task = run.data["tasks"][0]
    task["files"] = run.delivered_paths(task["outputs"])
    dump = await run.file_dump(task)
    assert "=== assets/hero.jpg ===" in dump and "provided by the owner" in dump and "1600x900" in dump


# ---------- end to end, in the demo ----------


@pytest.mark.asyncio
async def test_with_owner_photos_the_images_are_theirs_and_the_site_shows_them(ctx, monkeypatch):  # noqa: F811
    """No image API at all (generate_image would fail): the owner's two photos
    become the hero and the gallery, QA passes them, and the site links them."""
    from backend.run import Run

    generated = []

    async def no_credit(*a, **k):  # exec_tool turns an exception into "ERROR: ...": count the calls instead
        generated.append(a)
        raise RuntimeError("no credit for images")

    monkeypatch.setattr(ctx.media, "image", no_credit)
    run = Run(goal="Il sito completo della pizzeria con foto e galleria", ctx=ctx)
    await run.add_attachment("facciata.jpg", jpeg(1600, 900), announce=False)
    await run.add_attachment("forno.jpg", jpeg(1200, 800), announce=False)
    await asyncio.wait_for(run.start(), timeout=120)
    d = run.data
    assert d["status"] == "completed", (d["error"], [(t["id"], t["status"], t["error"]) for t in d["tasks"]])
    genai = [t for t in d["tasks"] if t["team"] == "genai"]
    assert genai and all(t["status"] == "done" for t in genai)
    used = [h for t in genai for h in t["history"] if h.get("tool") == "use_attachment"]
    assert len(used) >= 2
    delivered = {f for t in genai for f in t["files"]}
    assert {"assets/hero.jpg", "assets/gallery-1.jpg"} <= delivered
    page = (Path(d["workspace"]) / "index.html").read_text(encoding="utf-8")
    assert 'src="assets/hero.jpg"' in page and 'src="assets/gallery-1.jpg"' in page
    assert generated == []  # the image API was never needed


@pytest.mark.asyncio
async def test_files_given_while_a_worker_works_reach_it_at_the_next_step(run, monkeypatch):
    """The box of a blocked task: the file arrives mid-task, the worker gets it
    (and the tools for it) before its next step."""
    from backend.tasker import Tasker

    task = run.data["tasks"][0]
    sent = []
    steps = iter([
        {"thought": "look", "tool": "list_files", "args": {}},
        {"thought": "use it", "tool": "use_attachment", "args": {"from": "attachments/facciata.jpg", "path": "assets/hero.png"}},
        {"thought": "done", "tool": "finish", "args": {"summary": "s", "files": []}},
    ])

    async def chat(**kw):
        sent.append([dict(m) for m in kw["messages"]])
        if len(sent) == 1:
            await run.add_attachment("facciata.jpg", jpeg(1600, 900), task_id=task["id"], note="la hero")
        return {"text": json.dumps(next(steps)), "target": "mock/mock-genai", "profile": {"key": "mock/mock-genai", "compact": False, "tier": "smart"}}

    monkeypatch.setattr(run, "chat", chat)
    task["outputs"] = ["assets/hero.png"]
    t = Tasker(run, task, agent(run.ctx))
    assert "use_attachment" not in t.tools
    out = await t.work()
    assert out["summary"] == "s"
    note = next(m["content"] for m in sent[1] if m["role"] == "user" and m["content"].startswith("FILES FROM THE OWNER (just added"))
    assert "- attachments/facciata.jpg (image jpeg 1600x900" in note and ": la hero" in note and "use_attachment {" in note
    assert "use_attachment" in t.tools
    assert (Path(run.data["workspace"]) / "assets" / "hero.jpg").exists()
