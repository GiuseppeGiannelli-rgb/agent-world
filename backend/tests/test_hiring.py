"""Spec 10: every subtask "hires" its own model.

- The profiler gives each model a competence matrix: its size (paramsB from
  the name, sizeB also from the family), its specialties from 0 to 1
  (reasoning, coding, creative, research, vision, toolUse, speed) and its cost
  tier (local, free, low, high). The router adds the health of this session:
  calls, successes, latency, and whether it is cooling, benched or dead.
- router/hiring.py reads a subtask (title, description, files, skills, team,
  revisions) and ranks the ready models of the catalog for it: a dedicated
  chain, the team's combo and the cascade after it.
- When the hired model fails mid-step, the next compatible candidate takes
  the very next try, and the task records the replacement.

The providers here are fake servers (httpx.MockTransport)."""

import httpx
import pytest
from test_run import demo_ctx  # noqa: F401 -- the demo fixture of test_run.py (tests/ is on sys.path)

from backend.router import profiler


class FakeConfig:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


# ---------- R1: the competence matrix ----------


@pytest.mark.parametrize(
    "key,size,source,cost",
    [
        ("ollama/qwen2.5-coder:7b", 7, "name", "local"),
        ("openrouter/meta-llama/llama-3.3-70b-instruct:free", 70, "name", "free"),
        ("groq/openai/gpt-oss-120b", 120, "name", "free"),
        ("anthropic/claude-opus-5-5", 400, "family", "high"),
        ("openai/gpt-5", 400, "family", "high"),
        ("anthropic/claude-sonnet-5-5", 120, "family", "low"),
        ("deepseek/deepseek-chat", 120, "family", "low"),
        ("anthropic/claude-haiku-5-5", 24, "family", "low"),
        ("gemini/gemini-2.5-flash", 24, "family", "free"),
        ("mistral/codestral-latest", 32, "family", "low"),
        ("together/meta-llama/Llama-3.3-70B-Instruct-Turbo", 70, "name", "low"),  # open weights: big, not premium
        ("openai/o3", 400, "family", "high"),
    ],
)
def test_the_size_and_the_cost_of_a_model(key, size, source, cost):
    p = profiler.profile(key)
    assert (p["sizeB"], p["sizeSource"], p["costTier"]) == (size, source, cost), p


def test_specialties_are_scores_between_0_and_1_for_every_model():
    keys = ["ollama/qwen3:8b", "anthropic/claude-opus-5-5", "groq/llama-3.1-8b-instant", "openai/o3", "perplexity/sonar-pro", "gemini/gemini-2.5-flash", "mistral/codestral-latest"]
    for key in keys:
        s = profiler.profile(key)["specialties"]
        assert set(s) == {"reasoning", "coding", "creative", "research", "vision", "toolUse", "speed"}, key
        assert all(isinstance(v, float) and 0.0 <= v <= 1.0 for v in s.values()), (key, s)


def test_the_specialties_follow_the_family_and_the_size():
    sp = lambda key: profiler.profile(key)["specialties"]  # noqa: E731
    coder7, coder32, chat8 = sp("ollama/qwen2.5-coder:7b"), sp("ollama/qwen2.5-coder:32b"), sp("ollama/llama3.1:8b")
    assert coder32["coding"] > coder7["coding"] > chat8["coding"]  # a coder, and a bigger one, code better
    assert sp("openai/o3")["reasoning"] > sp("openai/gpt-4o")["reasoning"]  # a reasoning model reasons
    assert sp("perplexity/sonar-pro")["research"] > sp("anthropic/claude-haiku-5-5")["research"]  # web search built in
    assert sp("groq/llama-3.1-8b-instant")["speed"] > sp("anthropic/claude-opus-5-5")["speed"]  # small, on a fast provider
    assert sp("ollama/llama3.1:8b")["vision"] == 0.0 and sp("gemini/gemini-2.5-flash")["vision"] > 0.4
    assert sp("anthropic/claude-sonnet-5-5")["toolUse"] > sp("ollama/qwen3:4b")["toolUse"]  # the JSON of the actions


# ---------- R1: the catalog and the health of this session ----------


@pytest.fixture
def catalog_router(tmp_path, monkeypatch):
    from backend.router.index import Router

    monkeypatch.setenv("BIG_KEY", "k")
    monkeypatch.setenv("FREE_KEY", "k")
    monkeypatch.delenv("NONE_KEY", raising=False)
    value = {
        "router": {"defaultCombo": "fast", "demoFallback": True, "cooldownBaseMs": 60000, "cooldownMaxMs": 60000, "authCooldownMs": 60000, "quotaCooldownMs": 60000, "logCalls": False, "discoverMax": 6, "aliases": {"big/claude-opus-5-5": ["big/claude-sonnet-5-5"]}},
        "providers": {
            "mock": {"kind": "mock", "latencyMs": [1, 2]},
            "big": {"kind": "openai", "baseUrl": "http://big/v1", "keyEnv": "BIG_KEY"},
            "free": {"kind": "openai", "baseUrl": "http://free/v1", "keyEnv": "FREE_KEY"},
            "none": {"kind": "openai", "baseUrl": "http://none/v1", "keyEnv": "NONE_KEY"},
            "typesafe": {"kind": "typesafe", "baseUrl": "http://ts/v1", "keyEnv": "BIG_KEY"},
        },
        "combos": {
            "frontier": {"models": ["big/claude-opus-5-5", "free/llama-3.3-70b:free"]},
            "fast": {"models": ["free/llama-3.1-8b:free", "none/model-x", "mock/mock-any"]},
        },
        "teams": {},
    }
    return Router(config=FakeConfig(value), data_dir=tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))


