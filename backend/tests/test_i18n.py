"""Spec 06: the backend's own texts (run messages, speech bubbles, errors,
Brain titles) in every supported language, English first and by default.
The tables must stay in lockstep: a key missing from one language would
crash a run halfway."""

import json
import re
import string

import pytest

from backend.app import ROOT

ALL = {"en", "it", "es", "fr", "de"}


def _fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def test_five_languages_english_first_and_default():
    from backend.i18n import DEFAULT, LANGUAGES

    assert set(LANGUAGES) == ALL
    assert next(iter(LANGUAGES)) == "en" and DEFAULT == "en"
    assert LANGUAGES == {"en": "English", "it": "Italian", "es": "Spanish", "fr": "French", "de": "German"}


def test_same_keys_and_placeholders_in_every_language():
    from backend.i18n import LANGUAGES, MESSAGES

    assert set(MESSAGES) == set(LANGUAGES)
    keys = set(MESSAGES["en"])
    assert keys, "the English table is empty"
    for lang, table in MESSAGES.items():
        assert set(table) == keys, f"{lang}: {sorted(set(table) ^ keys)}"
        for k in keys:
            assert _fields(table[k]) == _fields(MESSAGES["en"][k]), f"{lang}.{k}"


@pytest.mark.parametrize("lang", ["it", "es", "fr", "de"])
def test_every_table_is_really_translated(lang):
    from backend.i18n import MESSAGES

    # a copy of the English table would pass the key check: allow only the
    # few texts that are the same word in both languages ("Mission · {goal}")
    same = [k for k, v in MESSAGES[lang].items() if v == MESSAGES["en"][k]]
    assert len(same) <= 3, same


def test_tr_formats_and_defaults_to_english():
    from backend.i18n import MESSAGES, tr

    key = "resumed"
    assert tr("it", key) == MESSAGES["it"][key]
    assert tr("de", key) == MESSAGES["de"][key]
    assert tr(None, key) == MESSAGES["en"][key]  # no language chosen: the default, English
    assert "w3" in tr("fr", "ws_done", id="w3", title="Site")


@pytest.mark.parametrize("bad", ["xx", "EN", "", 3])
def test_tr_rejects_an_unknown_language(bad):
    from backend.i18n import tr

    with pytest.raises(ValueError):
        tr(bad, "resumed")


def test_english_table_has_no_italian_left():
    from backend.i18n import MESSAGES

    italian = re.compile(r"[àèéìòù]|\b(il|della|sono|non|per|con|che)\b", re.IGNORECASE)
    leftovers = {k: v for k, v in MESSAGES["en"].items() if italian.search(v)}
    assert not leftovers


def test_team_label_translates_known_teams_and_falls_back_to_config():
    from backend.i18n import team_label

    cfg = {"teams": {"research": {"label": "Ricerca"}, "custom": {"label": "Su misura"}}}
    assert team_label(cfg, "research", "en") == "Research"
    assert team_label(cfg, "research", "es") == "Investigación"
    assert team_label(cfg, "research", "fr") == "Recherche"
    assert team_label(cfg, "research", "de") == "Recherche"
    assert team_label(cfg, "research", "it") == "Ricerca"  # Italian: the config label (D3)
    assert team_label(cfg, "research", None) == "Research"  # the default language
    assert team_label(cfg, "custom", "de") == "Su misura"  # D3: config label as fallback
    assert team_label(cfg, "ghost", "en") == "ghost"


def test_every_language_names_every_team():
    from backend.i18n import LANGUAGES, TEAM_LABELS

    teams = set(TEAM_LABELS["en"])
    for lang in set(LANGUAGES) - {"it"}:
        assert set(TEAM_LABELS[lang]) == teams, lang


def test_frontend_and_backend_offer_the_same_languages():
    """The UI builds its selectors from LANGS in i18n.js; the backend refuses
    any code outside LANGUAGES. A language in only one of them would be a
    choice that fails with a 400, or one nobody can pick."""
    from backend.i18n import LANGUAGES

    js = (ROOT / "public" / "js" / "i18n.js").read_text(encoding="utf-8")
    m = re.search(r"export const LANGS = \{([^}]*)\}", js)
    assert m, "LANGS not found in i18n.js"
    codes = re.findall(r"(\w+):\s*'", m.group(1))
    assert codes == list(LANGUAGES)  # same codes, same order (English first)


