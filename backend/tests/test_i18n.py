"""Spec 06: the backend's own texts (run messages, speech bubbles, errors,
Brain titles) in every supported language, English first and by default.
The tables must stay in lockstep: a key missing from one language would
crash a run halfway."""

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


def test_attachment_errors_carry_their_key_and_read_in_english():
    """attachments.check runs below the routes, which translate it; its own
    text (logs, a stack trace) is English."""
    from backend import attachments
    from backend.i18n import http_error

    with pytest.raises(attachments.AttachmentError) as err:
        attachments.check("empty.txt", b"", max_mb=25)
    assert err.value.key == "file_empty" and err.value.vars == {"name": "'empty.txt'"}
    assert str(err.value) == http_error("en", "file_empty", name="'empty.txt'")
