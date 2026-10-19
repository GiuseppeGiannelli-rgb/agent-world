"""GET/POST /api/skills*, GET/POST /api/brain -- mirrors the Skill Hub and
Brain handlers in server/index.js."""

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.downloads import DownloadError
from backend.i18n import DEFAULT, Refusal, http_error, ui_language
from backend.plan import nz


def mount(app, *, skills, brain, skiller=None, config=None) -> None:
    def _err(status: int, key: str, **vars) -> JSONResponse:
        """N13: the error in the language of the app, read at every request."""
        lang = ui_language(config.get()) if config is not None else DEFAULT
        return JSONResponse({"error": http_error(lang, key, **vars)}, status_code=status)

    @app.get("/api/skills")
    async def api_skills(q: str | None = None):
        results = await skills.search(q, 40) if q else skills.skills[:400]
        return {
            **skills.summary(),
            "results": [{"id": r["id"], "name": r["name"], "description": r["description"], "source": r["source"], "rel": r["rel"], "score": r.get("score")} for r in results],
        }

    @app.get("/api/skills/read")
    async def api_skills_read(id: str | None = None):
        try:
            r = await skills.read(id)
        except Refusal as err:
            return _err(404, err.key, **err.vars)
        return {"name": r["skill"]["name"], "source": r["skill"]["source"], "path": r["skill"]["path"], "content": r["text"]}

    @app.post("/api/skills/reindex")
    async def api_skills_reindex():
        count = await skills.reindex()
        return {"count": count, **skills.summary()}

    @app.post("/api/skills/repo")
    async def api_skills_repo(request: Request):
        body = await request.json()
        try:
            return await skills.add_repo(body.get("url"))
        except Refusal as err:
            return _err(400, err.key, **err.vars)
        except RuntimeError as err:  # git failed: no such repository, or no network (it was a bare 500)
            return _err(502, "repo_failed", detail=str(err))

    @app.get("/api/skills/skiller")
    async def api_skiller():
        if skiller is None:
            return _err(404, "skiller_off")
        return skiller.report()

    @app.post("/api/skills/skiller/run")
    async def api_skiller_run():
        if skiller is None:
            return _err(404, "skiller_off")
        return {**await skiller.run_once(), "report": skiller.report()}

    @app.post("/api/skills/skiller/approve")
    async def api_skiller_approve(request: Request):
        if skiller is None:
            return _err(404, "skiller_off")
        body = await request.json()
        try:
            return {"slug": body.get("slug"), "install": await skiller.approve(str(body.get("slug") or ""))}
        except DownloadError as err:
            # N13: the sentence in the app's language; what the download layer found is a detail
            return _err(400, "download_refused", detail=str(err))

    @app.get("/api/brain")
    async def api_brain_get(q: str | None = None):
        notes = await brain.search(q, 50, quiet=True) if q else brain.list(200)
        return {"count": brain.count, "notes": notes}

    @app.post("/api/brain")
    async def api_brain_post(request: Request):
        body = await request.json()
        if not str(nz(body.get("text"), "")).strip():
            return _err(400, "note_empty")
        note = brain.add(title=body.get("title"), text=body.get("text"), tags=nz(body.get("tags"), ["utente"]), kind="user", agent_id="user")
        return JSONResponse(note, status_code=201)
