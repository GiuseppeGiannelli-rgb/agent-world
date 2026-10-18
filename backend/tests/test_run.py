"""Contract tests for backend/run.py, ported from server/engine/run.js.

Two levels: unit tests with a minimal fake ctx, and end-to-end demo runs
with the real mock router (no network, no keys), real Team/Brain/Store and
a tmp workspace -- the same path the app exercises in demo mode."""

import asyncio
import json
import shutil
import types
from pathlib import Path

import pytest

from backend.brain import Brain
from backend.bus import Bus
from backend.config import Config
from backend.media import Media
from backend.router.index import Router
from backend.store import Store
from backend.team import Team

REPO_ROOT = Path(__file__).resolve().parents[2]


def mini_ctx(tmp_path):
    """The smallest ctx that lets a Run exist: no real router/team."""
    cfg = {
        "limits": {"approvePlan": False, "maxParallel": 8, "maxSteps": 4, "maxRevisions": 3, "escalateAfter": 2, "maxWorkstreams": 8, "maxSubtasks": 5, "askUserTimeoutMs": 300000, "commandTimeoutMs": 60000},
        "pacing": {"fetchMs": 0, "pickupMs": 0, "reviewWalkMs": 0, "verdictMs": 0, "deliverMs": 0},
        "router": {"escalationCombo": "frontier"},
        "combos": {},
        "teams": {},
    }
    bus = Bus()
    store = Store(tmp_path / "data")
    ctx = types.SimpleNamespace(
        config=types.SimpleNamespace(get=lambda: cfg),
        bus=bus,
        store=store,
        router=types.SimpleNamespace(mode=lambda: "demo"),
        workspace_root=str(tmp_path / "workspace"),
    )
    return ctx


@pytest.fixture
def make_run(tmp_path):
    from backend.run import Run

    def factory(goal="Un obiettivo di prova", ctx=None, options=None):
        return Run(goal=goal, ctx=ctx or mini_ctx(tmp_path), options=options or {})

    return factory


class TestLanguage:
    """Spec 06: the run freezes its language at creation."""

    def test_language_option_is_stored(self, make_run):
        assert make_run(options={"language": "en"}).data["language"] == "en"

    def test_no_language_falls_back_to_config_then_none(self, make_run, tmp_path):
        assert make_run().data["language"] is None  # mini ctx has no ui section: legacy rule
        ctx = mini_ctx(tmp_path)
        cfg = ctx.config.get()
        cfg["ui"] = {"language": "en"}
        assert make_run(ctx=ctx).data["language"] == "en"

    def test_unknown_language_is_refused(self, make_run):
        with pytest.raises(ValueError):
            make_run(options={"language": "xx"})


class TestDataShape:
    def test_constructor_mirrors_node(self, make_run, tmp_path):
        run = make_run("Apri un bar sulla luna!")
        d = run.data
        # spec 09 adds "attachments" (the owner's files); the rest is the Node shape
        assert set(d) == {"id", "slug", "goal", "status", "complexity", "paused", "approvePlan", "language", "mode", "createdAt", "finishedAt", "planSummary", "workstreams", "tasks", "messages", "waiting", "attachments", "report", "error", "usage", "workspace"}
        assert d["attachments"] == []
        assert d["status"] == "planning" and d["paused"] is False and d["mode"] == "demo"
        assert len(d["id"]) == 8
        assert d["slug"].startswith("apri-un-bar-sulla-luna-")
        assert d["workspace"] == str(Path(tmp_path / "workspace" / d["slug"]))
        assert d["usage"] == {"calls": 0, "tokensIn": 0, "tokensOut": 0, "escalations": 0, "subAgents": 0}
        assert d["approvePlan"] is False

    def test_approve_plan_option_wins_over_config(self, make_run):
        assert make_run(options={"approvePlan": True}).data["approvePlan"] is True