# ---------- N13: HTTP errors in the language of the app ----------
# The UI shows body.error in a toast next to its own translated text, so an
# error speaks the language the owner chose for the whole app (ui.language),
# whatever the language of the run it is about; English when none is set.

ITALIAN = re.compile(r"[àèéìòù]|\b(il|della|sono|non|per|con|che|una|deve|manca|vuoto|questo|questa|squadra|scrivi|trovato|serve|altro|sconosciut\w*|rifiutat\w*)\b", re.IGNORECASE)


def test_http_errors_have_the_same_keys_and_placeholders_in_every_language():
    from backend.i18n import HTTP_ERRORS, LANGUAGES

    assert set(HTTP_ERRORS) == set(LANGUAGES)
    keys = set(HTTP_ERRORS["en"])
    assert len(keys) >= 40, "every error the routes write has its own key"
    for lang, table in HTTP_ERRORS.items():
        assert set(table) == keys, f"{lang}: {sorted(set(table) ^ keys)}"
        for k in keys:
            assert _fields(table[k]) == _fields(HTTP_ERRORS["en"][k]), f"{lang}.{k}"


@pytest.mark.parametrize("lang", ["it", "es", "fr", "de"])
def test_http_errors_are_really_translated(lang):
    from backend.i18n import HTTP_ERRORS

    same = [k for k, v in HTTP_ERRORS[lang].items() if v == HTTP_ERRORS["en"][k]]
    assert len(same) <= 2, same


def test_english_http_errors_have_no_italian_left():
    from backend.i18n import HTTP_ERRORS

    assert not {k: v for k, v in HTTP_ERRORS["en"].items() if ITALIAN.search(v)}


@pytest.mark.parametrize(
    "cfg,lang",
    [
        ({"ui": {"language": "de"}}, "de"),
        ({"ui": {"language": "it"}}, "it"),
        ({}, "en"),
        ({"ui": None}, "en"),
        ({"ui": {}}, "en"),
        ({"ui": {"language": None}}, "en"),
        ({"ui": {"language": "xx"}}, "en"),  # a hand-edited local.json must not turn an error into a 500
        ({"ui": {"language": ["de"]}}, "en"),
    ],
)
def test_the_language_of_http_errors_is_the_app_language_or_english(cfg, lang):
    from backend.i18n import ui_language

    assert ui_language(cfg) == lang


def test_http_error_formats_and_never_raises_on_a_bad_language():
    from backend.i18n import HTTP_ERRORS, http_error

    assert http_error("it", "run_not_found") == HTTP_ERRORS["it"]["run_not_found"]
    assert http_error("de", "too_many_files", n=3, max=3) == HTTP_ERRORS["de"]["too_many_files"].format(n=3, max=3)
    for bad in (None, "xx", "", ["de"], 3):
        assert http_error(bad, "run_not_found") == HTTP_ERRORS["en"]["run_not_found"]


def _string_literals(path):
    """Every string constant of a module except its docstrings."""
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_no_italian_error_is_left_in_the_http_layer():
    """The guard behind N13: a new route that writes its error in Italian
    (or in any one language) instead of a key of HTTP_ERRORS turns this red."""
    backend = ROOT / "backend" / "backend"
    files = sorted((backend / "routes").glob("*.py")) + [backend / "security.py", backend / "attachments.py"]
    leftovers = {f.name: hits for f in files if (hits := [s for s in _string_literals(f) if ITALIAN.search(s)])}
    assert not leftovers


@pytest.fixture
def app_in(tmp_path):
    """The real app, with ui.language set to the language under test (the
    preferences file is the test's own: conftest.py, N15)."""
    from backend.app import create_app
    from backend.brain import Brain
    from backend.config import Config
    from backend.store import Store

    def make(lang):
        config = Config(ROOT / "config")
        config.update({"ui": {"language": lang}})
        store = Store(tmp_path)
        return create_app(config=config, store=store, brain=Brain(tmp_path / "brain.json")), store, config

    return make


