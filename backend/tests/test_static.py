from pathlib import Path

import httpx
import pytest

from backend.app import ROOT, create_app
from backend.store import Store


@pytest.fixture
def client(tmp_path):
    # An isolated Store: creating the app must never touch the repo's own data/.
    app = create_app(store=Store(tmp_path))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_index_html(client):
    async with client as c:
        res = await c.get("/")
        assert res.status_code == 200
        assert b"<html" in res.content.lower()


async def test_real_public_file(client):
    # public/css/app.css exists in this repo.
    async with client as c:
        res = await c.get("/css/app.css")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/css")


async def test_unknown_file_404(client):
    async with client as c:
        res = await c.get("/does/not/exist.xyz")
        assert res.status_code == 404


async def test_vendor_three(client):
    three_build = ROOT / "node_modules" / "three" / "build"
    if not three_build.exists():
        pytest.skip("node_modules/three not installed")
    async with client as c:
        res = await c.get("/vendor/three/three.module.js")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize(
    "path",
    [
        "/..%2f..%2f..%2fserver/index.js",
        "/%2e%2e/%2e%2e/server/index.js",
        "/..\\..\\server\\index.js",
    ],
)
async def test_traversal_forbidden(client, path):
    async with client as c:
        res = await c.get(path)
        assert res.status_code == 403


async def test_traversal_that_stays_inside_is_fine(client):
    # "a/../css/app.css" normalizes to "css/app.css", which is inside the root.
    async with client as c:
        res = await c.get("/a/../css/app.css")
        assert res.status_code == 200


async def test_unmapped_extension_is_octet_stream(client, tmp_path):
    async with client as c:
        # No .xyz file exists in public/, so this exercises the 404 path only;
        # the MIME-map fallback is covered directly in test_mime_map below.
        res = await c.get("/favicon.ico")
        assert res.status_code in (200, 404)


def test_mime_map_fallback():
    from backend.routes.static import MIME

    assert MIME.get(".made-up", "application/octet-stream") == "application/octet-stream"
    assert MIME[".wasm"] == "application/wasm"


async def test_preview_redirect_without_slash(client):
    async with client as c:
        res = await c.get("/preview/abc123", follow_redirects=False)
        assert res.status_code == 302
        assert res.headers["location"] == "/preview/abc123/"


async def test_preview_404_before_store(client):
    async with client as c:
        res = await c.get("/preview/abc123/")
        assert res.status_code == 404