class TestEventsAndNotes:
    @pytest.mark.asyncio
    async def test_message_caps_at_800_and_truncates(self, make_run):
        run = make_run()
        for i in range(810):
            run.message("a", "b", "chat", f"m{i}")
        assert len(run.data["messages"]) == 800
        assert run.data["messages"][-1]["text"] == "m809"
        run.message("a", "b", "chat", "x" * 5000)
        assert len(run.data["messages"][-1]["text"]) == 4000

    @pytest.mark.asyncio
    async def test_note_caps_history(self, make_run):
        run = make_run()
        task = {"history": []}
        agent = {"id": "nina"}
        for i in range(90):
            run.note(task, agent, "step", f"n{i}")
        assert len(task["history"]) == 80
        assert task["history"][-1]["text"] == "n89"
        assert task["history"][-1]["agentId"] == "nina"

    @pytest.mark.asyncio
    async def test_emit_run_throttles_but_force_is_immediate(self, make_run):
        run = make_run()
        frames = []

        async def collect():
            q, _unsub = run.ctx.bus.subscribe()
            run.emit_run(force=True)
            run.emit_run()
            run.emit_run()
            frames.append((await asyncio.wait_for(q.get(), 1)).count('"type": "run"'))
            await asyncio.sleep(0.35)  # let the debounce fire
            frames.append((await asyncio.wait_for(q.get(), 1)).count('"type": "run"'))

        await collect()
        assert frames == [1, 1]  # one immediate forced frame, one debounced


class TestFlowControl:
    @pytest.mark.asyncio
    async def test_gate_blocks_while_paused_and_resume_wakes(self, make_run):
        run = make_run()
        run.ctx.team = types.SimpleNamespace(set=lambda *a: None, ceo=lambda: {"id": "ada"}, abort_waiters=lambda run_id: None)
        run.pause()
        assert run.data["paused"] is True
        waiter = asyncio.ensure_future(run.gate())
        await asyncio.sleep(0.05)
        assert not waiter.done()
        run.resume()
        await asyncio.wait_for(waiter, 1)
        assert run.data["paused"] is False

    @pytest.mark.asyncio
    async def test_stop_aborts_sleep_and_completes_waiters(self, make_run):
        from backend.run import RunStopped

        run = make_run()
        run.ctx.team = types.SimpleNamespace(set=lambda *a: None, ceo=lambda: {"id": "ada"}, abort_waiters=lambda run_id: None)
        sleeper = asyncio.ensure_future(run.sleep(60000))
        item = run.add_waiting({"kind": "question", "from": "nina", "text": "Scelta?"})
        answer = asyncio.ensure_future(run.wait_answer(item, 0))
        await asyncio.sleep(0.05)
        run.stop()
        with pytest.raises(RunStopped):
            await sleeper
        assert await answer is None
        # stop() resolves the waiter with None, and the done() path marks the
        # item expired -- same as a timeout, exactly like Node
        assert item["status"] == "expired"

    @pytest.mark.asyncio
    async def test_sleep_returns_normally_without_abort(self, make_run):
        run = make_run()
        await run.sleep(1)  # must not raise


class TestSteering:
    @pytest.mark.asyncio
    async def test_scopes_and_dedup_per_agent(self, make_run):
        run = make_run()
        run.steer("all", "per tutti")
        run.steer("team:dev", "per il dev")
        run.steer("agent:nina", "solo nina")
        task = {"team": "dev"}
        nina = {"id": "nina"}
        leo = {"id": "leo"}
        assert run.take_steering(task, nina) == ["per tutti", "per il dev", "solo nina"]
        assert run.take_steering(task, nina) == []  # already seen
        assert run.take_steering(task, leo) == ["per tutti", "per il dev"]
        assert run.take_steering({"team": "research"}, {"id": "sara"}) == ["per tutti"]


class TestWaiting:
    @pytest.mark.asyncio
    async def test_answer_resolves_and_expires(self, make_run):
        run = make_run()
        item = run.add_waiting({"kind": "question", "from": "nina", "text": "Che tono?"})
        waiter = asyncio.ensure_future(run.wait_answer(item, 0))
        await asyncio.sleep(0.02)
        ok = run.answer(item["id"], {"text": "Diretto", "decision": None})
        assert ok is True
        out = await waiter
        assert out["text"] == "Diretto"
        assert item["status"] == "answered"
        assert run.answer(item["id"], {"text": "di nuovo"}) is False  # no longer open

    @pytest.mark.asyncio
    async def test_wait_answer_timeout_expires(self, make_run):
        run = make_run()
        item = run.add_waiting({"kind": "question", "from": "nina", "text": "?"})
        out = await run.wait_answer(item, 30)
        assert out is None and item["status"] == "expired"