def test_the_catalog_lists_every_model_once_with_its_matrix(catalog_router):
    r = catalog_router
    r.discovered["free"] = [profiler.profile("free/qwen2.5-coder:32b:free"), profiler.profile("free/nomic-embed-text")]
    cat = {m["key"]: m for m in r.catalog()}
    # combos, aliases and found models, once each; not the simulator, not TypeSafe, not an embedding model
    assert set(cat) == {"big/claude-opus-5-5", "big/claude-sonnet-5-5", "free/llama-3.3-70b:free", "free/llama-3.1-8b:free", "none/model-x", "free/qwen2.5-coder:32b:free"}
    m = cat["big/claude-opus-5-5"]
    for field in ("paramsB", "sizeB", "sizeSource", "tier", "specialties", "costTier", "context", "ready", "health", "combos"):
        assert field in m, field
    assert m["combos"] == ["frontier"] and cat["big/claude-sonnet-5-5"]["combos"] == []
    assert cat["none/model-x"]["ready"] is False and cat["none/model-x"]["health"]["state"] == "unready"
    assert "meta" not in m


def test_the_health_follows_the_calls_of_the_session(catalog_router):
    from backend.router.providers import ProviderError

    r = catalog_router
    big, free = {"provider": "big", "model": "claude-opus-5-5", "key": "big/claude-opus-5-5"}, {"provider": "free", "model": "llama-3.1-8b:free", "key": "free/llama-3.1-8b:free"}
    assert r.health(big["key"]) == {"calls": 0, "ok": 0, "fail": 0, "successRate": None, "avgMs": None, "state": "ok", "reason": None}
    r.record(big, ok=True, ms=100)
    r.record(big, ok=True, ms=300)
    r.record(big, ok=False, ms=200, error="boom")
    h = r.health(big["key"])
    assert (h["calls"], h["ok"], h["fail"], h["successRate"], h["avgMs"]) == (3, 2, 1, 0.67, 200)
    r.cool(free, ProviderError("slow down", kind="rate_limit", retryable=True))
    assert r.health(free["key"])["state"] == "cooling"
    r.cool(big, ProviderError("no credit", kind="quota"))
    assert (r.health(big["key"])["state"], r.health(big["key"])["reason"]) == ("benched", "quota_exhausted")
    r.cool(free, ProviderError("gone", kind="model_not_found"))
    assert r.health(free["key"])["state"] == "dead"


def test_the_router_snapshot_carries_the_catalog(catalog_router):
    snap = catalog_router.snapshot()
    assert {"mode", "providers", "combos", "recent", "catalog"} <= set(snap)
    assert any(m["key"] == "big/claude-opus-5-5" for m in snap["catalog"])


# ---------- R2: reading a subtask ----------


def task(**fields):
    from backend.plan import new_task

    base = {"id": "w1.1", "wsId": "w1", "team": "content", "title": "Nota", "description": "", "acceptance": [], "outputs": [], "dependsOn": []}
    return new_task({**base, **fields})


CFG_TEAMS = {
    "teams": {
        "dev": {"tools": ["run_command", "web_fetch"]},
        "research": {"tools": ["web_search", "web_fetch"]},
        "content": {"tools": ["web_search"]},
        "design": {"tools": []},
        "genai": {"tools": ["generate_image", "generate_speech"]},
        "prompt": {"tools": []},
    }
}

BIG_DEV = dict(
    team="dev",
    title="Backend completo con API, database e autenticazione",
    description="Implementa il backend completo: API REST con autenticazione, database, validazione, gestione degli errori e test automatici. Deve integrarsi con il front-end e rispettare i requisiti di sicurezza.",
    acceptance=["Le API rispondono", "I test passano", "Gli errori sono gestiti", "Sicurezza verificata"],
    outputs=["api/server.py", "api/db.py", "api/auth.py", "tests/test_api.py"],
    dependsOn=["w0.1"],
)
SMALL_NOTE = dict(team="content", title="Breve nota di benvenuto", description="Scrivi una breve nota di benvenuto per il sito.", outputs=["notes/benvenuto.md"])


@pytest.mark.parametrize(
    "fields,category",
    [
        (BIG_DEV, "coding"),
        (dict(team="dev", title="Build the landing page", description="Write index.html, style.css and app.js", outputs=["index.html", "css/style.css", "js/app.js"]), "coding"),
        (dict(team="research", title="Analisi della concorrenza", description="Ricerca i concorrenti e confronta prezzi e recensioni", outputs=["research/competitors.md"]), "research"),
        (dict(team="research", title="Análisis de la competencia", description="Investiga el mercado y compara precios", outputs=["research/mercado.md"]), "research"),
        (dict(team="content", title="Testi della home", description="Scrivi i testi e lo slogan della home", outputs=["content/home.md"]), "creative"),
        (dict(team="content", title="Textes de la page d'accueil", description="Écris le slogan et les titres", outputs=["content/accueil.md"]), "creative"),
        (dict(team="prompt", title="Strategie und Architektur", description="Plane die Architektur und bewerte die Optionen logisch", outputs=["notes/plan.md"]), "reasoning"),
    ],
)
def test_the_category_of_a_subtask(fields, category):
    from backend.router import hiring

    assert hiring.analyze(task(**fields), CFG_TEAMS)["category"] == category