def _client(app, base="http://127.0.0.1:4300"):
    import httpx

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base)


# (method, path, request kwargs, status, key, vars): one refusal of every kind of route
REFUSALS = [
    ("post", "/api/runs", {"json": {"goal": "ab"}}, 400, "goal_missing", {}),
    ("post", "/api/runs", {"json": {"goal": "A site for my bar", "language": "xx"}}, 400, "language_unsupported", {"value": "'xx'", "choices": "en, it, es, fr, de"}),
    ("post", "/api/runs", {"json": {"goal": "A site for my bar", "attachments": ["0123456789ab"]}}, 400, "upload_gone", {}),
    ("get", "/api/runs/nope", {}, 404, "run_not_found", {}),
    ("post", "/api/runs/nope/explode", {}, 404, "unknown_endpoint", {}),
    ("post", "/api/runs/nope/refine", {"json": {"text": "x"}}, 404, "run_not_found", {}),
    ("post", "/api/chat/nobody", {"json": {"text": "hi"}}, 404, "agent_not_found", {}),
    ("post", "/api/chat/ada", {"json": {"text": "  "}}, 400, "message_empty", {}),
    ("post", "/api/uploads", {"content": b"hello"}, 400, "upload_name_missing", {}),
    ("post", "/api/uploads?name=tool.exe", {"content": b"MZ"}, 400, "file_type_refused", {"name": "'tool.exe'", "allowed": None}),
    ("post", "/api/uploads?name=empty.txt", {"content": b""}, 400, "file_empty", {"name": "'empty.txt'"}),
    ("post", "/api/uploads?name=photo.png", {"content": b"not a png at all"}, 400, "file_content_mismatch", {"name": "'photo.png'", "ext": ".png"}),
    ("post", "/api/config", {"json": {"ui": {"language": "xx"}}}, 400, "language_unsupported", {"value": "'xx'", "choices": "en, it, es, fr, de"}),
    ("post", "/api/config", {"json": {"combos": {"fast": {"models": ["no-slash"]}}}}, 400, "combo_models", {"name": "fast"}),
    ("post", "/api/providers", {"json": {"id": "Bad Id", "models": ["m"]}}, 400, "provider_id_invalid", {}),
    ("post", "/api/providers", {"json": {"id": "mybox", "baseUrl": "http://api.example.test/v1", "keyEnv": "MYBOX_API_KEY", "models": ["m"]}}, 400, "provider_url_https", {}),
    ("post", "/api/providers", {"json": {"id": "mybox", "baseUrl": "https://api.example.test/v1", "keyEnv": "lower", "models": ["m"]}}, 400, "provider_key_format", {}),
    ("delete", "/api/providers/ghost", {}, 404, "provider_not_found", {}),
    ("delete", "/api/providers/openai", {}, 400, "provider_shipped_remove", {"pid": "openai"}),
    ("post", "/api/skills/repo", {"json": {"url": "not a url"}}, 400, "repo_url_invalid", {}),
    ("get", "/api/skills/read?id=nope-t02", {}, 404, "skill_not_found", {"name": "nope-t02"}),
    ("post", "/api/brain", {"json": {"title": "A", "text": "  "}}, 400, "note_empty", {}),
]


@pytest.mark.parametrize("lang", ["en", "it", "es", "fr", "de"])
@pytest.mark.parametrize("method,path,kwargs,status,key,vars", REFUSALS, ids=[f"{r[0]} {r[1]} {r[4]}" for r in REFUSALS])
async def test_every_route_refuses_in_the_language_of_the_app(app_in, lang, method, path, kwargs, status, key, vars):
    from backend.attachments import EXT_KIND
    from backend.i18n import http_error

    if "allowed" in vars:
        vars = {**vars, "allowed": ", ".join(sorted(EXT_KIND))}
    app, _, _ = app_in(lang)
    async with _client(app) as c:
        res = await getattr(c, method)(path, **kwargs) if kwargs else await getattr(c, method)(path)
    assert res.status_code == status, res.text
    assert res.json()["error"] == http_error(lang, key, **vars)