class FakeChatRouter:
    def __init__(self, replies):
        self.replies = list(replies)

    async def chat(self, **kwargs):
        return {"text": self.replies.pop(0) if self.replies else "junk", "usage": {"in": 3, "out": 5}, "target": "mock/mock-dev"}


class TestChatHelpers:
    @pytest.mark.asyncio
    async def test_chat_counts_usage_and_sets_model(self, make_run):
        run = make_run()
        run.ctx.router = FakeChatRouter(['{"a": 1}'])
        agent = {"id": "nina"}
        run.ctx.team = types.SimpleNamespace(get=lambda id: agent, set=lambda *a: None)
        res = await run.chat(role="dev", use=None, messages=[], json=True, max_tokens=100, agent=agent, task=None)
        assert res["text"] == '{"a": 1}'
        assert run.data["usage"] == {"calls": 1, "tokensIn": 3, "tokensOut": 5, "escalations": 0, "subAgents": 0}
        assert agent["model"] == "mock/mock-dev"

    @pytest.mark.asyncio
    async def test_chat_json_retries_then_gives_up(self, make_run):
        run = make_run()
        run.ctx.router = FakeChatRouter(["junk1", "junk2"])
        run.ctx.team = types.SimpleNamespace(get=lambda id: None, set=lambda *a: None)
        out = await run.chat_json({"role": "dev", "messages": [], "agent": None}, lambda o: True, tries=2)
        assert out is None
        assert run.data["usage"]["calls"] == 2

    @pytest.mark.asyncio
    async def test_chat_json_returns_validated_object(self, make_run):
        run = make_run()
        run.ctx.router = FakeChatRouter(["junk", '{"ok": true}'])
        run.ctx.team = types.SimpleNamespace(get=lambda id: None, set=lambda *a: None)
        out = await run.chat_json({"role": "dev", "messages": [], "agent": None}, lambda o: o.get("ok"), tries=2)
        assert out == {"ok": True}


class TestRolesOnTheirTier:
    """Spec 08: each kind of call lands on the tier of its role. The team combos
    come from config (CEO and QA frontier, development code...); on top of them a
    lead plans and helps on router.roles.lead, a sub-agent works on
    router.roles.sub, unless it was escalated."""

    @pytest.mark.asyncio
    async def test_leads_plan_on_smart_and_sub_agents_work_on_fast(self, demo_ctx):
        from backend.run import Run

        calls = []
        real = demo_ctx.router.chat

        async def spy(**kw):
            system = next(m["content"] for m in kw["messages"] if m["role"] == "system")
            calls.append({"marker": system.split("]]", 1)[0] + "]]", "role": kw.get("role"), "use": kw.get("use"), "agent": (kw.get("meta") or {}).get("agentId")})
            return await real(**kw)

        demo_ctx.router.chat = spy
        run = Run(goal="The complete launch website for a bakery, with images and a voice-over", ctx=demo_ctx, options={"language": "en"})
        await asyncio.wait_for(run.start(), timeout=120)
        assert run.data["status"] in ("completed", "completed_with_failures"), run.data["error"]
        roles = demo_ctx.config.get()["router"]["roles"]
        kinds = {a["id"]: a["kind"] for a in demo_ctx.team.agents.values()}
        import re

        for c in calls:  # a sub-agent leaves the team when its task is done: its id says what it was
            if c["agent"] and re.search(r"-sub\d+$", c["agent"]):
                kinds[c["agent"]] = "sub"

        leads = [c for c in calls if c["marker"] == "[[role:lead]]"]
        assert leads and all(c["use"] == roles["lead"] for c in leads)
        subs = [c for c in calls if c["marker"].startswith("[[role:tasker") and kinds.get(c["agent"]) == "sub"]
        assert subs, "a complex mission spawns sub-agents"
        assert all(c["use"] in (roles["sub"], "frontier") for c in subs), [c for c in subs if c["use"] not in (roles["sub"], "frontier")]
        workers = [c for c in calls if c["marker"].startswith("[[role:tasker") and kinds.get(c["agent"]) == "worker"]
        assert workers and all(c["use"] in (None, "frontier") for c in workers)  # their team combo, or escalated
        assert all(c["role"] == "qa" for c in calls if c["marker"] == "[[role:judge]]")
        assert all(c["role"] == "ceo" for c in calls if c["marker"] in ("[[role:planner]]", "[[role:synth]]"))