def test_the_level_follows_the_size_of_the_work_and_the_revisions():
    from backend.router import hiring

    big, small = hiring.analyze(task(**BIG_DEV), CFG_TEAMS), hiring.analyze(task(**SMALL_NOTE), CFG_TEAMS)
    assert (big["level"], small["level"]) == ("complex", "simple"), (big, small)
    assert 0.0 <= small["complexity"] < big["complexity"] <= 1.0
    revised = hiring.analyze(task(**SMALL_NOTE, revisions=2), CFG_TEAMS)
    assert revised["complexity"] > small["complexity"]  # every revision asks for more
    assert hiring.analyze(task(**SMALL_NOTE, escalated=True), CFG_TEAMS)["level"] == "complex"  # an escalation is complex
    assert set(big["needs"]) <= {"reasoning", "coding", "creative", "research", "vision", "toolUse", "speed"}
    assert "toolUse" in big["needs"]  # every worker answers with JSON actions


# ---------- R2: the chain of one subtask ----------


@pytest.fixture
def market(tmp_path, monkeypatch):
    """A router with a real-looking market: premium, mid, free, fast and local models."""
    from backend.router.index import Router

    for k in ("ANTHROPIC_KEY", "OPENROUTER_KEY", "GROQ_KEY"):
        monkeypatch.setenv(k, "k")
    monkeypatch.delenv("NOKEY_KEY", raising=False)
    value = {
        "router": {"defaultCombo": "fast", "demoFallback": True, "cooldownBaseMs": 60000, "cooldownMaxMs": 60000, "authCooldownMs": 60000, "quotaCooldownMs": 60000, "logCalls": False, "discoverMax": 6, "hiring": {"enabled": True, "chain": 6}},
        "providers": {
            "mock": {"kind": "mock", "latencyMs": [1, 2]},
            "anthropic": {"kind": "openai", "baseUrl": "http://anthropic/v1", "keyEnv": "ANTHROPIC_KEY"},
            "openrouter": {"kind": "openai", "baseUrl": "http://openrouter/v1", "keyEnv": "OPENROUTER_KEY"},
            "groq": {"kind": "openai", "baseUrl": "http://groq/v1", "keyEnv": "GROQ_KEY"},
            "ollama": {"kind": "openai", "baseUrl": "http://ollama/v1", "keyless": True, "local": True},
            "nokey": {"kind": "openai", "baseUrl": "http://nokey/v1", "keyEnv": "NOKEY_KEY"},
        },
        "combos": {
            "frontier": {"models": ["anthropic/claude-opus-5-5", "nokey/giant-405b"]},
            "smart": {"models": ["anthropic/claude-sonnet-5-5"]},
            "code": {"models": ["openrouter/qwen/qwen-2.5-coder-32b-instruct:free"]},
            "fast": {"models": ["groq/llama-3.1-8b-instant"]},
            "free": {"models": ["openrouter/meta-llama/llama-3.3-70b-instruct:free"]},
            "local": {"models": ["ollama/qwen3:8b"]},
        },
        "teams": CFG_TEAMS["teams"],
    }
    return Router(config=FakeConfig(value), data_dir=tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))))


def test_a_complex_coding_subtask_hires_a_big_model(market):
    from backend.router import hiring

    rec = hiring.hire(task(**BIG_DEV), market.cfg, market)
    assert rec["demo"] is False and rec["level"] == "complex" and rec["category"] == "coding"
    chosen = next(m for m in market.catalog() if m["key"] == rec["chosen"])
    assert chosen["sizeB"] >= 32 and chosen["tier"] in ("frontier", "smart", "code"), rec
    assert all(c["sizeB"] >= 32 for c in rec["chain"][:3]), rec["chain"]  # the first candidates are all big enough
    assert "nokey/giant-405b" not in [c["key"] for c in rec["chain"]]  # no key: never hired


def test_a_simple_subtask_hires_a_free_or_local_model_and_spares_the_paid_quota(market):
    from backend.router import hiring

    rec = hiring.hire(task(**SMALL_NOTE), market.cfg, market)
    assert rec["level"] == "simple"
    chosen = next(m for m in market.catalog() if m["key"] == rec["chosen"])
    assert chosen["costTier"] in ("free", "local"), rec
    keys = [c["key"] for c in rec["chain"]]
    assert "anthropic/claude-opus-5-5" not in keys or keys.index("anthropic/claude-opus-5-5") > keys.index(rec["chosen"])  # the premium model at most as a later option


def test_the_chain_is_short_ordered_and_always_the_same(market):
    from backend.router import hiring

    a, b = hiring.hire(task(**BIG_DEV), market.cfg, market), hiring.hire(task(**BIG_DEV), market.cfg, market)
    assert a["chain"] == b["chain"] and 1 <= len(a["chain"]) <= 6
    scores = [c["score"] for c in a["chain"]]
    assert scores == sorted(scores, reverse=True)
    assert a["chosen"] == a["chain"][0]["key"]
    for c in a["chain"]:
        assert {"key", "score", "fit", "tier", "sizeB", "costTier"} <= set(c)


