"""GET/POST /api/skills*, GET/POST /api/brain -- mirrors the Skill Hub and
Brain handlers in server/index.js."""

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.plan import nz


def mount(app, *, skills, brain) -> None:
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
        except ValueError as err:
            return JSONResponse({"error": str(err)}, status_code=404)
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
        except ValueError as err:
            return JSONResponse({"error": str(err)}, status_code=400)

    @app.get("/api/brain")
    async def api_brain_get(q: str | None = None):
        notes = await brain.search(q, 50, quiet=True) if q else brain.list(200)
        return {"count": brain.count, "notes": notes}

    @app.post("/api/brain")
    async def api_brain_post(request: Request):
        body = await request.json()
        if not str(nz(body.get("text"), "")).strip():
            return JSONResponse({"error": "Scrivi il contenuto della nota"}, status_code=400)
        note = brain.add(title=body.get("title"), text=body.get("text"), tags=nz(body.get("tags"), ["utente"]), kind="user", agent_id="user")
        return JSONResponse(note, status_code=201)
