"""Spec 11 T02: a zero-trust shell and the access key on the LAN.

- run_command (on only with AGENT_WORLD_ALLOW_SHELL=1) starts its command with
  an environment without the keys: every variable whose name has a secret word
  (KEY, TOKEN, SECRET, PASSWORD, CREDENTIALS, AUTH...) and every variable the
  config names as a provider key (keyEnv), whatever its form (D6).
- A request is local only when both its Host and the address it comes from are
  loopback (D7). Any other request to /api/*, /api/events or /v1/* needs
  AGENT_WORLD_API_KEY: a Bearer header (scripts) or the session cookie the
  browser gets from POST /api/session (D10). With no key on the server, the
  LAN is refused (D8). The spec 07 checks (Host, Origin, Sec-Fetch-Site) run
  first and are unchanged.

Each test drives the real app (httpx ASGITransport, with the client address it
needs) or the real function; none touches the network."""

import json
import shutil
import sys
import time

import httpx
import pytest
from test_attachments import ctx  # noqa: F401 -- the fixture of a Run's context (tests/ is on sys.path)

from backend.app import ROOT, create_app
from backend.brain import Brain
from backend.config import Config
from backend.i18n import http_error
from backend.store import Store

KEY = "t02-access-key-0123456789abcdef"
LAN = "http://192.168.1.20:4300"
LAN_PEER = ("192.168.1.30", 51000)
LOCAL = "http://127.0.0.1:4300"
LOCAL_PEER = ("127.0.0.1", 51000)


# ---------- the shell: no key reaches a command ----------

# every value holds MARK: the command lists the variables whose value has it
MARK = "zt02x"
SECRETS = {
    "OPENAI_API_KEY": f"sk-{MARK}-openai",
    "GITHUB_TOKEN": f"ghp-{MARK}-github",
    "AGENT_WORLD_API_KEY": f"{MARK}-own-key",
    "HF_TOKEN": f"hf-{MARK}",
    "FAL_KEY": f"fal-{MARK}",
    "CLOUDFLARE_API_TOKEN": f"cf-{MARK}",
    "AWS_SECRET_ACCESS_KEY": f"aws-{MARK}",
    "ANTHROPIC_AUTH_TOKEN": f"ant-{MARK}",
    "GOOGLE_APPLICATION_CREDENTIALS": f"creds-{MARK}.json",
    "DB_PASSWORD": f"pw-{MARK}",
    "SSH_AUTH_SOCK": f"sock-{MARK}",
    "OPENAI_API_KEY_BACKUP": f"sk-{MARK}-backup",
    "SERPAPI_APIKEY": f"serp-{MARK}",
    "npm_config__auth": f"npm-{MARK}",
}
KEPT = {
    "PATH": "/usr/bin",
    "TOKENIZERS_PARALLELISM": "false",
    "MONKEY_MODE": "1",
    "KEYBOARD_LAYOUT": "it",
    "PORT": "4300",
    "CLOUDFLARE_ACCOUNT_ID": "acct",
    "LOCAL_OPENAI_URL": "http://127.0.0.1:1234/v1",
    "AGENT_WORLD_HOME": "/tmp/aw",
}


def test_the_shell_env_drops_every_secret_and_keeps_the_rest():
    from backend.tools import shell_env

    env = shell_env(base={**SECRETS, **KEPT, "MYBOX_CREDS": "box-t02"}, names={"MYBOX_CREDS"})
    assert env == KEPT


def test_the_shell_env_reads_the_names_without_case():
    # Windows: the environment ignores case, so a name the config writes in lower case is the same variable
    from backend.tools import shell_env

    assert shell_env(base={"MYBOX_CREDS": "x", "Path": "p"}, names={"mybox_creds"}) == {"Path": "p"}


def test_the_config_names_its_provider_keys():
    from backend.tools import config_key_names

    cfg = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))
    cfg["providers"]["mybox"] = {"kind": "openai", "baseUrl": "https://box.example/v1", "keyEnv": "MYBOX_CREDS"}
    names = config_key_names(cfg)
    assert {"OPENAI_API_KEY", "HF_TOKEN", "FAL_KEY", "ELEVENLABS_API_KEY", "CLOUDFLARE_API_TOKEN", "TYPESAFE_API_KEY", "LOCAL_OPENAI_KEY", "MYBOX_CREDS"} <= names
    # the URLs of the local servers are not keys: a command may need them
    assert not {"LOCAL_OPENAI_URL", "TYPESAFE_BASE_URL"} & names