class TestRunMemory:
    """Spec 08: the run memory fills up as the mission goes, and the workers of
    later workstreams (sub-agents included) read what the others delivered."""

    @pytest.mark.asyncio
    async def test_a_demo_mission_fills_the_run_memory_and_shares_it(self, demo_ctx):
        """The worker of a later workstream (a spawned sub-agent included) reads in
        its brief the files the upstream teams delivered, from the run memory."""
        import asyncio

        from backend.run import Run

        briefs = {}
        real = demo_ctx.router.chat

        async def spy(**kw):
            system = kw["messages"][0]["content"]
            if system.startswith("[[role:tasker") and len(kw["messages"]) == 2:
                briefs[(kw.get("meta") or {}).get("taskId")] = kw["messages"][1]["content"]
            return await real(**kw)

        demo_ctx.router.chat = spy
        run = Run(goal="The complete launch website for a bakery, with images and a voice-over", ctx=demo_ctx, options={"language": "en"})
        await asyncio.wait_for(run.start(), timeout=120)
        kinds = {i["kind"] for i in run.memory.items}
        assert {"file", "delivery"} <= kinds
        assert any(i["path"] == "research/notes.md" for i in run.memory.items if i["kind"] == "file")
        dev = [b for t, b in briefs.items() if t and t.startswith(next(w["id"] for w in run.data["workstreams"] if w["team"] == "dev"))]
        assert dev and any("FROM THE TEAM (this run)" in b and "research/notes.md" in b for b in dev)


class TestEmergencyAnswers:
    """Spec 08: when no provider answers in a live run, the router lets the demo
    simulator answer (emergency). The run says so once, in its language, where
    the user reads it, and counts those answers: they are not real work."""

    @pytest.mark.asyncio
    async def test_the_first_emergency_answer_is_announced_once(self, make_run):
        from backend.i18n import tr

        run = make_run()
        run.data["language"] = "fr"

        class EmergencyRouter:
            async def chat(self, **kwargs):
                return {"text": "{}", "usage": {"in": 1, "out": 1}, "target": "mock/mock-dev", "demo": True, "emergency": True, "requested": "frontier", "cascade": ["frontier", "smart"]}

        run.ctx.router = EmergencyRouter()
        run.ctx.team = types.SimpleNamespace(get=lambda id: None, set=lambda *a: None, ceo=lambda: {"id": "ada"})
        for _ in range(3):
            await run.chat(role="dev", messages=[], json=True)
        text = tr("fr", "emergency_answer", cascade="frontier → smart")
        warned = [m for m in run.data["messages"] if m["text"] == text]
        assert len(warned) == 1 and warned[0]["kind"] == "system"  # a kind the panel already labels
        assert run.data["usage"]["emergencies"] == 3


class TestFiles:
    @pytest.mark.asyncio
    async def test_missing_outputs_and_machine_check(self, make_run):
        run = make_run()
        await run.ws.ensure()
        await run.ws.write("a.md", "testo")
        task = {"outputs": ["a.md", "b.md", "empty.md"]}
        await run.ws.write("empty.md", "")
        assert await run.missing_outputs(task) == ["b.md", "empty.md"]
        assert await run.machine_check(task) == ["Missing or empty files: b.md, empty.md"]  # no language: English
        run.data["language"] = "it"
        assert await run.machine_check(task) == ["File mancanti o vuoti: b.md, empty.md"]

    @pytest.mark.asyncio
    async def test_file_dump_marks_missing_and_binary(self, make_run):
        run = make_run()
        await run.ws.ensure()
        await run.ws.write("a.md", "# Titolo")
        await run.ws.write_bytes("img.png", b"\x89PNG")
        task = {"outputs": ["a.md", "img.png", "gone.md"], "files": []}
        dump = await run.file_dump(task)
        assert "=== a.md ===\n# Titolo" in dump
        assert "=== img.png ===\n(binary file, 4 bytes" in dump
        assert "=== gone.md ===\n(missing)" in dump

    @pytest.mark.asyncio
    async def test_progress_text(self, make_run):
        run = make_run()
        run.data["tasks"] = [
            {"id": "w1.1", "team": "dev", "status": "done", "title": "A", "summary": "fatta"},
            {"id": "w1.2", "team": "research", "status": "working", "title": "B", "summary": ""},
        ]
        assert run.progress_text("dev") == "- w1.1 [done] A: fatta"
        assert "w1.2 [working] B" in run.progress_text(None)