def test_unhealthy_models_leave_the_chain_or_go_last(market):
    from backend.router import hiring
    from backend.router.providers import ProviderError

    first = hiring.hire(task(**BIG_DEV), market.cfg, market)["chosen"]
    provider, _, model = first.partition("/")
    market.cool({"provider": provider, "model": model, "key": first}, ProviderError("no credit", kind="quota"))
    rec = hiring.hire(task(**BIG_DEV), market.cfg, market)
    assert all(not c["key"].startswith(provider + "/") for c in rec["chain"]), rec["chain"]  # a benched provider is out
    slow = rec["chosen"]
    p2, _, m2 = slow.partition("/")
    market.cool({"provider": p2, "model": m2, "key": slow}, ProviderError("slow down", kind="rate_limit", retryable=True))
    keys = [c["key"] for c in hiring.hire(task(**BIG_DEV), market.cfg, market)["chain"]]
    assert keys[-1] == slow  # cooling: still an option, the last one


def test_without_ready_models_nobody_is_hired_and_the_team_combo_stays(tmp_path):
    """D5: in demo mode the record says so, and the worker keeps its team's combo (the simulator)."""
    from backend.router import hiring
    from backend.router.index import Router

    value = {"router": {"defaultCombo": "fast", "logCalls": False}, "providers": {"mock": {"kind": "mock"}}, "combos": {"fast": {"models": ["mock/m"]}}, "teams": CFG_TEAMS["teams"]}
    router = Router(config=FakeConfig(value), data_dir=tmp_path)
    rec = hiring.hire(task(**BIG_DEV), value, router)
    assert (rec["demo"], rec["chosen"], rec["chain"]) == (True, None, [])
    assert rec["category"] == "coding" and rec["level"] == "complex"  # the reading is there all the same


def test_a_replacement_promotes_the_next_compatible_candidate(market):
    from backend.router import hiring
    from backend.router.providers import ProviderError

    rec = hiring.hire(task(**BIG_DEV), market.cfg, market)
    first, second = rec["chain"][0]["key"], rec["chain"][1]["key"]
    provider, _, model = first.partition("/")
    market.cool({"provider": provider, "model": model, "key": first}, ProviderError("no credit", kind="quota"))
    out = hiring.promote(task(**BIG_DEV, hire=rec), {"target": second, "failed": [{"target": first, "kind": "quota"}]}, market.cfg, market)
    assert out["chosen"] == second and out["chain"][0]["key"] == second
    assert out["replacements"][-1] | {"at": None} == {"from": first, "to": second, "reason": "quota", "at": None}
    assert hiring.promote(task(**BIG_DEV, hire=out), {"target": second, "failed": []}, market.cfg, market) is None  # the hired model answered: nothing changes


# ---------- R2: the router follows the chain, then the team's combo ----------


@pytest.mark.asyncio
async def test_the_router_tries_the_hired_chain_first_then_the_combo_of_the_role(tmp_path, monkeypatch):
    from backend.router.index import Router

    for k in ("A_KEY", "B_KEY", "C_KEY"):
        monkeypatch.setenv(k, "k")
    seen = []

    def handler(request):
        import json as jsonlib

        model = jsonlib.loads(request.content)["model"]
        seen.append(f"{request.url.host}/{model}")
        if request.url.host == "a":
            return httpx.Response(429, json={"error": {"message": "quota", "type": "insufficient_quota", "code": "insufficient_quota"}})
        return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    value = {
        "router": {"defaultCombo": "fast", "cascade": ["fast"], "cooldownBaseMs": 1, "cooldownMaxMs": 1, "authCooldownMs": 1, "quotaCooldownMs": 60000, "logCalls": False, "emergencyMock": False, "demoFallback": False},
        "providers": {p: {"kind": "openai", "baseUrl": f"http://{p}/v1", "keyEnv": f"{p.upper()}_KEY"} for p in ("a", "b", "c")},
        "combos": {"fast": {"models": ["c/team-model"]}},
        "teams": {"dev": {"combo": "fast"}},
    }
    router = Router(config=FakeConfig(value), data_dir=tmp_path, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = await router.chat(role="dev", chain=["a/hired", "b/next"], messages=[{"role": "user", "content": "x"}])
    assert seen == ["a/hired", "b/next"] and res["target"] == "b/next" and res["combo"] == "hire"
    assert res["failed"] == [{"target": "a/hired", "kind": "quota"}]
    value["providers"]["b"]["enabled"] = False
    res = await router.chat(role="dev", chain=["a/hired", "b/next"], messages=[{"role": "user", "content": "x"}])
    assert res["target"] == "c/team-model"  # the chain is gone: the team's combo answers (D3)


# ---------- R2 in a run: every subtask on its own model ----------

MARKET = {
    "anthropic": ["claude-opus-5-5", "claude-sonnet-5-5"],
    "openrouter": ["meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-coder-32b-instruct:free"],
    "groq": ["llama-3.1-8b-instant"],
}


def market_ctx(tmp_path, monkeypatch, upstream, market=None):
    """The failover tests' live context (fake servers answering like the simulator),
    with a market of real-looking model names instead of alpha/m1 and beta/m2."""
    market = market or MARKET
    from test_failover import live_ctx  # tests/ is on sys.path

    ctx = live_ctx(tmp_path, monkeypatch, upstream, limits={"maxParallel": 2})
    cfg = ctx.config.get()
    for p in market:
        monkeypatch.setenv(f"{p.upper()}_TEST_KEY", "k")
        cfg["providers"][p] = {"kind": "openai", "baseUrl": f"http://{p}/v1", "keyEnv": f"{p.upper()}_TEST_KEY"}
    del cfg["providers"]["alpha"], cfg["providers"]["beta"]
    every = [f"{p}/{m}" for p, models in market.items() for m in models]
    for combo in cfg["combos"].values():
        combo["models"] = list(every)
    cfg["router"]["aliases"] = {}
    return ctx


def _task_of(call) -> str | None:
    import re as re_

    brief = next((m["content"] for m in call["messages"][1:2]), "")
    m = re_.search(r"^TASK ID: (\S+)$", brief, re_.MULTILINE)
    return m.group(1) if m else None


@pytest.mark.asyncio
async def test_every_subtask_of_a_live_run_works_on_the_model_it_hired(tmp_path, monkeypatch):
    import asyncio

    from test_failover import GOAL, Upstream

    from backend.run import Run

    upstream = Upstream()
    run = Run(goal=GOAL, ctx=market_ctx(tmp_path, monkeypatch, upstream))
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] == "completed", d["error"]
    for t in d["tasks"]:
        rec = t["hire"]
        assert rec["chosen"] and rec["demo"] is False and rec["category"] in ("coding", "creative", "research", "reasoning", "general"), rec
        calls = [c for c in upstream.calls if c["marker"] == "tasker" and _task_of(c) == t["id"]]
        assert calls, t["id"]
        used = {f"{c['provider']}/{c['model']}" for c in calls}
        assert used == {rec["chosen"]}, (t["id"], used, rec["chosen"])  # no failure: every step on the hired model
        assert any(h["kind"] == "hire" for h in t["history"])  # the timeline says who was hired