# the names of the variables a command sees with MARK in their value, or named AW_T02_*
# (the whole environment would not fit: run_command keeps the last 5000 characters)
ENV_DUMP = f"\"{sys.executable}\" -c \"import os, json; print(json.dumps(sorted(k.upper() for k, v in os.environ.items() if '{MARK}' in v or k.upper().startswith('AW_T02'))))\""


def _dumped(output: str) -> list:
    return json.loads(output.strip().splitlines()[-1])


@pytest.mark.asyncio
async def test_a_shell_command_sees_no_key(tmp_path, monkeypatch):
    from backend.tools import run_command

    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("AW_T02_VISIBLE", "yes")
    r = await run_command(ENV_DUMP, tmp_path, 20000)
    assert r["code"] == 0, r["output"]
    # no secret is left, and the rest of the environment is there: tools still run
    assert _dumped(r["output"]) == ["AW_T02_VISIBLE"]


@pytest.fixture
def run_with_shell(ctx):  # noqa: F811
    from backend.run import Run

    cfg = ctx.config.get()
    cfg["limits"]["allowShell"] = True
    cfg["providers"]["mybox"] = {"kind": "openai", "baseUrl": "https://box.example/v1", "keyEnv": "MYBOX_CREDS"}
    run = Run(goal="A site for my bar", ctx=ctx)
    return run, next(a for a in ctx.team.list() if a["team"] == "dev")


@pytest.mark.asyncio
async def test_the_run_hides_the_keys_its_config_names(run_with_shell, monkeypatch):
    """A provider registered with a key of its own name (here, one without a
    secret word) is a key all the same: the run passes the config's names."""
    monkeypatch.setenv("MYBOX_CREDS", f"box-{MARK}")
    monkeypatch.setenv("OPENAI_API_KEY", f"sk-{MARK}-openai")
    monkeypatch.setenv("AW_T02_VISIBLE", "yes")
    run, agent = run_with_shell
    await run.ws.ensure()
    out = await run.exec_tool({"id": "w1.1", "wsId": "w1", "team": "dev", "title": "Build"}, agent, {"thought": "", "tool": "run_command", "args": {"cmd": ENV_DUMP}})
    assert out.startswith("exit code 0"), out
    assert _dumped(out) == ["AW_T02_VISIBLE"]


# ---------- who is local ----------


@pytest.mark.parametrize(
    "peer,host,local",
    [
        (("127.0.0.1", 1), "127.0.0.1:4300", True),
        (("127.0.0.1", 1), "localhost:4300", True),
        (("::1", 1), "[::1]:4300", True),
        (("::ffff:127.0.0.1", 1), "LOCALHOST", True),
        (("127.0.0.5", 1), "127.0.0.1", True),  # the whole 127/8 is this machine
        (("192.168.1.30", 1), "127.0.0.1:4300", False),  # D7: a Host header is written by the client
        (("127.0.0.1", 1), "192.168.1.20:4300", False),  # the LAN name, even from this machine
        (("127.0.0.1", 1), "studio.lan:4300", False),
        (None, "127.0.0.1:4300", False),  # no address: not provably local
        (("testclient", 1), "127.0.0.1", False),
    ],
)
def test_a_request_is_local_only_with_a_loopback_host_and_peer(peer, host, local):
    from backend.security import is_local

    assert is_local({"client": peer, "headers": [(b"host", host.encode())]}) is local


# ---------- the session cookie ----------


def test_the_session_cookie_is_signed_expires_and_dies_with_the_key():
    from backend.security import SESSION_DAYS, session_token, valid_session

    now = time.time()
    token = session_token(KEY, now)
    assert KEY not in token  # the cookie is not the key
    assert valid_session(KEY, token, now)
    assert valid_session(KEY, token, now + SESSION_DAYS * 86400 - 60)
    assert not valid_session(KEY, token, now + SESSION_DAYS * 86400 + 60)  # expired
    assert not valid_session("another-key-of-the-same-size-xyz", token, now)  # a new key logs everyone out
    exp, sig = token.split(".")
    assert not valid_session(KEY, f"{int(exp) + 86400}.{sig}", now)  # a longer life is not signed
    for bad in ("", ".", "abc", "1.2", f"{exp}.", f".{sig}", "²³.abc", f"{exp}.{sig}x", "-1." + sig):
        assert not valid_session(KEY, bad, now), bad


# ---------- the LAN, through the real app ----------


@pytest.fixture
def lan_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORLD_ALLOWED_HOSTS", "studio.lan, 192.168.1.20")
    monkeypatch.setenv("AGENT_WORLD_API_KEY", KEY)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    shutil.copy(ROOT / "config" / "default.json", cfg_dir / "default.json")
    config = Config(cfg_dir)
    return create_app(config=config, store=Store(tmp_path), brain=Brain(tmp_path / "brain.json")), config