# ---------- end-to-end demo run ----------


@pytest.fixture
def demo_ctx(tmp_path, monkeypatch):
    """A full ctx on the repo's own default.json (copied, so the repo is
    never written), in AGENT_WORLD_FAST mode: the mock provider plays every
    role, all pacing is minimal."""
    monkeypatch.setenv("AGENT_WORLD_FAST", "1")
    default = json.loads((REPO_ROOT / "config" / "default.json").read_text(encoding="utf-8"))
    # every key and local server URL the config names (spec 08 added providers): a demo stays a demo
    named = {p[k] for section in (default["providers"], default["media"]["providers"]) for p in section.values() for k in ("keyEnv", "baseUrlEnv") if p.get(k)}
    for var in named:
        monkeypatch.delenv(var, raising=False)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    shutil.copy(REPO_ROOT / "config" / "default.json", config_dir / "default.json")
    config = Config(config_dir)
    cfg = config.get()
    cfg["router"]["logCalls"] = False  # keep call logs out of tmp data
    cfg["providers"]["mock"]["latencyMs"] = [1, 5]
    bus = Bus()
    store = Store(tmp_path / "data")
    router = Router(config, tmp_path / "data", bus)
    team = Team(bus)
    team.load(cfg["staff"])
    brain = Brain(tmp_path / "data" / "brain.json", bus)
    media = Media(config=config, bus=bus)
    skills = types.SimpleNamespace(skills=[], search=lambda *a, **k: [], summary=lambda: {"count": 0, "sources": []})
    ctx = types.SimpleNamespace(config=config, bus=bus, store=store, router=router, team=team, brain=brain, skills=skills, media=media, workspace_root=str(tmp_path / "workspace"))
    return ctx