@pytest.mark.parametrize("lang", ["en", "it", "es", "fr", "de"])
async def test_the_spec07_refusals_speak_the_language_of_the_app(app_in, lang):
    from backend.i18n import http_error

    app, _, _ = app_in(lang)
    async with _client(app, base="http://evil.example:4300") as c:
        host = await c.get("/api/state")
    async with _client(app) as c:
        site = await c.get("/api/state", headers={"sec-fetch-site": "cross-site"})
        origin = await c.post("/api/config", json={}, headers={"origin": "https://evil.example"})
    assert [r.status_code for r in (host, site, origin)] == [403, 403, 403]
    assert host.json()["error"] == http_error(lang, "refused_host")
    assert site.json()["error"] == http_error(lang, "refused_site")
    assert origin.json()["error"] == http_error(lang, "refused_origin")


@pytest.mark.parametrize("lang", ["en", "it", "es", "fr", "de"])
async def test_the_lan_refusals_speak_the_language_of_the_app(app_in, lang, monkeypatch):
    """Spec 11 T02: the access key on the LAN. The login dialog shows these
    texts as they are, so they follow the app like every other error."""
    import httpx

    from backend.i18n import http_error

    monkeypatch.setenv("AGENT_WORLD_ALLOWED_HOSTS", "studio.lan")
    monkeypatch.setenv("AGENT_WORLD_API_KEY", "t02-access-key-0123456789abcdef")
    app, _, _ = app_in(lang)
    lan = httpx.ASGITransport(app=app, client=("192.168.1.30", 51000))
    async with httpx.AsyncClient(transport=lan, base_url="http://studio.lan:4300") as c:
        needed = await c.get("/api/state")
        wrong = await c.post("/api/session", json={"key": "nope"}, headers={"origin": "http://studio.lan:4300"})
        monkeypatch.delenv("AGENT_WORLD_API_KEY")
        closed = await c.get("/api/state")
        session = (await c.get("/api/session")).json()
    assert [r.status_code for r in (needed, wrong, closed)] == [401, 401, 403]
    assert needed.json()["error"] == http_error(lang, "auth_required")
    assert wrong.json()["error"] == http_error(lang, "auth_wrong")
    assert closed.json()["error"] == http_error(lang, "lan_needs_key")
    assert session["language"] == lang  # the login dialog speaks it before the page can read the config


@pytest.mark.parametrize("lang", ["en", "it", "de"])
async def test_the_static_refusals_speak_the_language_of_the_app(app_in, lang):
    """N13, closed by spec 11 T02: the plain texts of the file server were
    "Forbidden" and "Not found" in every language."""
    from backend.i18n import http_error

    app, _, _ = app_in(lang)
    async with _client(app) as c:
        refused = await c.get("/css/app.css:hidden")  # ':' is refused on every system (N16)
        missing = await c.get("/no-such-page-t02.html")
    assert refused.status_code == 403 and refused.text == http_error(lang, "forbidden")
    assert missing.status_code == 404 and missing.text == http_error(lang, "not_found")


@pytest.mark.parametrize("lang", ["en", "it", "fr"])
async def test_the_gateway_refusals_speak_the_language_of_the_app(app_in, lang, monkeypatch):
    """N13, closed by spec 11 T02: /v1 keeps the OpenAI shape of its errors,
    with the text in the language of the app."""
    from backend.i18n import http_error

    app, _, _ = app_in(lang)
    async with _client(app) as c:
        no_messages = await c.post("/v1/chat/completions", json={"model": "combo:fast"})
        monkeypatch.setenv("AGENT_WORLD_API_KEY", "t02-access-key-0123456789abcdef")
        no_key = await c.get("/v1/models")
    assert no_messages.status_code == 400 and no_messages.json() == {"error": {"message": http_error(lang, "messages_required")}}
    assert no_key.status_code == 401 and no_key.json() == {"error": {"message": http_error(lang, "api_key_invalid")}}