@pytest.mark.asyncio
async def test_a_hired_model_out_of_credit_mid_step_hands_over_to_the_next_candidate(tmp_path, monkeypatch):
    import asyncio

    from test_failover import GOAL, QUOTA, Upstream

    from backend.run import Run

    state = {"victim": None, "worker_calls": 0}

    def fail(provider, n):
        return (429, QUOTA) if state["victim"] == provider else None

    upstream = Upstream(fail)
    real = upstream.handler

    def handler(request):
        import json as jsonlib

        body = jsonlib.loads(request.content or b"{}")
        if "[[role:tasker" in jsonlib.dumps(body.get("messages", [])[:1]):
            state["worker_calls"] += 1
            if state["worker_calls"] == 3 and state["victim"] is None:
                state["victim"] = request.url.host  # the provider of this step runs out of credit, now
        return real(request)

    upstream.handler = handler
    run = Run(goal=GOAL, ctx=market_ctx(tmp_path, monkeypatch, upstream))
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] == "completed", d["error"]
    assert state["victim"], "no worker step reached the third call"
    replaced = [t for t in d["tasks"] if (t["hire"].get("replacements") or [])]
    assert replaced, [t["hire"]["chosen"] for t in d["tasks"]]
    r = replaced[0]["hire"]["replacements"][0]
    assert r["from"].startswith(state["victim"] + "/") and not r["to"].startswith(state["victim"] + "/") and r["reason"] == "quota"
    assert replaced[0]["hire"]["chosen"] == r["to"]
    assert any(h["kind"] == "hire" and r["to"] in h["text"] for h in replaced[0]["history"])
    # after the bench, no subtask hires a model of the provider without credit
    later = [t for t in d["tasks"] if t["hire"]["at"] > r["at"]]
    assert all(not t["hire"]["chosen"].startswith(state["victim"] + "/") for t in later)


@pytest.mark.asyncio
async def test_a_model_that_keeps_failing_in_the_session_is_no_longer_hired(tmp_path, monkeypatch):
    """The same flapping 429 as the spec 09 test, with hiring on: the health of
    the session moves the workers away from it, the run uses it less and less."""
    import asyncio

    from test_failover import GOAL, Upstream, live_ctx

    from backend.run import Run

    upstream = Upstream(lambda provider, n: (429, {"error": {"message": "Rate limit reached for requests"}}) if provider == "alpha" else None)
    ctx = live_ctx(tmp_path, monkeypatch, upstream)
    ctx.config.get()["router"].update({"cooldownBaseMs": 1, "cooldownMaxMs": 1})
    run = Run(goal=GOAL, ctx=ctx)
    await asyncio.wait_for(run.start(), timeout=60)
    assert run.data["status"] == "completed", run.data["error"]
    alpha_worker = [c for c in upstream.calls if c["provider"] == "alpha" and c["marker"] == "tasker"]
    worker = [c for c in upstream.calls if c["marker"] == "tasker"]
    assert len(alpha_worker) <= 2 < len(worker), (len(alpha_worker), len(worker))  # tried, then not hired again
    later = [t["hire"]["chosen"] for t in run.data["tasks"]][1:]
    assert later and all(k == "beta/m2" for k in later)


@pytest.mark.asyncio
async def test_a_demo_run_hires_nobody_and_works_as_before(demo_ctx):
    """D5: no provider with a key, the simulator answers every role as always."""
    import asyncio

    from backend.run import Run

    run = Run(goal="Una landing page per il bar", ctx=demo_ctx)
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] in ("completed", "completed_with_failures"), d["error"]
    assert d["tasks"] and all(t["hire"]["demo"] is True and t["hire"]["chosen"] is None for t in d["tasks"])
    assert all(t["hire"]["category"] and t["hire"]["level"] for t in d["tasks"])


# ---------- R4: the prompt takes the shape of the hired model ----------
#
# small (local, :free, 14B or less): atomic steps from the task, one example from
# the skill, the JSON contract and a validator at every turn; reasoning: the QA
# checklist, the constraints and the Brain lessons first; coder: the snippets of
# the skills, the exact tree of the project and the interfaces to respect;
# general: the prompt of before (the demo simulator stays here). D6: in this order.

