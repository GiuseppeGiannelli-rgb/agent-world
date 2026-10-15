"""Routes for the run lifecycle, agent chat and media status -- the last
handlers of server/index.js (P5). A FakeRun stands in for the orchestrator so
the wiring is tested without running a real mission; the real end-to-end run
over HTTP is covered by the demo suite in test_run.py."""

import asyncio

import httpx
import pytest

from backend.app import ROOT, create_app
from backend.brain import Brain
from backend.config import Config
from backend.store import Store


class FakeRun:
    """Same surface the routes use: data, emit_run, start, steer, message,
    task_by_id, progress_text, pause, resume, stop, answer."""

    auto_finish = True  # when False, start() blocks until finish() is called

    def __init__(self, *, goal, ctx, options=None):
        self.ctx = ctx
        self.options = options
        self.data = {
            "id": f"fake{len(self.instances)}",
            "goal": goal,
            "status": "planning",
            "paused": False,
            "workspace": str(ctx.workspace_root),
            "tasks": [],
        }
        self.instances.append(self)
        self.steered = []
        self.messages = []
        self.answers = {}
        self._finish = asyncio.Event()
        if FakeRun.auto_finish:
            self._finish.set()

    instances = []

    async def start(self):
        await self._finish.wait()
        self.data["status"] = "completed"

    def emit_run(self, force=False):
        pass

    def steer(self, scope, text):
        self.steered.append((scope, text))

    def message(self, from_, to, kind, text):
        self.messages.append((from_, to, kind, text))

    def task_by_id(self, id):
        return None

    def progress_text(self, team=None):
        return "0/0 task"

    def pause(self):
        self.data["paused"] = True

    def resume(self):
        self.data["paused"] = False

    def stop(self):
        self.data["status"] = "stopped"
        self._finish.set()

    def answer(self, id, answer):
        return self.answers.pop(id, None) is not None


@pytest.fixture
def app_and_store(tmp_path, monkeypatch):
    FakeRun.instances = []
    FakeRun.auto_finish = True
    monkeypatch.setattr("backend.routes.runs.Run", FakeRun)
    store = Store(tmp_path)
    config = Config(ROOT / "config")
    app = create_app(config=config, store=store, brain=Brain(tmp_path / "brain.json"))
    return app, store, config


@pytest.fixture
def client(app_and_store):
    app, _, _ = app_and_store
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ---------- POST /api/runs ----------


async def test_create_run_validates_goal(client):
    async with client as c:
        res = await c.post("/api/runs", json={"goal": "ab"})
        assert res.status_code == 400
        assert res.json()["error"] == "Scrivi un obiettivo per la squadra."
        res = await c.post("/api/runs", json={})
        assert res.status_code == 400


async def test_create_run_starts_and_finishes(client, app_and_store):
    app, _, _ = app_and_store
    async with client as c:
        res = await c.post("/api/runs", json={"goal": "Un sito per il bar"})
        assert res.status_code == 201
        run_id = res.json()["id"]
        assert run_id in app.state.live
        await asyncio.sleep(0.05)  # lets the background start() task complete
        assert run_id not in app.state.live  # finally-branch removed it
        assert FakeRun.instances[0].data["status"] == "completed"


async def test_create_run_conflict_while_active(client, app_and_store):
    FakeRun.auto_finish = False
    async with client as c:
        res = await c.post("/api/runs", json={"goal": "Primo run"})
        assert res.status_code == 201
        res = await c.post("/api/runs", json={"goal": "Secondo run"})
        assert res.status_code == 409
        assert res.json()["error"] == "La squadra sta già lavorando a un run. Fermalo o aspetta che finisca."
        FakeRun.instances[0].stop()  # unblock start() so the task can finish
        await asyncio.sleep(0.05)


async def test_create_run_passes_approve_plan_option(client, app_and_store):
    _, _, config = app_and_store
    async with client as c:
        await c.post("/api/runs", json={"goal": "Con approvazione", "approvePlan": True})
        assert FakeRun.instances[0].options == {"approvePlan": True, "language": config.get()["ui"]["language"]}


# ---------- spec 06: language ----------


async def test_create_run_passes_the_language(client):
    async with client as c:
        res = await c.post("/api/runs", json={"goal": "A site for my bar", "language": "en"})
        assert res.status_code == 201
        assert FakeRun.instances[0].options["language"] == "en"


@pytest.mark.parametrize("body", [{}, {"language": None}])
async def test_create_run_defaults_to_the_configured_language(client, app_and_store, body):
    _, _, config = app_and_store
    async with client as c:
        res = await c.post("/api/runs", json={"goal": "Un sito per il bar", **body})
        assert res.status_code == 201
        assert FakeRun.instances[0].options["language"] == config.get()["ui"]["language"]


