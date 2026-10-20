"""Spec 07: the security audit. The server listens on 127.0.0.1 with no
login, so the threats are a web page the user visits (CSRF, DNS rebinding),
the sites the agents build (served by the same server) and an agent steered
by a malicious page into reading the local network (SSRF). Each test drives
the real app or the real function; none touches the network."""

import json
import shutil

import httpx
import pytest

from backend.app import ROOT, create_app
from backend.brain import Brain
from backend.config import Config
from backend.store import Store

APP = "http://127.0.0.1:4300"


@pytest.fixture
def app_and_config(tmp_path):
    # an isolated config folder: POST /api/config must never write the repo's local.json
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    shutil.copy(ROOT / "config" / "default.json", cfg_dir / "default.json")
    config = Config(cfg_dir)
    store = Store(tmp_path)
    app = create_app(config=config, store=store, brain=Brain(tmp_path / "brain.json"))
    return app, config, store, cfg_dir


def client(app, base=APP):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base)


EVIL_PATCH = {"providers": {"openai": {"baseUrl": "https://evil.example/v1"}}}


# ---------- CSRF: a page on another site posts to the local server ----------


async def test_a_cross_site_post_cannot_redirect_the_api_keys(app_and_config):
    """The attack: a "simple" cross-site request (text/plain, no preflight)
    that points a provider at the attacker, who then receives the user's key
    as the Authorization header of the next model call."""
    app, config, _, cfg_dir = app_and_config
    async with client(app) as c:
        res = await c.post("/api/config", content=json.dumps(EVIL_PATCH), headers={"origin": "https://evil.example", "content-type": "text/plain"})
    assert res.status_code == 403
    assert config.get()["providers"]["openai"]["baseUrl"] == "https://api.openai.com/v1"
    assert not (cfg_dir / "local.json").exists()


@pytest.mark.parametrize("origin", ["null", "http://localhost:5173", "http://127.0.0.1:9999", "https://127.0.0.1:4300"])
async def test_every_other_origin_is_refused_on_post(app_and_config, origin):
    # "null": a sandboxed page (the agents' sites, below); another port is
    # another origin, even on the same machine
    app, *_ = app_and_config
    async with client(app) as c:
        for path, body in (("/api/config", {"limits": {"maxParallel": 2}}), ("/api/runs", {"goal": "Una prova cross-site"}), ("/api/brain", {"text": "x"}), ("/v1/chat/completions", {"model": "combo:fast", "messages": []})):
            res = await c.post(path, json=body, headers={"origin": origin})
            assert res.status_code == 403, (origin, path)


async def test_the_app_itself_and_local_tools_still_post(app_and_config):
    app, config, *_ = app_and_config
    async with client(app) as c:
        same = await c.post("/api/config", json={"limits": {"maxParallel": 2}}, headers={"origin": APP})
        assert same.status_code == 200
        # a script or an IDE on the gateway sends no Origin: not a browser, not CSRF
        tool = await c.post("/api/config", json={"limits": {"maxParallel": 3}})
        assert tool.status_code == 200
    assert config.get()["limits"]["maxParallel"] == 3


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
async def test_cross_site_reads_of_the_api_are_refused(app_and_config, site):
    """A GET can cost money too: /api/skills?q= and /api/brain?q= may call an
    embedding model, and an <img> or a no-cors fetch sends no Origin."""
    app, *_ = app_and_config
    async with client(app) as c:
        for path in ("/api/state", "/api/skills?q=landing", "/api/brain?q=x", "/v1/models"):
            res = await c.get(path, headers={"sec-fetch-site": site})
            assert res.status_code == 403, (site, path)
        ok = await c.get("/api/state", headers={"sec-fetch-site": "same-origin"})
        assert ok.status_code == 200
        typed = await c.get("/api/state", headers={"sec-fetch-site": "none"})  # typed in the address bar
        assert typed.status_code == 200


# ---------- DNS rebinding: evil.example resolves to 127.0.0.1 ----------


@pytest.mark.parametrize("host", ["evil.example", "evil.example:4300", "127.0.0.1.evil.example", "192.168.1.20:4300"])
async def test_an_unknown_host_header_is_refused(app_and_config, host):
    app, *_ = app_and_config
    async with client(app) as c:
        for path in ("/api/state", "/", "/api/events"):
            res = await c.get(path, headers={"host": host})
            assert res.status_code == 403, (host, path)


@pytest.mark.parametrize("host", ["127.0.0.1:4300", "localhost:4300", "[::1]:4300", "127.0.0.1", "LOCALHOST:4300"])
async def test_the_loopback_names_are_accepted(app_and_config, host):
    app, *_ = app_and_config
    async with client(app) as c:
        res = await c.get("/api/config", headers={"host": host})
        assert res.status_code == 200, host


async def test_more_hosts_can_be_allowed_for_a_lan_setup(tmp_path, monkeypatch):
    # spec 11 T02 (D8): an allowed LAN host also needs the access key (test_zero_trust.py)
    monkeypatch.setenv("AGENT_WORLD_ALLOWED_HOSTS", "studio.lan, 192.168.1.20")
    key = "t02-access-key-0123456789abcdef"
    monkeypatch.setenv("AGENT_WORLD_API_KEY", key)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    shutil.copy(ROOT / "config" / "default.json", cfg_dir / "default.json")
    app = create_app(config=Config(cfg_dir), store=Store(tmp_path), brain=Brain(tmp_path / "brain.json"))
    async with client(app, "http://192.168.1.20:4300") as c:
        c.headers["authorization"] = f"Bearer {key}"
        assert (await c.get("/api/config")).status_code == 200
        assert (await c.get("/api/config", headers={"host": "studio.lan:4300"})).status_code == 200
        assert (await c.get("/api/config", headers={"host": "evil.example"})).status_code == 403