SHAPES = [
    ("ollama/qwen2.5-coder:7b", "small"),  # D6: a 7B coder needs atomic steps more than snippets
    ("openrouter/meta-llama/llama-3.3-70b-instruct:free", "small"),
    ("gemini/gemini-2.5-flash", "small"),
    ("groq/llama-3.1-8b-instant", "small"),
    ("together/Qwen/Qwen2.5-14B-Instruct", "small"),  # 14B and less
    ("openai/o3", "reasoning"),
    ("deepseek/deepseek-reasoner", "reasoning"),
    ("openrouter/deepseek/deepseek-r1", "reasoning"),
    ("gemini/gemini-2.5-pro", "reasoning"),
    ("anthropic/claude-sonnet-5-5", "coder"),
    ("deepseek/deepseek-chat", "coder"),
    ("openai/gpt-5", "coder"),
    ("mistral/codestral-latest", "coder"),
    ("mistral/devstral-medium-latest", "coder"),
    ("anthropic/claude-opus-5-5", "general"),
    ("openai/gpt-4o", "general"),
    ("together/meta-llama/Llama-3.3-70B-Instruct-Turbo", "general"),
    ("mock/mock-dev", "general"),  # the demo keeps its prompt
]


@pytest.mark.parametrize("key,shape", SHAPES)
def test_the_prompt_shape_follows_the_family_and_the_size(key, shape):
    from backend.rag_budget import budget
    from backend.rag_budget import shape as shape_of

    p = profiler.profile(key)
    assert shape_of(p) == shape, p
    assert budget(p, {})["shape"] == shape
    if shape == "small":
        assert budget(p, {})["jsonContract"] is True  # the contract comes with every small model


SKILL_MD = """---
name: landing-page
description: how to build a landing page that converts
---
# Landing page

Keep the hero above the fold, with one call to action.

## Example

```html
<section class="hero"><h1>Da Gino</h1><a class="cta" href="#menu">Prenota</a></section>
```

## Layout

```css
.hero { display: grid; place-items: center; min-height: 80vh; }
```

Use the brand palette of the stylesheet.
"""
CSS = ":root { --primary: #c0392b; }\n.hero { color: var(--primary); }\n.cta { background: var(--primary); }\n"
MARKERS = {
    "small": ["STEPS (", "EXAMPLE FROM YOUR SKILL"],
    "reasoning": ["QA CHECKLIST", "CONSTRAINTS", "LESSONS FROM THE BRAIN"],
    "coder": ["PROJECT TREE", "INTERFACES TO RESPECT", "SKILL SNIPPETS"],
}


@pytest.mark.parametrize("head", ["Example", "Examples", "Worked example", "Esempio", "Ejemplo", "Exemple", "Beispiel"])
def test_the_example_of_a_skill_is_its_example_section(head):
    from backend.skills import example_of

    body = f"# Skill\n\nIntro.\n\n```css\n.a {{}}\n```\n\n## {head}\n\nThe hero, then the menu.\n\n### Detail\n\nStill the example.\n\n## Next\n\nNot the example."
    assert example_of(body) == "The hero, then the menu.\n\n### Detail\n\nStill the example."  # down to the next heading of its level


def test_without_an_example_section_the_first_code_block_and_otherwise_nothing():
    from backend.skills import code_blocks, example_of

    body = "# Skill\n\n## Counterexamples are not examples\n\n```html\n<p>one</p>\n```\n\ntext\n\n```js\ntwo()\n```\n"
    assert code_blocks(body) == ["```html\n<p>one</p>\n```", "```js\ntwo()\n```"]
    assert example_of(body) == "```html\n<p>one</p>\n```"
    assert example_of("# Skill\n\nOnly words.") == ""
    assert example_of("## Bad examples\n\nwrong\n\n## Esempi sbagliati\n\nwrong\n\n## Example\n\nright") == "right"  # what to avoid is no model
    assert len(example_of("## Example\n\n" + "x" * 5000, max_chars=300)) == 300