@pytest.mark.parametrize("bad", ["fr", "", 3, ["en"]])
async def test_create_run_rejects_an_unknown_language(client, bad):
    async with client as c:
        res = await c.post("/api/runs", json={"goal": "Un sito per il bar", "language": bad})
        assert res.status_code == 400
        assert res.json()["error"].startswith("Lingua non supportata")  # N13: HTTP errors stay Italian
        assert FakeRun.instances == []


async def test_chat_uses_the_language_of_the_active_run(client, app_and_store, monkeypatch):
    import backend.routes.runs as runs_mod

    seen = []
    real = runs_mod.chat_prompt
    monkeypatch.setattr(runs_mod, "chat_prompt", lambda **kw: seen.append(kw.get("language")) or real(**kw))
    FakeRun.auto_finish = False
    async with client as c:
        await c.post("/api/runs", json={"goal": "A site for my bar", "language": "en"})
        FakeRun.instances[0].data["language"] = "en"
        await c.post("/api/chat/ada", json={"text": "How is it going?"})
        assert seen == ["en"]
        FakeRun.instances[0].stop()
        await asyncio.sleep(0.05)


async def test_chat_without_a_run_uses_the_configured_language(client, app_and_store, monkeypatch):
    import backend.routes.runs as runs_mod

    _, _, config = app_and_store
    seen = []
    real = runs_mod.chat_prompt
    monkeypatch.setattr(runs_mod, "chat_prompt", lambda **kw: seen.append(kw.get("language")) or real(**kw))
    async with client as c:
        await c.post("/api/chat/ada", json={"text": "Come va?"})
    assert seen == [config.get()["ui"]["language"]]


# ---------- GET /api/runs/{id} and actions ----------


async def test_get_run_prefers_live_over_store(client, app_and_store):
    app, store, _ = app_and_store
    store.save({"id": "r1", "goal": "vecchio", "status": "completed", "tasks": []}, immediate=True)
    fake = FakeRun(goal="Vivo", ctx=app.state.ctx)
    fake.data["id"] = "r1"
    fake.data["status"] = "running"
    app.state.live["r1"] = fake
    async with client as c:
        res = await c.get("/api/runs/r1")
        assert res.status_code == 200
        assert res.json()["status"] == "running"  # live data, not the stored copy
    app.state.live.clear()


async def test_actions_require_an_active_run(client, app_and_store):
    _, store, _ = app_and_store
    store.save({"id": "r1", "goal": "finito", "status": "completed", "tasks": []}, immediate=True)
    async with client as c:
        for action in ("pause", "resume", "stop", "answer"):
            res = await c.post(f"/api/runs/r1/{action}", json={})
            assert res.status_code == 409
            assert res.json()["error"] == "Questo run non è attivo"


async def test_pause_resume_stop_delegate(client, app_and_store):
    app, _, _ = app_and_store
    fake = FakeRun(goal="Vivo", ctx=app.state.ctx)
    app.state.live[fake.data["id"]] = fake
    async with client as c:
        res = await c.post(f"/api/runs/{fake.data['id']}/pause")
        assert res.json() == {"ok": True}
        assert fake.data["paused"] is True
        await c.post(f"/api/runs/{fake.data['id']}/resume")
        assert fake.data["paused"] is False
        await c.post(f"/api/runs/{fake.data['id']}/stop")
        assert fake.data["status"] == "stopped"
    app.state.live.clear()


async def test_answer_route_validates_and_delegates(client, app_and_store):
    app, _, _ = app_and_store
    captured = {}

    class AnsweringRun(FakeRun):
        def answer(self, id, answer):
            captured["call"] = (id, answer)
            return id == "w1"

    fake = AnsweringRun(goal="Vivo", ctx=app.state.ctx)
    app.state.live[fake.data["id"]] = fake
    async with client as c:
        res = await c.post(f"/api/runs/{fake.data['id']}/answer", json={"itemId": "w1", "text": "Va bene", "decision": "approve"})
        assert res.json() == {"ok": True}
        assert captured["call"] == ("w1", {"text": "Va bene", "decision": "approve"})
        # an unknown decision value degrades to None, exactly like Node
        await c.post(f"/api/runs/{fake.data['id']}/answer", json={"itemId": "w1", "decision": "bogus"})
        assert captured["call"][1]["decision"] is None
        res = await c.post(f"/api/runs/{fake.data['id']}/answer", json={"itemId": "gone"})
        assert res.status_code == 409
        assert res.json()["error"] == "Questa richiesta non è più aperta"
    app.state.live.clear()


# ---------- files ----------


