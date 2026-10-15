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


# Spec 07: what the agents build is untrusted (a page they read can steer what
# they write), yet this server serves it. The sandbox gives its scripts an
# opaque origin: they run, but they are not the app, and LocalGuard refuses
# what they send to /api. No allow-same-origin, by design: the price is that a
# generated site cannot use localStorage here (open it from the folder for that).
# frame-ancestors / X-Frame-Options on every page: 127.0.0.1 passes the Host
# check, so without them another site could frame the app (clickjacking).
NO_FRAMES = "frame-ancestors 'none'"
PREVIEW_CSP = f"sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads allow-pointer-lock; {NO_FRAMES}"


def serve_from(root: Path, rel: str, *, cache_control: str = "no-cache", sandbox: bool = False):
    full = _resolve(root, rel)
    if full is None:
        return PlainTextResponse("Forbidden", status_code=403)
    target = full / "index.html" if full.is_dir() else full
    if not target.is_file():
        return PlainTextResponse("Not found", status_code=404)
    media_type = MIME.get(target.suffix.lower(), "application/octet-stream")
    headers = {"cache-control": cache_control, "x-content-type-options": "nosniff", "x-frame-options": "DENY", "content-security-policy": PREVIEW_CSP if sandbox else NO_FRAMES}
    return FileResponse(target, media_type=media_type, headers=headers)


def mount(app, *, public_root: Path, three_build: Path, three_addons: Path, store=None, live=None) -> None:
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
        # Node: store.get(id) ?? live.get(id)?.data -- a running mission's
        # workspace is previewable before it lands in the store.
        run = store.get(run_id) if store is not None else None
        if run is None and live is not None:
            active = live.get(run_id)
            run = active.data if active is not None else None
        if run is None:
            return PlainTextResponse("Run non trovato", status_code=404)
        return serve_from(Path(run["workspace"]), rest, sandbox=True)

    @app.get("/{path:path}")
    async def static_files(path: str):
        return serve_from(public_root, path)
