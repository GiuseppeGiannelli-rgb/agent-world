"""Run lifecycle, agent chat and media status -- mirrors the matching
handlers in server/index.js: POST/GET /api/runs..., answer/pause/resume/stop,
/files, /file, GET/POST /api/chat/:id, GET /api/media, plus the talk() and
describeAgent() helpers."""

import asyncio
import json
import re
import shutil
import time
import traceback
import uuid
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

from backend import attachments
from backend.i18n import LANGUAGES, http_error, ui_language
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
        reply = http_error(language, "chat_unavailable", err=str(err).splitlines()[0])
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


class TooBig(Exception):
    pass


async def _read_capped(request: Request, max_bytes: int) -> bytes:
    """Spec 09: the raw body of an upload, refused while it arrives once it passes
    max_bytes (a declared Content-Length over it is refused before reading)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise TooBig()
    parts, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise TooBig()
        parts.append(chunk)
    return b"".join(parts)


UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{12}$")
UPLOAD_TTL_S = 24 * 3600


def _clean_uploads(root: Path) -> None:
    """Uploads never used by a mission leave after a day."""
    now = time.time()
    for d in root.glob("*"):
        try:
            if d.is_dir() and now - d.stat().st_mtime > UPLOAD_TTL_S:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def mount(app, *, config, store, bus, router, team, media, live: dict, chats: dict, ctx, uploads_dir: Path | None = None) -> None:
    uploads = Path(uploads_dir) if uploads_dir is not None else Path(ctx.workspace_root).parent / "uploads"

    def _err(status: int, key: str, **vars) -> JSONResponse:
        """N13: the error in the language of the app, read at every request."""
        return JSONResponse({"error": http_error(ui_language(config.get()), key, **vars)}, status_code=status)

    def active_run():
        return next(iter(live.values()), None)

    def launch(run, step) -> None:
        """Runs a mission (start, or a resume) in the background; it leaves `live` at the end."""

        async def _go(r=run):
            try:
                await step()
            except Exception:
                traceback.print_exc()
            finally:
                live.pop(r.data["id"], None)

        asyncio.ensure_future(_go())

    def resume_stored(run_id: str, data: dict):
        """Spec 09: a stored run starts again from where it stopped, or the JSONResponse that refuses it."""
        if active_run() is not None:
            return _err(409, "busy")
        if data.get("status") == "completed" and all(w["status"] == "done" for w in data.get("workstreams") or []) and all(t["status"] == "done" for t in data.get("tasks") or []):
            return _err(409, "run_complete")
        team.load(config.get()["staff"])
        run = Run.from_data(data, ctx)
        live[run_id] = run
        launch(run, run.resume_from_block)
        return None

    def max_bytes() -> int:
        return int(float(config.get()["limits"].get("maxUploadMB", 25)) * 1024 * 1024)

    async def read_upload(request: Request):
        """(name, bytes) of an upload, or the JSONResponse that refuses it."""
        name = str(request.query_params.get("name") or "").strip()
        if not name:
            return _err(400, "upload_name_missing")
        try:
            data = await _read_capped(request, max_bytes())
        except TooBig:
            return _err(413, "upload_too_big", mb=f"{float(config.get()['limits'].get('maxUploadMB', 25)):g}")
        try:
            attachments.check(name, data, max_mb=float(config.get()["limits"].get("maxUploadMB", 25)))
        except attachments.AttachmentError as err:
            return _err(400, err.key, **err.vars)
        return name, data

    def staged(upload_id: str):
        """(meta, bytes) of an upload in the staging folder, or None."""
        if not UPLOAD_ID_RE.match(str(upload_id)):
            return None
        d = uploads / upload_id
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            return meta, (d / "blob").read_bytes()
        except (OSError, ValueError):
            return None

    # ----- spec 09: the owner's files -----

    @app.post("/api/uploads")
    async def api_upload(request: Request):
        """A file chosen in the composer, before its mission exists: kept for a day
        in data/uploads/, then moved into the run that names it."""
        got = await read_upload(request)
        if isinstance(got, JSONResponse):
            return got
        name, data = got
        uploads.mkdir(parents=True, exist_ok=True)
        _clean_uploads(uploads)
        upload_id = uuid.uuid4().hex[:12]
        d = uploads / upload_id
        d.mkdir()
        original = re.split(r"[\\/]", name)[-1][:120]
        meta = {"id": upload_id, "name": original, "kind": attachments.kind_of(name), "size": len(data), "at": int(time.time() * 1000)}
        (d / "blob").write_bytes(data)
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return JSONResponse(meta, status_code=201)

    @app.post("/api/runs/{run_id}/attachments")
    async def api_run_attachment(run_id: str, request: Request):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        got = await read_upload(request)
        if isinstance(got, JSONResponse):
            return got
        name, raw = got
        target = run if run is not None else Run.from_data(data, ctx)
        task_id = request.query_params.get("taskId") or None
        if task_id and target.task_by_id(task_id) is None:
            return _err(404, "task_not_found")
        try:
            rec = await target.add_attachment(name, raw, task_id=task_id, note=str(request.query_params.get("note") or ""))
        except attachments.AttachmentError as err:
            return _err(400, err.key, **err.vars)
        if run is None:
            store.save(data, True)
        return JSONResponse(rec, status_code=201)

    @app.post("/api/runs")
    async def api_runs_create(request: Request):
        body = await _body(request)
        goal = str(body.get("goal") or "").strip()
        if len(goal) < 4:
            return _err(400, "goal_missing")
        if active_run() is not None:
            return _err(409, "busy")
        language = body.get("language")
        if language is None:
            language = config.get()["ui"]["language"]
        elif not isinstance(language, str) or language not in LANGUAGES:
            return _err(400, "language_unsupported", value=repr(language), choices=", ".join(LANGUAGES))
        ids = body.get("attachments") or []
        if not isinstance(ids, list) or len(ids) > int(config.get()["limits"].get("maxAttachments", 60)):
            return _err(400, "attachments_not_list")
        files = [staged(i) for i in ids]
        if any(f is None for f in files):
            return _err(400, "upload_gone")
        team.load(config.get()["staff"])
        options = {"approvePlan": body["approvePlan"]} if "approvePlan" in body else {}
        options["language"] = language  # D1: frozen for the whole run
        run = Run(goal=goal[:4000], ctx=ctx, options=options)
        live[run.data["id"]] = run
        # spec 09: the composer's files are in the run before the CEO plans it
        try:
            for upload_id, (meta, raw) in zip(ids, files):
                await run.add_attachment(meta["name"], raw, announce=False)
                shutil.rmtree(uploads / upload_id, ignore_errors=True)
        except attachments.AttachmentError as err:
            live.pop(run.data["id"], None)
            return _err(400, err.key, **err.vars)
        run.emit_run(True)
        launch(run, run.start)
        return JSONResponse({"id": run.data["id"]}, status_code=201)

    @app.get("/api/runs/{run_id}")
    async def api_run_get(run_id: str):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        return data

    @app.post("/api/runs/{run_id}/answer")
    async def api_run_answer(run_id: str, request: Request):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        body = await _body(request)
        item_id = str(body.get("itemId") or "")
        if body.get("solve"):
            # spec 09: "Find a solution yourself": the lead (or the CEO, TypeSafe as arbiter) decides
            target = run if run is not None else Run.from_data(data, ctx)
            decision = await (target.solve(item_id) if run is not None else target.solve_pending(item_id))
            if decision is None:
                return _err(409, "request_closed")
            if run is None:
                store.save(data, True)
            return {"ok": True, "decision": decision["text"], "by": decision["by"], "arbiter": decision["arbiter"], **({"resumable": True} if run is None else {})}
        if run is None:
            # spec 09: a question of a stopped run is answered now and reaches its task on resume
            stored = Run.from_data(data, ctx)
            if not stored.answer_pending(item_id, str(body.get("text") or "")):
                return _err(409, "request_closed")
            store.save(data, True)
            return {"ok": True, "resumable": True}
        decision = body.get("decision")
        ok = run.answer(
            str(body.get("itemId") or ""),
            {"text": body.get("text") or "", "decision": decision if decision in ("approve", "reject") else None},
        )
        return {"ok": True} if ok else _err(409, "request_closed")

    @app.post("/api/runs/{run_id}/tasks/{task_id}/interact")
    async def api_task_interact(run_id: str, task_id: str, request: Request):
        """Spec 09 §2: the owner talks to one task -- a blocked one too, in a stopped run."""
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        target = run if run is not None else Run.from_data(data, ctx)
        task = target.task_by_id(task_id)
        if task is None:
            return _err(404, "task_not_found")
        body = await _body(request)
        text = str(body.get("text") or "").strip()[:4000]
        ids = body.get("attachments") or []
        known = {a["id"]: a for a in data.get("attachments") or []}
        if not isinstance(ids, list) or any(i not in known for i in ids):
            return _err(400, "attachment_not_in_run")
        if not text and not ids:
            return _err(400, "interact_empty")
        if ids:
            text = f"{text}\n" if text else ""
            text += "Files: " + ", ".join(known[i]["path"] for i in ids)
        out = await target.interact(task, text, attachment_ids=ids)
        if run is None:
            store.save(data, True)
            out["resumable"] = True
            if body.get("resume"):
                refused = resume_stored(run_id, data)
                if refused is not None:
                    return refused
                out["resumed"] = True
        return out

    @app.post("/api/runs/{run_id}/refine")
    async def api_run_refine(run_id: str, request: Request):
        """Spec 09 §4: a change to what was delivered, during the run or after it."""
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        body = await _body(request)
        text = str(body.get("text") or "").strip()[:4000]
        ids = body.get("attachments") or []
        if not isinstance(ids, list) or any(i not in {a["id"] for a in data.get("attachments") or []} for i in ids):
            return _err(400, "attachment_not_in_run")
        if not text:
            return _err(400, "refine_empty")
        if run is not None and run.data["status"] not in ("running",):
            return _err(409, "refine_busy")
        if run is None and active_run() is not None:
            return _err(409, "busy")
        target = run if run is not None else Run.from_data(data, ctx)
        task_id = body.get("taskId")
        if task_id is not None and (target.task_by_id(str(task_id)) or {}).get("status") != "done":
            return _err(404, "refine_task_not_found")
        out = await target.refine(text, ids, task_id=str(task_id) if task_id else None)
        if not out["targets"]:
            return _err(409, "refine_nothing")
        if run is None:
            store.save(data, True)
            refused = resume_stored(run_id, data)
            if refused is not None:
                return refused
            out["resumed"] = True
        return out

    @app.post("/api/runs/{run_id}/{action}")
    async def api_run_action(run_id: str, action: str):
        if action not in ("pause", "resume", "stop"):
            return _err(404, "unknown_endpoint")
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        if run is None and action == "resume":
            # spec 09: "Riprendi workflow dal punto di blocco"
            refused = resume_stored(run_id, data)
            return refused if refused is not None else {"ok": True, "resumed": True}
        if run is None:
            return _err(409, "run_not_active")
        getattr(run, action)()
        return {"ok": True}

    @app.get("/api/runs/{run_id}/files")
    async def api_run_files(run_id: str):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        return await Workspace(data["workspace"]).list(".", 500)

    @app.get("/api/runs/{run_id}/file")
    async def api_run_file(run_id: str, request: Request):
        run = live.get(run_id)
        data = run.data if run is not None else store.get(run_id)
        if data is None:
            return _err(404, "run_not_found")
        path = request.query_params.get("path")
        try:
            content = await Workspace(data["workspace"]).read(path, 400_000)
            return {"path": path, "content": content}
        except Exception as err:
            return _err(404, "file_unreadable", path=repr(path), err=err)

    # ----- talk to an agent -----

    @app.get("/api/chat/{agent_id}")
    async def api_chat_get(agent_id: str):
        return chats.get(agent_id) or []

    @app.post("/api/chat/{agent_id}")
    async def api_chat_post(agent_id: str, request: Request):
        agent = team.get(agent_id)
        if agent is None:
            return _err(404, "agent_not_found")
        body = await _body(request)
        text = str(body.get("text") or "").strip()[:2000]
        if not text:
            return _err(400, "message_empty")
        return await talk(agent, text, config=config, router=router, chats=chats, bus=bus, active_run=active_run)

    @app.get("/api/media")
    async def api_media():
        return media.status()