async def test_files_and_file_routes(client, app_and_store, tmp_path):
    _, store, _ = app_and_store
    ws = tmp_path / "ws-r2"
    (ws / "assets").mkdir(parents=True)
    (ws / "index.html").write_text("<h1>bar</h1>", encoding="utf-8")
    # Node's Workspace.list queues directories but only ever pushes FILES,
    # so the fixture puts a real file inside assets/.
    (ws / "assets" / "hero.png").write_bytes(b"png")
    store.save({"id": "r2", "goal": "file", "status": "completed", "tasks": [], "workspace": str(ws)}, immediate=True)
    async with client as c:
        res = await c.get("/api/runs/r2/files")
        assert res.status_code == 200
        paths = [f["path"] for f in res.json()]
        assert "index.html" in paths and any(p.startswith("assets") for p in paths)
        res = await c.get("/api/runs/r2/file", params={"path": "index.html"})
        assert res.status_code == 200
        assert res.json() == {"path": "index.html", "content": "<h1>bar</h1>"}
        res = await c.get("/api/runs/r2/file", params={"path": "manca.txt"})
        assert res.status_code == 404
        assert res.json()["error"]


# ---------- chat ----------


async def test_chat_unknown_agent_and_empty_text(client):
    async with client as c:
        res = await c.post("/api/chat/nobody", json={"text": "ciao"})
        assert res.status_code == 404
        assert res.json()["error"] == "Agente non trovato"
        res = await c.post("/api/chat/ada", json={"text": "   "})
        assert res.status_code == 400
        assert res.json()["error"] == "Messaggio vuoto"


async def test_chat_replies_and_keeps_history(client, app_and_store):
    app, _, _ = app_and_store
    async with client as c:
        res = await c.post("/api/chat/ada", json={"text": "Come va?"})
        assert res.status_code == 200
        body = res.json()
        assert body["steered"] is False  # no run active
        assert isinstance(body["reply"], str) and body["reply"]
        res = await c.get("/api/chat/ada")
        history = res.json()
        assert [h["from"] for h in history] == ["user", "ada"]
        assert history[0]["text"] == "Come va?"
        assert history[1]["text"] == body["reply"]
        assert all("ts" in h for h in history)
        # unknown agent: empty history, no 404 (Node returns `?? []`)
        assert (await c.get("/api/chat/nobody")).json() == []


async def test_chat_history_is_capped_at_60(client, app_and_store):
    app, _, _ = app_and_store
    app.state.chats["ada"] = [{"from": "user", "text": f"m{i}", "ts": i} for i in range(60)]
    async with client as c:
        await c.post("/api/chat/ada", json={"text": "ancora"})
        res = await c.get("/api/chat/ada")
        assert len(res.json()) == 60
        assert res.json()[-1]["text"]  # the fresh reply is kept, oldest dropped


async def test_chat_steers_the_active_run(client, app_and_store):
    app, _, _ = app_and_store
    fake = FakeRun(goal="Vivo", ctx=app.state.ctx)
    fake.data["status"] = "running"
    app.state.live[fake.data["id"]] = fake
    async with client as c:
        res = await c.post("/api/chat/leo", json={"text": "Accelera"})
        assert res.json()["steered"] is True
        # leo is the dev lead: the steer scope is his whole team
        assert fake.steered == [("team:dev", "Accelera")]
        assert ("user", "leo", "chat", "Accelera") in fake.messages
        # the CEO steers everybody instead
        await c.post("/api/chat/ada", json={"text": "Tutti"})
        assert ("all", "Tutti") in fake.steered
    app.state.live.clear()


# ---------- media + state wiring ----------


async def test_media_status_route(client):
    async with client as c:
        res = await c.get("/api/media")
        assert res.status_code == 200
        assert set(res.json().keys()) == {"image", "speech", "providers"}


async def test_state_has_real_agents_and_media(client):
    async with client as c:
        body = (await c.get("/api/state")).json()
        assert any(a["id"] == "ada" and a["kind"] == "ceo" for a in body["agents"])
        assert any(a["id"] == "leo" and a["kind"] == "lead" for a in body["agents"])
        assert set(body["media"].keys()) == {"image", "speech", "providers"}


# ---------- /preview falls back to the live run ----------


async def test_preview_uses_live_run_workspace(client, app_and_store, tmp_path):
    app, _, _ = app_and_store
    ws = tmp_path / "ws-live"
    ws.mkdir()
    (ws / "index.html").write_text("<h1>live</h1>", encoding="utf-8")
    fake = FakeRun(goal="Vivo", ctx=app.state.ctx)
    fake.data["workspace"] = str(ws)
    app.state.live[fake.data["id"]] = fake
    async with client as c:
        res = await c.get(f"/preview/{fake.data['id']}/index.html")
        assert res.status_code == 200
        assert res.text == "<h1>live</h1>"
        res = await c.get(f"/preview/{fake.data['id']}")
        assert res.status_code == 302 or res.history  # redirect to trailing slash
    app.state.live.clear()
