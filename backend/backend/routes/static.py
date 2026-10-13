"""Static files: public/, /vendor/three*, /preview/:run — mirrors serveFile
in server/index.js (MIME map, traversal guard, directory -> index.html)."""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse

router = APIRouter()

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
}


def _resolve(root: Path, rel: str) -> Path | None:
    """None means the path escaped root (F2): a 403, not a 404."""
    full = (root / rel.lstrip("/\\")).resolve()
    if full != root and not str(full).startswith(str(root) + os.sep):
        return None
    return full


def serve_from(root: Path, rel: str, *, cache_control: str = "no-cache"):
    full = _resolve(root, rel)
    if full is None:
        return PlainTextResponse("Forbidden", status_code=403)
    target = full / "index.html" if full.is_dir() else full
    if not target.is_file():
        return PlainTextResponse("Not found", status_code=404)
    media_type = MIME.get(target.suffix.lower(), "application/octet-stream")
    return FileResponse(target, media_type=media_type, headers={"cache-control": cache_control})


def mount(app, *, public_root: Path, three_build: Path, three_addons: Path, store=None) -> None:
    @app.get("/vendor/three/{path:path}")
    async def vendor_three(path: str):
        return serve_from(three_build, path)

    @app.get("/vendor/three-addons/{path:path}")
    async def vendor_three_addons(path: str):
        return serve_from(three_addons, path)

    @app.get("/preview/{run_id}")
    async def preview_redirect(run_id: str):
        return RedirectResponse(f"/preview/{run_id}/", status_code=302)

    @app.get("/preview/{run_id}/{rest:path}")
    async def preview_file(run_id: str, rest: str = ""):
        run = store.get(run_id) if store is not None else None
        if run is None:
            return PlainTextResponse("Run non trovato", status_code=404)
        return serve_from(Path(run["workspace"]), rest)

    @app.get("/{path:path}")
    async def static_files(path: str):
        return serve_from(public_root, path)