def client(app, base=LAN, peer=LAN_PEER, **kw):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=peer), base_url=base, **kw)


API_READS = ("/api/state", "/api/config", "/api/runs", "/api/events", "/api/skills?q=x", "/api/brain", "/v1/models")


@pytest.mark.asyncio
async def test_the_local_flow_needs_no_key(lan_app):
    app, _ = lan_app
    async with client(app, LOCAL, LOCAL_PEER) as c:
        assert (await c.get("/api/state")).status_code == 200
        assert (await c.post("/api/config", json={"limits": {"maxParallel": 2}}, headers={"origin": LOCAL})).status_code == 200
        assert (await c.get("/api/session")).json() == {"local": True, "keyRequired": False, "keySet": True, "authenticated": True, "language": "en"}


@pytest.mark.asyncio
async def test_the_lan_without_the_key_is_refused(lan_app):
    app, _ = lan_app
    async with client(app) as c:
        for path in API_READS:
            res = await c.get(path)
            assert res.status_code == 401, path
            assert res.headers.get("www-authenticate", "").startswith("Bearer"), path
            assert res.json()["error"] == http_error("en", "auth_required"), path
        res = await c.post("/api/runs", json={"goal": "A site for my bar"}, headers={"origin": LAN})
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_a_spoofed_loopback_host_from_the_lan_still_needs_the_key(lan_app):
    """D7: the spec says "a host that is not 127.0.0.1", but the Host header is
    the client's: a script on the LAN writes 127.0.0.1 and would be local."""
    app, _ = lan_app
    async with client(app, LOCAL, LAN_PEER) as c:
        assert (await c.get("/api/state")).status_code == 401
        assert (await c.get("/api/config", headers={"host": "localhost:4300"})).status_code == 401


@pytest.mark.asyncio
async def test_a_lan_name_needs_the_key_even_from_this_machine(lan_app):
    app, _ = lan_app
    async with client(app, LAN, LOCAL_PEER) as c:
        assert (await c.get("/api/state")).status_code == 401


@pytest.mark.asyncio
async def test_a_script_on_the_lan_passes_with_the_bearer_key(lan_app):
    app, config = lan_app
    async with client(app, headers={"authorization": f"Bearer {KEY}"}) as c:
        for path in ("/api/state", "/api/config", "/api/runs", "/v1/models"):
            assert (await c.get(path)).status_code == 200, path
        # a script sends no Origin: the spec 07 CSRF rule lets it post, as on this machine
        assert (await c.post("/api/config", json={"limits": {"maxParallel": 3}})).status_code == 200
    assert config.get()["limits"]["maxParallel"] == 3
    async with client(app, headers={"authorization": f"Bearer {KEY}x"}) as c:
        assert (await c.get("/api/state")).status_code == 401
    async with client(app, headers={"authorization": KEY}) as c:  # the key without "Bearer"
        assert (await c.get("/api/state")).status_code == 401


@pytest.mark.asyncio
async def test_without_a_key_on_the_server_the_lan_is_closed(lan_app, monkeypatch):
    """D8: before T02, AGENT_WORLD_ALLOWED_HOSTS alone opened the API to the
    LAN. Now the LAN needs a key, and without one it stays closed."""
    monkeypatch.delenv("AGENT_WORLD_API_KEY")
    app, _ = lan_app
    async with client(app) as c:
        for path in ("/api/state", "/api/events", "/v1/models"):
            res = await c.get(path)
            assert res.status_code == 403, path
            assert res.json()["error"] == http_error("en", "lan_needs_key")
        assert (await c.get("/api/session")).json() == {"local": False, "keyRequired": True, "keySet": False, "authenticated": False, "language": "en"}
        res = await c.post("/api/session", json={"key": ""}, headers={"origin": LAN})
        assert res.status_code == 403 and "set-cookie" not in res.headers
    async with client(app, LOCAL, LOCAL_PEER) as c:
        assert (await c.get("/api/state")).status_code == 200


