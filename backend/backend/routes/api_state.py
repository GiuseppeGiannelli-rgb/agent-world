"""GET /api/state, GET/POST /api/config, GET /api/runs[/:id] -- mirrors the
matching handlers in server/index.js."""

from fastapi import Request
from fastapi.responses import JSONResponse

from backend.router.providers import ProviderError
from backend.state import build_state, public_config


def _bad_combo_message(name: str) -> str:
    return f'Combo "{name}": "models" deve essere una lista di "provider/modello"'


def mount(app, *, config, store, bus=None, router=None) -> None:
    @app.get("/api/state")
    async def api_state():
        return build_state(config, store, router=router)

    @app.get("/api/config")
    async def api_config_get():
        return public_config(config)

    @app.post("/api/config")
    async def api_config_post(request: Request):
        body = await request.json()
        combos = body.get("combos")
        if combos:
            for name, c in combos.items():
                models = c.get("models") if isinstance(c, dict) else None
                if not isinstance(models, list) or any(not isinstance(m, str) or "/" not in m for m in models):
                    return JSONResponse({"error": _bad_combo_message(name)}, status_code=400)
        config.update(body)
        public = public_config(config)
        if bus is not None:
            bus.emit("config", public)
        return public

    @app.get("/api/runs")
    async def api_runs_list():
        from backend.state import run_list

        return run_list(store)

    @app.get("/api/runs/{run_id}")
    async def api_run_get(run_id: str):
        run = store.get(run_id)
        if run is None:
            return JSONResponse({"error": "Run non trovato"}, status_code=404)
        return run

    @app.get("/api/router")
    async def api_router_snapshot():
        return router.snapshot()

    @app.post("/api/router/test")
    async def api_router_test(request: Request):
        body = await request.json()
        use = str(body.get("use") or "fast")
        try:
            out = await router.chat(use=use, messages=[{"role": "user", "content": "Reply with the single word: pong"}], max_tokens=20, meta={"agentId": "test"})
            return {"ok": True, "target": out["target"], "ms": out["ms"], "text": out["text"][:200], "demo": out["demo"]}
        except ProviderError as err:
            return {"ok": False, "error": str(err)}