@pytest.mark.parametrize("lang", ["en", "it", "es"])
async def test_the_skill_downloads_refuse_in_the_language_of_the_app(app_in, lang, monkeypatch, tmp_path):
    """The sentence is the app's; what the download layer found (an archive
    entry, a limit, a folder) is a technical detail and stays as it is."""
    import backend.skills as skills_mod
    from backend.i18n import http_error

    monkeypatch.delenv("CUSTOM_DOWNLOAD_PATH", raising=False)

    async def git_fails(args):
        raise RuntimeError("git exited with 128: repository not found")

    monkeypatch.setattr(skills_mod, "_git", git_fails)
    app, _, _ = app_in(lang)
    app.state.skills.vendor_dir = tmp_path / "vendor"  # N15: add_repo makes this folder, never the repo's skills/vendor/
    async with _client(app) as c:
        refused = await c.post("/api/skills/skiller/approve", json={"slug": "nobody/unknown"})
        failed = await c.post("/api/skills/repo", json={"url": "https://github.com/nobody/no-such-repo-t02"})
    assert refused.status_code == 400
    assert refused.json()["error"] == http_error(lang, "download_refused", detail="downloads are off: CUSTOM_DOWNLOAD_PATH is not set")
    # a git that fails (no such repo, no network) was a bare 500 with an Italian log line
    assert failed.status_code == 502
    assert failed.json()["error"] == http_error(lang, "repo_failed", detail="git exited with 128: repository not found")


def test_every_http_refusal_is_built_from_the_dictionary():
    """The guard behind N13 (spec 11 T02): in the routes, a response with a
    4xx status writes its text through http_error (directly or through the
    route's _err), never a literal or the str() of an exception. A 5xx may
    carry the upstream's own text (a provider's error, as it answered)."""
    import ast

    backend = ROOT / "backend" / "backend"
    found = {}
    for f in sorted((backend / "routes").glob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("JSONResponse", "PlainTextResponse") and node.args):
                continue
            status = next((k.value for k in node.keywords if k.arg == "status_code"), None)
            if not (isinstance(status, ast.Name) or (isinstance(status, ast.Constant) and 400 <= status.value < 500)):
                continue
            text = node.args[0]
            while isinstance(text, ast.Dict):  # {"error": ...} or, on /v1, {"error": {"message": ...}}
                keys = [k.value for k in text.keys if isinstance(k, ast.Constant)]
                field = "error" if "error" in keys else "message" if "message" in keys else None
                if field is None:
                    break
                text = text.values[keys.index(field)]
            if not (isinstance(text, ast.Call) and getattr(text.func, "id", None) == "http_error"):
                found.setdefault(f.name, []).append(ast.unparse(node)[:120])
    assert not found


@pytest.mark.parametrize("lang", ["en", "fr"])
async def test_the_preview_of_an_unknown_run_says_so_in_the_language_of_the_app(app_in, lang):
    from backend.i18n import http_error

    app, _, _ = app_in(lang)
    async with _client(app) as c:
        res = await c.get("/preview/nope/")
    assert res.status_code == 404 and res.text == http_error(lang, "run_not_found")


async def test_an_error_about_a_run_follows_the_app_not_the_run(app_in):
    """The run keeps the language it started with (D1), but the toast that
    shows the error is in the UI's language: the error goes with the UI."""
    from backend.i18n import http_error

    app, store, _ = app_in("de")
    store.save({"id": "r1", "goal": "Un sito", "language": "it", "status": "completed", "tasks": [], "workstreams": []}, immediate=True)
    async with _client(app) as c:
        res = await c.post("/api/runs/r1/stop")
    assert res.status_code == 409 and res.json()["error"] == http_error("de", "run_not_active")


async def test_a_language_switch_changes_the_errors_at_once(app_in):
    from backend.i18n import http_error

    app, _, _ = app_in("en")
    async with _client(app) as c:
        before = (await c.get("/api/runs/nope")).json()["error"]
        assert (await c.post("/api/config", json={"ui": {"language": "es"}})).status_code == 200
        after = (await c.get("/api/runs/nope")).json()["error"]
    assert (before, after) == (http_error("en", "run_not_found"), http_error("es", "run_not_found"))


# ---------- N17: the last texts written in one language ----------