@pytest.mark.asyncio
async def test_the_browser_signs_in_with_the_key_and_gets_a_session_cookie(lan_app):
    from backend.security import SESSION_COOKIE, SESSION_DAYS

    app, _ = lan_app
    async with client(app, headers={"origin": LAN}) as c:
        # the page asks first, without the key: the UI shows its login in the app's language
        assert (await c.get("/api/session")).json() == {"local": False, "keyRequired": True, "keySet": True, "authenticated": False, "language": "en"}
        wrong = await c.post("/api/session", json={"key": "not the key"})
        assert wrong.status_code == 401 and wrong.json()["error"] == http_error("en", "auth_wrong")
        assert "set-cookie" not in wrong.headers
        assert (await c.post("/api/session", content=b"not json")).status_code == 401  # a broken body is a wrong key, never a 500
        ok = await c.post("/api/session", json={"key": KEY})
        assert ok.status_code == 200 and ok.json() == {"ok": True}
        cookie = ok.headers["set-cookie"]
        attrs = {a.strip().split("=")[0].lower() for a in cookie.split(";")}
        assert cookie.startswith(f"{SESSION_COOKIE}=") and KEY not in cookie
        assert {"httponly", "path", "max-age", "samesite"} <= attrs
        assert "samesite=strict" in cookie.lower() and f"max-age={SESSION_DAYS * 86400}" in cookie.lower() and "path=/" in cookie.lower()
        # the client keeps the cookie, as a browser does: the API and the stream open
        assert (await c.get("/api/state")).status_code == 200
        assert (await c.get("/api/session")).json()["authenticated"] is True
        assert (await c.post("/api/config", json={"limits": {"maxParallel": 2}})).status_code == 200


@pytest.mark.asyncio
async def test_a_forged_or_stale_cookie_is_refused(lan_app):
    from backend.security import SESSION_COOKIE, session_token

    app, _ = lan_app
    stale = session_token(KEY, time.time() - 8 * 86400)
    foreign = session_token("another-key-of-the-same-size-xyz")
    for value in (stale, foreign, KEY, "garbage", ""):
        async with client(app, cookies={SESSION_COOKIE: value}) as c:
            assert (await c.get("/api/state")).status_code == 401, value


@pytest.mark.asyncio
async def test_the_spec07_checks_still_come_first_on_the_lan(lan_app):
    app, _ = lan_app
    async with client(app, headers={"authorization": f"Bearer {KEY}"}) as c:
        assert (await c.get("/api/state", headers={"sec-fetch-site": "cross-site"})).status_code == 403
        assert (await c.post("/api/config", json={}, headers={"origin": "https://evil.example"})).status_code == 403
        assert (await c.get("/api/state", headers={"host": "evil.example"})).status_code == 403
    async with client(app) as c:
        # CSRF on the login: another site cannot sign the browser in (or probe the key)
        res = await c.post("/api/session", json={"key": KEY}, headers={"origin": "https://evil.example"})
        assert res.status_code == 403 and "set-cookie" not in res.headers


@pytest.mark.asyncio
async def test_the_page_itself_loads_on_the_lan_without_the_key(lan_app):
    # the login is part of the page: the static files are the app's code, not the owner's data
    app, _ = lan_app
    async with client(app) as c:
        assert (await c.get("/")).status_code == 200
        assert (await c.get("/js/main.js")).status_code == 200


# ---------- the guard alone: /api/events and every method ----------


async def _through_guard(scope_extra: dict, key: str = KEY) -> int:
    from backend.security import LocalGuard, allowed_hosts

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"stream"})

    guard = LocalGuard(inner, hosts=allowed_hosts(env="192.168.1.20"), key=lambda: key)
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request", "body": b""}

    scope = {"type": "http", "method": "GET", "scheme": "http", "path": "/api/events", "client": LAN_PEER, "headers": [(b"host", b"192.168.1.20:4300")]}
    scope.update(scope_extra)
    await guard(scope, receive, send)
    return sent[0]["status"]


@pytest.mark.asyncio
async def test_the_event_stream_opens_on_the_lan_only_with_a_key():
    from backend.security import SESSION_COOKIE, session_token

    assert await _through_guard({}) == 401
    assert await _through_guard({"headers": [(b"host", b"192.168.1.20:4300"), (b"authorization", f"Bearer {KEY}".encode())]}) == 200
    cookie = f"theme=night; {SESSION_COOKIE}={session_token(KEY)}".encode()
    assert await _through_guard({"headers": [(b"host", b"192.168.1.20:4300"), (b"cookie", cookie)]}) == 200
    assert await _through_guard({"headers": [(b"host", b"192.168.1.20:4300"), (b"cookie", b"aw_session=1.2; broken")]}) == 401
    assert await _through_guard({"method": "HEAD"}) == 401
    assert await _through_guard({"client": LOCAL_PEER, "headers": [(b"host", b"127.0.0.1:4300")]}) == 200
    assert await _through_guard({"path": "/js/main.js"}) == 200
    assert await _through_guard({"path": "/apis-are-not-api"}) == 200
    assert await _through_guard({"path": "/api"}) == 401