async def shaped_tasker(demo_ctx, tmp_path, key):
    """A worker of w2 (dev) building on w1 (design, delivered css/style.css), with
    a skill that has an example, a Brain lesson and its subtask hired on `key`."""
    from backend.plan import new_task
    from backend.run import Run
    from backend.skills import SkillLibrary
    from backend.tasker import Tasker

    class Cfg:
        def get(self):
            return {"skills": {"sources": ["skills"], "repos": []}, "rag": {"chunk": {"maxChars": 1200}}}

    root = tmp_path / "lib"
    (root / "skills" / "landing-page").mkdir(parents=True)
    (root / "skills" / "landing-page" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    lib = SkillLibrary(root, Cfg(), None)
    await lib.reindex()
    demo_ctx.skills = lib
    demo_ctx.brain.add(title="Il pulsante sopra la piega", text="Nella pagina del menu il pulsante di prenotazione va sopra la piega: il QA lo ha chiesto due volte.", team="dev", kind="lesson")
    run = Run(goal="Il sito della pizzeria", ctx=demo_ctx)
    ws = lambda i, deps=(): {"id": i, "team": "dev", "title": i, "objective": "o", "deliverables": [], "acceptance": [], "dependsOn": list(deps), "status": "running", "summary": ""}  # noqa: E731
    run.data["workstreams"] = [ws("w1"), ws("w2", ["w1"])]
    design = new_task({"id": "w1.1", "wsId": "w1", "team": "design", "title": "Palette e stile", "description": "La palette del brand", "acceptance": [], "outputs": ["css/style.css"], "dependsOn": []})
    design.update(status="done", files=["css/style.css"], summary="La palette del brand in css/style.css")
    page = new_task(
        {
            "id": "w2.1",
            "wsId": "w2",
            "team": "dev",
            "title": "Pagina del menu",
            "description": "Costruisci la pagina del menu con i colori del brand e il pulsante di prenotazione.",
            "acceptance": ["La pagina usa le variabili della palette", "Il pulsante di prenotazione sta sopra la piega"],
            "outputs": ["menu.html", "js/menu.js"],
            "dependsOn": [],
        }
    )
    page["pitfalls"] = ["Non ridefinire i colori: usa var(--primary)"]
    page["skills"] = [{"id": lib.skills[0]["id"], "name": "landing-page"}]
    page["hire"] = {"chain": [{"key": key}], "chosen": key}
    run.data["tasks"] = [design, page]
    await run.ws.write("css/style.css", CSS)
    await run.ws.write("index.html", "<main id='app'></main>")
    run.publish_file(design, {"id": "ugo", "name": "Ugo"}, "css/style.css", CSS)
    tasker = Tasker(run, page, {"id": "nina", "name": "Nina", "team": "dev", "kind": "worker"})
    await tasker.init()
    return tasker


@pytest.mark.asyncio
async def test_a_small_model_gets_atomic_steps_an_example_from_its_skill_and_the_contract(demo_ctx, tmp_path):
    t = await shaped_tasker(demo_ctx, tmp_path, "ollama/qwen2.5-coder:7b")
    system, brief = t.messages[0]["content"], t.messages[1]["content"]
    assert t.shape == "small"
    steps = brief.split("STEPS (", 1)[1].split("\n\n", 1)[0].splitlines()[1:]
    numbered = [s for s in steps if s[:1].isdigit()]
    assert numbered[0].startswith("1. list_files")
    assert any("read_file" in s and "css/style.css" in s for s in numbered)  # the teammate's file, before building on it
    assert [s for s in numbered if "write_file" in s and "menu.html" in s] and [s for s in numbered if "write_file" in s and "js/menu.js" in s]  # one step per file
    assert "read_file" in numbered[-2] and "finish" in numbered[-1]  # the check, then finish
    example = brief.split("EXAMPLE FROM YOUR SKILL", 1)[1]
    assert '<section class="hero">' in example  # the "Example" section of the skill
    assert system.rsplit("\n\n", 1)[1].startswith("OUTPUT CONTRACT")  # the contract, last
    assert "QA CHECKLIST" not in brief and "PROJECT TREE" not in brief
    for field in ("GOAL:", "TASK ID: w2.1", "OUTPUTS: menu.html, js/menu.js", "PROJECT FILES:"):
        assert field in brief  # the fields the demo simulator and the tests read stay


@pytest.mark.asyncio
async def test_a_reasoning_model_gets_the_checklist_the_constraints_and_the_lessons_first(demo_ctx, tmp_path):
    t = await shaped_tasker(demo_ctx, tmp_path, "openai/o3")
    brief = t.messages[1]["content"]
    assert t.shape == "reasoning"
    head = brief.split("\nDESCRIPTION:", 1)[0]  # what comes before the task itself
    assert "QA CHECKLIST" in head and "[ ] La pagina usa le variabili della palette" in head and "[ ] Il pulsante di prenotazione sta sopra la piega" in head
    constraints = head.split("CONSTRAINTS", 1)[1]
    assert "var(--primary)" in constraints  # the pitfall
    assert "w1.1" in constraints and "css/style.css" in constraints  # the work it builds on
    assert ".hero" in constraints and "--primary #c0392b" in constraints  # the interface of the linked file
    lessons = head.split("LESSONS FROM THE BRAIN", 1)[1]
    assert "sopra la piega" in lessons
    assert "STEPS (" not in brief and "SKILL SNIPPETS" not in brief


@pytest.mark.asyncio
async def test_a_coder_model_gets_the_snippets_the_tree_and_the_interfaces(demo_ctx, tmp_path):
    t = await shaped_tasker(demo_ctx, tmp_path, "anthropic/claude-sonnet-5-5")
    brief = t.messages[1]["content"]
    assert t.shape == "coder"
    tree = brief.split("PROJECT TREE", 1)[1].split("\n\n", 1)[0]
    assert "\n  css/\n    style.css" in tree and "\n  index.html" in tree  # the exact tree, folders first
    interfaces = brief.split("INTERFACES TO RESPECT", 1)[1].split("\n\n", 1)[0]
    assert "css/style.css" in interfaces and ".hero" in interfaces and ".cta" in interfaces
    snippets = brief.split("SKILL SNIPPETS", 1)[1]
    assert ".hero { display: grid;" in snippets and '<section class="hero">' in snippets  # the code blocks of the skill
    assert brief.index("PROJECT TREE") < brief.index("\nDESCRIPTION:")  # first
    assert "QA CHECKLIST" not in brief and "STEPS (" not in brief


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["anthropic/claude-opus-5-5", None])
async def test_a_general_model_and_the_demo_keep_the_prompt_of_before(demo_ctx, tmp_path, key):
    t = await shaped_tasker(demo_ctx, tmp_path, key or "x/y")
    if key is None:
        t.task["hire"] = {"chain": [], "chosen": None, "demo": True}  # D5: nobody hired, the simulator
        t.messages = None
        await t.init()
    brief, system = t.messages[1]["content"], t.messages[0]["content"]
    assert t.shape == "general"
    assert not [m for markers in MARKERS.values() for m in markers if m in brief], brief
    assert brief.startswith("GOAL: Il sito della pizzeria\n\nWORKSTREAM:")  # the brief of before, field by field
    assert "OUTPUT CONTRACT" not in system


