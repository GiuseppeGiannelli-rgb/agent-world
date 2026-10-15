"""Run lifecycle, agent chat and media status -- mirrors the matching
handlers in server/index.js: POST/GET /api/runs..., answer/pause/resume/stop,
/files, /file, GET/POST /api/chat/:id, GET /api/media, plus the talk() and
describeAgent() helpers."""

import asyncio
import time
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.i18n import LANGUAGES
from backend.prompts import chat_prompt
from backend.run import Run
from backend.tools import Workspace


def describe_agent(a: dict, config) -> str:
    c = config.get()
    if a["kind"] == "ceo":
        return "the CEO of the company, who plans missions and coordinates every team lead"
    t = c["teams"].get(a["team"]) or {}
    label = t.get("label") or a["team"]
    if a["kind"] == "lead":
        return f"lead (task manager) of the {label} team: {t.get('brief') or ''}"
    if a["kind"] == "sub":
        return f"a temporary sub-agent of the {label} team"
    return f"a {t.get('title') or 'worker'} in the {label} team: {t.get('brief') or ''}"


# The owner talks to an agent. During a run the message also steers the work:
# to the CEO it reaches everybody, to a lead the whole team, to a worker only them.
async def talk(agent: dict, text: str, *, config, router, chats, bus, active_run) -> dict:
    history = chats.get(agent["id"]) or []
    run = active_run()
    context = "No mission is running right now."
    language = config.get()["ui"]["language"]
    if run is not None:
        scope = "all" if agent["kind"] == "ceo" else (f"team:{agent['team']}" if agent["kind"] == "lead" else f"agent:{agent['id']}")
        run.steer(scope, text)
        run.message("user", agent["id"], "chat", text)
        language = run.data.get("language") or language
        task = run.task_by_id(agent["taskId"]) if agent.get("taskId") else None
        context = (
            f"Mission: {run.data['goal']}\nStatus: {run.data['status']}\nYour state: {agent['state']}"
            + (f"\nYour task: {task['id']} {task['title']}" if task else "")
            + f"\nTeam progress:\n{run.progress_text(None if agent['kind'] == 'ceo' else agent['team'])}"
        )
    try:
        out = await router.chat(
            role="ceo" if agent["kind"] == "ceo" else agent["team"],
            messages=chat_prompt(agent=agent, who=describe_agent(agent, config), context=context, history=history[-10:], text=text, language=language),
            max_tokens=600,
            meta={"agentId": agent["id"]},
        )
        reply = out["text"].strip()
    except Exception as err:
        reply = f"(Non riesco a rispondere ora: {str(err).splitlines()[0]})"
    now = int(time.time() * 1000)
    history = history + [{"from": "user", "text": text, "ts": now}, {"from": agent["id"], "text": reply, "ts": now}]
    chats[agent["id"]] = history[-60:]
    if run is not None:
        run.message(agent["id"], "user", "chat", reply)
    bus.emit("chat", {"agentId": agent["id"], "reply": reply})
    return {"reply": reply, "steered": run is not None}


async def _body(request: Request) -> dict:
    """Node's readBody: empty body -> {}, invalid JSON -> 400."""
    raw = await request.body()
    if not raw:
        return {}
    return await request.json()


def _err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def mount(app, *, config, store, bus, router, team, media, live: dict, chats: dict, ctx) -> None:
    def active_run():
        return next(iter(live.values()), None)

    @app.post("/api/runs")
    async def api_runs_create(request: Request):
        body = await _body(request)
        goal = str(body.get("goal") or "").strip()
        if len(goal) < 4:
            return _err(400, "Scrivi un obiettivo per la squadra.")
        if active_run() is not None:
            return _err(409, "La squadra sta già lavorando a un run. Fermalo o aspetta che finisca.")
        language = body.get("language")
        if language is None:
            language = config.get()["ui"]["language"]
        elif not isinstance(language, str) or language not in LANGUAGES:
            return _err(400, f"Lingua non supportata: {language!r}. Scegli fra {', '.join(LANGUAGES)}.")
        team.load(config.get()["staff"])
        options = {"approvePlan": body["approvePlan"]} if "approvePlan" in body else {}
        options["language"] = language  # D1: frozen for the whole run
        run = Run(goal=goal[:4000], ctx=ctx, options=options)
        live[run.data["id"]] = run
        run.emit_run(True)

        async def _start(r=run):
            try:
                await r.start()
            except Exception:
                traceback.print_exc()
            finally:
                live.pop(r.data["id"], None)

        asyncio.ensure_future(_start())
        return JSONResponse({"id": run.data["id"]}, status_code=201)

    @app.get("/api/runs/{run_id}")
    async def api_run_get(run_id: str):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "Run non trovato")
        return data

    @app.post("/api/runs/{run_id}/answer")
    async def api_run_answer(run_id: str, request: Request):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "Run non trovato")
        if run is None:
            return _err(409, "Questo run non è attivo")
        body = await _body(request)
        decision = body.get("decision")
        ok = run.answer(
            str(body.get("itemId") or ""),
            {"text": body.get("text") or "", "decision": decision if decision in ("approve", "reject") else None},
        )
        return {"ok": True} if ok else _err(409, "Questa richiesta non è più aperta")

    @app.post("/api/runs/{run_id}/{action}")
    async def api_run_action(run_id: str, action: str):
        if action not in ("pause", "resume", "stop"):
            return _err(404, "Endpoint sconosciuto")
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "Run non trovato")
        if run is None:
            return _err(409, "Questo run non è attivo")
        getattr(run, action)()
        return {"ok": True}

    @app.get("/api/runs/{run_id}/files")
    async def api_run_files(run_id: str):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "Run non trovato")
        return await Workspace(data["workspace"]).list(".", 500)

    @app.get("/api/runs/{run_id}/file")
    async def api_run_file(run_id: str, request: Request):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "Run non trovato")
        path = request.query_params.get("path")
        try:
            content = await Workspace(data["workspace"]).read(path, 400_000)
            return {"path": path, "content": content}
        except Exception as err:
            return _err(404, str(err))

    # ----- talk to an agent -----

    @app.get("/api/chat/{agent_id}")
    async def api_chat_get(agent_id: str):
        return chats.get(agent_id) or []

    @app.post("/api/chat/{agent_id}")
    async def api_chat_post(agent_id: str, request: Request):
        agent = team.get(agent_id)
        if agent is None:
            return _err(404, "Agente non trovato")
        body = await _body(request)
        text = str(body.get("text") or "").strip()[:2000]
        if not text:
            return _err(400, "Messaggio vuoto")
        return await talk(agent, text, config=config, router=router, chats=chats, bus=bus, active_run=active_run)

    @app.get("/api/media")
    async def api_media():
        return media.status()