# ---------- the agents' sites: served by this server, not trusted by it ----------


async def test_a_preview_runs_sandboxed_in_an_opaque_origin(app_and_config, tmp_path):
    """A generated site is untrusted: a page the agents read can steer what
    they write. Without the sandbox its scripts would run on the app's origin
    and could post to /api/config like the app itself."""
    app, _, store, _ = app_and_config
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "index.html").write_text("<script>fetch('/api/config', {method: 'POST'})</script>", encoding="utf-8")
    (ws / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', encoding="utf-8")
    store.save({"id": "r1", "goal": "g", "status": "completed", "createdAt": "2026-10-15T00:00:00.000Z", "workspace": str(ws)}, immediate=True)
    async with client(app) as c:
        for path in ("/preview/r1/index.html", "/preview/r1/logo.svg", "/preview/r1/"):
            res = await c.get(path)
            assert res.status_code == 200, path
            csp = res.headers.get("content-security-policy", "")
            assert csp.startswith("sandbox") and "allow-scripts" in csp, (path, csp)
            assert "allow-same-origin" not in csp, path  # the whole point: an opaque origin
            assert res.headers.get("x-content-type-options") == "nosniff"
        # and what such a page sends ("Origin: null") is refused, as tested above
        res = await c.post("/api/config", json=EVIL_PATCH, headers={"origin": "null", "sec-fetch-site": "cross-site"})
        assert res.status_code == 403


async def test_the_app_pages_are_not_sandboxed(app_and_config):
    app, *_ = app_and_config
    async with client(app) as c:
        res = await c.get("/")
        assert res.status_code == 200
        assert "sandbox" not in res.headers.get("content-security-policy", "")
        assert res.headers.get("x-content-type-options") == "nosniff"


async def test_no_page_can_be_framed_by_another_site(app_and_config, tmp_path):
    """Clickjacking: 127.0.0.1 passes the Host check, so a page could frame
    the app and trick the user into clicking Save or Approve over a decoy."""
    app, _, store, _ = app_and_config
    ws = tmp_path / "ws2"
    ws.mkdir()
    (ws / "index.html").write_text("<p>site</p>", encoding="utf-8")
    store.save({"id": "r2", "goal": "g", "status": "completed", "createdAt": "2026-10-15T00:00:00.000Z", "workspace": str(ws)}, immediate=True)
    async with client(app) as c:
        for path in ("/", "/index.html", "/preview/r2/index.html"):
            res = await c.get(path)
            assert res.headers.get("x-frame-options") == "DENY", path
            assert "frame-ancestors 'none'" in res.headers.get("content-security-policy", ""), path


# ---------- SSRF: an agent asked to read the local network ----------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:4300/api/state",
        "http://localhost:4300/api/config",
        "http://[::1]:4300/",
        "http://[::ffff:127.0.0.1]/",
        "http://2130706433/",  # 127.0.0.1 as one decimal number
        "http://0.0.0.0:4300/",
        "http://10.1.2.3/admin",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://100.64.0.1/",  # carrier-grade NAT
        "http://[fe80::1]/",
        "http://[fd00::1]/",
    ],
)
async def test_web_fetch_refuses_local_and_private_addresses(url):
    from backend.web import web_fetch

    seen = []
    trap = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(200, text="secret")))
    with pytest.raises(ValueError, match="local or private"):
        await web_fetch(url, client=trap)
    assert seen == []  # refused before any connection


async def test_web_fetch_refuses_a_name_that_resolves_to_a_private_address(monkeypatch):
    """DNS rebinding against the agent: the name looks public, its address is not."""
    import backend.web as web

    async def resolve(host, port):
        return ["10.0.0.7"] if host == "intranet.example.com" else ["93.184.216.34"]

    monkeypatch.setattr(web, "_resolve", resolve)
    trap = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="secret")))
    with pytest.raises(ValueError, match="local or private"):
        await web.web_fetch("https://intranet.example.com/wiki", client=trap)


async def test_web_fetch_connects_to_the_address_it_checked(monkeypatch):
    """The checked address is the one used (pinned), so a second, different
    DNS answer cannot slip a private address in between; the Host header
    and the TLS name stay the original ones."""
    import backend.web as web

    answers = iter([["93.184.216.34"], ["127.0.0.1"]])

    async def resolve(host, port):
        return next(answers)

    monkeypatch.setattr(web, "_resolve", resolve)
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers["host"], request.extensions.get("sni_hostname")))
        return httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    out = await web.web_fetch("https://example.com/page", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert out.startswith("HTTP 200 https://example.com/page")
    assert seen == [("93.184.216.34", "example.com", "example.com")]


async def test_web_fetch_does_not_follow_a_redirect_into_the_network(monkeypatch):
    import backend.web as web

    async def resolve(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(web, "_resolve", resolve)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1:4300/api/state"})

    out = await web.web_fetch("https://example.com/r", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert out.startswith("HTTP 302")
    assert len(seen) == 1 and "127.0.0.1" not in seen[0]