@pytest.mark.parametrize("lang", ["en", "it", "es", "fr", "de"])
async def test_an_invalid_answer_is_noted_in_the_language_of_the_run(lang):
    """A model that answers no JSON leaves a note in the task's timeline: it is
    the run's own text, like every other run message."""
    from test_tasker import AGENT, TASK, FakeRun  # the tasker's own stand-in run (tests/ is on sys.path)

    from backend.i18n import tr
    from backend.tasker import Tasker

    run = FakeRun(
        [
            "this is not JSON",
            json.dumps({"thought": "write", "tool": "write_file", "args": {"path": "out.md", "content": "x"}}),
            json.dumps({"thought": "deliver", "tool": "finish", "args": {"summary": "Done", "files": ["out.md"]}}),
        ]
    )
    run.data["language"] = lang
    await Tasker(run, dict(TASK, history=[]), AGENT).work()
    assert ("error", tr(lang, "invalid_answer")) in run.notes


def test_a_busy_port_is_explained_in_the_language_of_the_app(tmp_path):
    """`npm start` on a busy port: the owner reads why it stopped in the language
    chosen in the app (ui.language of the preferences file)."""
    import os
    import socket
    import subprocess
    import sys

    from backend.i18n import tr

    local = tmp_path / "local.json"
    local.write_text(json.dumps({"ui": {"language": "de"}}), encoding="utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        env = {**os.environ, "PORT": str(port), "AGENT_WORLD_SKILLER": "0", "PYTHONIOENCODING": "utf-8", "AGENT_WORLD_LOCAL_CONFIG": str(local)}
        r = subprocess.run([sys.executable, "-m", "backend"], cwd=ROOT / "backend", env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 1, r.stdout + r.stderr
    assert tr("de", "port_busy", port=port) in r.stderr


# Literals that are data, not texts for anyone to read: stopwords and the sample
# texts of the Rust parity probes, a provider's error pattern, a Windows reserved
# name. Matched by their start, file by file, so a new message next to them is seen.
DATA_LITERALS = {
    "downloads.py": ("CON",),
    "embed.py": ("Caffè e tipografia", "il la di"),
    "prompts.py": (", the CEO of an autonomous AI company",),
    "router/providers.py": ("per ?minute",),
    "search.py": ("the and for with", "Più cose per una pizza", "ricetta della tradizione", "il la di un per"),
    # spec 11 T06-T07: a probe of readable strings in bytes, an npm script name
    "deconstructor.py": ("città",),
    "tools.py": ("serve",),
}
# the language tables themselves, the demo's goal keywords and (spec 10) the
# hiring matcher's subtask keywords, both in five languages
TABLES = {"i18n.py", "router/mock_texts.py", "router/mock.py", "router/hiring.py", "intent.py"}  # spec 11 T09: the intent cues, five languages
LOG_WORDS = re.compile(r"\b(riprovo|rispost\w*|porta|indicizzat\w*|scaricat\w*|predefinit\w*|valutat\w*|approvat\w*|fallit\w*|giro|spent[io]|ignorat\w*)\b", re.IGNORECASE)


def test_no_italian_text_is_left_in_the_backend():
    """N17: the guard of N13 over every module of the backend. What the owner
    reads goes through i18n (run messages, HTTP errors, the port message); a
    console log is English, like the code."""
    backend = ROOT / "backend" / "backend"
    leftovers = {}
    for f in sorted(backend.rglob("*.py")):
        rel = f.relative_to(backend).as_posix()
        if rel in TABLES:
            continue
        allowed = DATA_LITERALS.get(rel, ())
        hits = [s for s in _string_literals(f) if (ITALIAN.search(s) or LOG_WORDS.search(s)) and not s.startswith(allowed)]
        if hits:
            leftovers[rel] = hits
    assert not leftovers


def test_attachment_errors_carry_their_key_and_read_in_english():
    """attachments.check runs below the routes, which translate it; its own
    text (logs, a stack trace) is English."""
    from backend import attachments
    from backend.i18n import http_error

    with pytest.raises(attachments.AttachmentError) as err:
        attachments.check("empty.txt", b"", max_mb=25)
    assert err.value.key == "file_empty" and err.value.vars == {"name": "'empty.txt'"}
    assert str(err.value) == http_error("en", "file_empty", name="'empty.txt'")