@pytest.mark.asyncio
async def test_a_switch_to_a_small_model_brings_its_shape(demo_ctx, tmp_path):
    """A failover from a coder to a small model: the next step gets the steps and the contract."""
    t = await shaped_tasker(demo_ctx, tmp_path, "anthropic/claude-sonnet-5-5")
    await t._switched({"target": "groq/llama-3.1-8b-instant", "profile": profiler.profile("groq/llama-3.1-8b-instant")})
    assert t.shape == "small"
    switch = t.pending["content"]
    assert switch.startswith("MODEL SWITCH") and "STEPS (" in switch and "OUTPUT CONTRACT" in switch


def small_run(replies, key):
    """test_tasker's duck of a run, its model profiled as `key`, its tool calls recorded."""
    from test_tasker import FakeRun

    run = FakeRun(replies)
    run.cfg["limits"]["maxSteps"] = 6
    run.model_profile = lambda role, use=None: profiler.profile(key)

    async def exec_tool(task, agent, action):
        run.tool_calls.append((action["tool"], dict(action["args"])))
        return "done"

    run.exec_tool = exec_tool
    return run


@pytest.mark.asyncio
@pytest.mark.parametrize("key,stopped", [("groq/llama-3.1-8b-instant", True), ("anthropic/claude-opus-5-5", False)])
async def test_the_validator_stops_an_incomplete_action_of_a_small_model(key, stopped):
    """write_file without content: for a small model a FORMAT ERROR that names the
    missing argument, at every turn, instead of reaching the tool."""
    import json

    from test_tasker import AGENT, TASK

    from backend.tasker import Tasker

    run = small_run(
        [
            json.dumps({"thought": "write", "tool": "write_file", "args": {"path": "out.md"}}),
            json.dumps({"thought": "write", "tool": "write_file", "args": {"path": "out.md", "content": "# Out"}}),
            json.dumps({"thought": "deliver", "tool": "finish", "args": {"summary": "Done", "files": ["out.md"]}}),
        ],
        key,
    )
    t = Tasker(run, dict(TASK, history=[]), AGENT)
    out = await t.work()
    assert out["summary"] == "Done"
    errors = [m["content"] for m in t.messages if m["role"] == "user" and m["content"].startswith("FORMAT ERROR")]
    if stopped:
        assert run.tool_calls == [("write_file", {"path": "out.md", "content": "# Out"})]  # the incomplete one never reached the tool
        assert len(errors) == 1 and "write_file" in errors[0] and '"content"' in errors[0]
        results = [m["content"] for m in t.messages if m["role"] == "user" and m["content"].startswith("RESULT of")]
        assert results and all("ONE JSON object" in r for r in results)  # the contract, at every turn
    else:
        assert [c[0] for c in run.tool_calls] == ["write_file", "write_file"] and not errors  # the prompt of before


@pytest.mark.asyncio
async def test_every_hired_model_of_a_live_run_gets_the_prompt_of_its_family(tmp_path, monkeypatch):
    """The market of the live tests: the worker of each subtask writes to its hired
    model in the shape of that model, and the run still arrives at the end."""
    import asyncio

    from test_failover import GOAL, Upstream

    from backend.rag_budget import shape as shape_of
    from backend.run import Run

    upstream = Upstream()
    mixed = {"anthropic": ["claude-opus-5-5", "claude-sonnet-5-5"], "openai": ["o3", "gpt-4o"], "groq": ["llama-3.1-8b-instant"]}  # paid families and one free
    run = Run(goal=GOAL, ctx=market_ctx(tmp_path, monkeypatch, upstream, mixed))
    await asyncio.wait_for(run.start(), timeout=60)
    d = run.data
    assert d["status"] == "completed", d["error"]
    seen, rehired = set(), 0
    for t in d["tasks"]:
        calls = [c for c in upstream.calls if c["marker"] == "tasker" and _task_of(c) == t["id"]]
        shapes = [shape_of(profiler.profile(f"{c['provider']}/{c['model']}")) for c in calls]
        brief = calls[0]["messages"][1]["content"]
        for name, markers in MARKERS.items():
            assert (markers[0] in brief) is (name == shapes[0]), (t["id"], calls[0]["model"], name)  # no skills here: the first block of each shape
        for prev, c, shape in zip(calls, calls[1:], shapes[1:]):
            if c["model"] != prev["model"]:
                # a revision hired another model: the switch, in its shape, is there from its first step
                rehired += 1
                switch = [m["content"] for m in c["messages"] if m["role"] == "user" and m["content"].startswith(f"MODEL SWITCH: you now run on {c['provider']}/{c['model']}")]
                assert switch and (shape == "general" or MARKERS[shape][0] in switch[-1]), (t["id"], c["model"], shape)
        assert t["hire"]["shape"] == shapes[-1]  # the record says which prompt the hired model got
        seen.update(shapes)
    assert len(seen) >= 2, seen  # the market hires more than one family
    assert rehired >= 1  # and a revision hires a bigger one for the same subtask