class TestDemoRun:
    @pytest.mark.asyncio
    async def test_demo_run_completes_end_to_end(self, demo_ctx, tmp_path):
        from backend.run import Run

        run = Run(goal="Una landing page per il bar con immagini", ctx=demo_ctx)
        await asyncio.wait_for(run.start(), timeout=120)
        d = run.data
        assert d["status"] == "completed", f"error={d['error']} ws={[ (w['id'], w['status']) for w in d['workstreams'] ]}"
        assert d["finishedAt"] is not None
        assert all(w["status"] == "done" for w in d["workstreams"])
        assert d["tasks"] and all(t["status"] == "done" for t in d["tasks"])
        assert d["report"].startswith("# Final report")  # default.json: English (N14)
        # the workspace holds the deliverables and the report
        ws_root = Path(d["workspace"])
        assert (ws_root / "REPORT.md").exists()
        listed = await run.ws.list_text()
        assert "index.html" in listed
        assert "assets/hero.png" in listed  # the genai team really generated it (demo PNG)
        # the run was persisted with the Node-compatible shape
        saved = demo_ctx.store.get(d["id"])
        assert saved["status"] == "completed" and saved["goal"] == "Una landing page per il bar con immagini"
        # every agent was released at the end
        assert all(not a["busy"] for a in demo_ctx.team.list())
        # the Brain learned the mission note
        assert any(n["kind"] == "run" for n in demo_ctx.brain.notes)

    @pytest.mark.asyncio
    async def test_approve_plan_parks_until_the_owner_answers(self, demo_ctx):
        from backend.run import Run

        run = Run(goal="Un documento di ricerca", ctx=demo_ctx, options={"approvePlan": True})
        starter = asyncio.ensure_future(run.start())
        for _ in range(500):
            if run.data["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        assert run.data["status"] == "awaiting_approval"
        item = next(w for w in run.data["waiting"] if w["kind"] == "plan" and w["status"] == "open")
        assert run.answer(item["id"], {"text": "", "decision": "approve"}) is True
        await asyncio.wait_for(starter, timeout=120)
        assert run.data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_rejecting_the_plan_stops_the_run(self, demo_ctx):
        from backend.run import Run

        run = Run(goal="Un documento di ricerca", ctx=demo_ctx, options={"approvePlan": True})
        starter = asyncio.ensure_future(run.start())
        for _ in range(500):
            if run.data["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        assert run.data["status"] == "awaiting_approval"
        item = run.data["waiting"][0]
        run.answer(item["id"], {"text": "Non ora", "decision": "reject"})
        await asyncio.wait_for(starter, timeout=30)
        assert run.data["status"] == "stopped"
        assert "Plan rejected" in (run.data["error"] or "")  # default.json: English

    @pytest.mark.asyncio
    async def test_stop_during_planning(self, demo_ctx):
        from backend.run import Run

        run = Run(goal="Una campagna social completa con video e podcast per il lancio", ctx=demo_ctx, options={"approvePlan": True})
        starter = asyncio.ensure_future(run.start())
        for _ in range(500):
            if run.data["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        assert run.data["status"] == "awaiting_approval"
        run.stop()
        await asyncio.wait_for(starter, timeout=30)
        assert run.data["status"] == "stopped"
        assert all(t["status"] == "skipped" for t in run.data["tasks"])
        assert all(w["status"] == "skipped" for w in run.data["workstreams"])


def _strings(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)
    elif isinstance(v, str):
        yield v


def _foreign_fragments(lang: str) -> list[str]:
    """The fixed parts of every text the backend (i18n.MESSAGES) and the demo
    provider (mock_texts.MOCK_TEXTS) write in the OTHER languages: in a run in
    `lang` none of them may reach the UI or the files. A piece that also
    occurs in `lang`'s own texts is skipped (a shared word, a product name),
    and so are short pieces."""
    import re
    import string

    from backend.i18n import MESSAGES
    from backend.router.mock_texts import MOCK_TEXTS

    own = " ".join([*_strings(MESSAGES[lang]), *_strings(MOCK_TEXTS[lang])])
    out = set()
    for other in MOCK_TEXTS:
        if other == lang:
            continue
        for template in [*_strings(MESSAGES[other]), *_strings(MOCK_TEXTS[other])]:
            for literal, *_ in string.Formatter().parse(template):
                for piece in re.split(r"[\n:·()\"«»„“*#|]", literal):
                    piece = piece.strip(" .,;!?¡¿…→-_>")
                    if len(piece) >= 12 and piece not in own:
                        out.add(piece)
    return sorted(out)


GOALS_BY_LANGUAGE = {
    "en": "The complete launch website for a bakery, with images and a voice-over",
    "it": "Il sito completo per il lancio di una panetteria, con immagini e una voce narrante",
    "es": "El sitio web completo para el lanzamiento de una panadería, con imágenes y una voz en off",
    "fr": "Le site web complet pour le lancement d'une boulangerie, avec des images et une voix off",
    "de": "Die komplette Website zum Start einer Bäckerei, mit Bildern und einer Sprecherstimme",
}


class TestDemoRunInEveryLanguage:
    """Spec 06 + N14: a whole demo mission in each language. Every model call
    carries the run's rule, and nothing the backend or the demo provider
    writes (messages, bubbles, timelines, Brain notes, files, report) holds a
    fixed piece of another language. Before N14 the demo provider's words
    had to be cut out first: they were always Italian."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lang", list(GOALS_BY_LANGUAGE))
    async def test_the_whole_mission_speaks_the_run_language(self, demo_ctx, lang):
        from backend.prompts import language_rule
        from backend.router.mock_texts import MOCK_TEXTS
        from backend.run import Run

        calls = []
        real_chat = demo_ctx.router.chat

        async def spy(**kw):
            calls.append(kw["messages"])
            return await real_chat(**kw)

        demo_ctx.router.chat = spy
        bubbles = []
        real_set = demo_ctx.team.set
        demo_ctx.team.set = lambda id, patch: (bubbles.append(patch.get("text") or ""), real_set(id, patch))[1]

        goal = GOALS_BY_LANGUAGE[lang]
        run = Run(goal=goal, ctx=demo_ctx, options={"approvePlan": True, "language": lang})
        starter = asyncio.ensure_future(run.start())
        for _ in range(500):
            if run.data["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        item = next(w for w in run.data["waiting"] if w["kind"] == "plan")
        run.answer(item["id"], {"text": "", "decision": "approve"})
        await asyncio.wait_for(starter, timeout=120)
        d = run.data
        assert d["status"] in ("completed", "completed_with_failures"), d["error"]
        assert d["language"] == lang

        # every model call carries the run's rule in its system prompt
        rule = language_rule(lang)
        assert calls
        for msgs in calls:
            system = next(m["content"] for m in msgs if m["role"] == "system")
            assert rule in system, system[:80]

        # what reaches the UI, and what lands in the project folder
        texts = [m["text"] for m in d["messages"]] + bubbles + [w["text"] for w in d["waiting"]]
        texts += [x.get("error") or "" for x in d["tasks"] + d["workstreams"]]
        texts += [h["text"] for t in d["tasks"] for h in t["history"]]
        texts += [f"{n['title']} {n['text']}" for n in demo_ctx.brain.notes]
        texts += [d["report"], d["planSummary"]] + [f"{w['title']} {w['objective']}" for w in d["workstreams"]]
        files = [p for p in Path(d["workspace"]).rglob("*") if p.suffix in (".md", ".html")]
        texts += [p.read_text(encoding="utf-8") for p in files]
        texts = [t.replace(goal, "") for t in texts]
        fragments = _foreign_fragments(lang)
        assert len(fragments) > 50
        leaks = sorted({f for f in fragments for t in texts if f in t})
        assert not leaks, leaks[:15]
        # and the demo provider's own words are there, in this language
        assert d["report"].startswith(f"# {MOCK_TEXTS[lang]['report']['title']}\n")
        assert f'<html lang="{lang}">' in (Path(d["workspace"]) / "index.html").read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_rejecting_the_plan_in_english(self, demo_ctx):
        from backend.i18n import tr
        from backend.run import Run

        run = Run(goal="A research document", ctx=demo_ctx, options={"approvePlan": True, "language": "en"})
        starter = asyncio.ensure_future(run.start())
        for _ in range(500):
            if run.data["status"] == "awaiting_approval":
                break
            await asyncio.sleep(0.02)
        run.answer(run.data["waiting"][0]["id"], {"text": "Not now", "decision": "reject"})
        await asyncio.wait_for(starter, timeout=30)
        assert run.data["status"] == "stopped"
        assert run.data["error"] == tr("en", "plan_rejected_because", reason="Not now")


class TestTickLaunchesEachTaskOnce:
    """Spec 09 found it: tick() starts a task with ensure_future, and the task
    only leaves "queued" when its coroutine runs. Two ticks in the same turn of
    the loop (two workstreams done preparing at once) started the same task
    twice, with two agents: double work, double calls, double sub-agents."""

    @pytest.mark.asyncio
    async def test_two_ticks_in_a_row_start_a_task_once(self, demo_ctx):
        from backend.plan import new_task
        from backend.run import Run

        run = Run(goal="Un documento per il bar", ctx=demo_ctx)
        run.data["complexity"] = "simple"
        run.data["workstreams"] = [{"id": "w1", "team": "research", "title": "t", "objective": "o", "deliverables": [], "acceptance": [], "dependsOn": [], "status": "running"}]
        run.data["tasks"] = [new_task({"id": f"w1.{i}", "wsId": "w1", "team": "research", "title": f"t{i}", "description": "d", "acceptance": [], "outputs": [], "dependsOn": []}) for i in (1, 2)]
        started = []

        async def run_task(task, agent):
            started.append(task["id"])
            await asyncio.sleep(0.05)
            task["status"] = "done"

        run.run_task = run_task
        run._finish_schedule = asyncio.Event()
        run.tick()
        run.tick()  # before the first tick's coroutines had a chance to run
        await asyncio.sleep(0.2)
        assert sorted(started) == ["w1.1", "w1.2"]
