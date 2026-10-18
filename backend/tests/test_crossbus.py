"""Spec 10 §R3: the cross-agent context bus.

Workers and sub-agents working in parallel publish what they find the moment
they find it: every file written gives facts (its palette, its classes and
ids, its functions, its headings, its links, its keys), and deliveries,
verdicts and QA lessons are there as before (spec 08). When a linked subtask
is delivered or judged, or the worker's own model changes, the worker's next
step starts with a [LIVE CROSS-AGENT UPDATE]: the real paths just produced
by the others and the facts closest to its task (RRF of BM25 and cosine),
sized for its model, never the same fact twice."""

import json

import pytest
from test_run import demo_ctx  # noqa: F401 -- the demo fixture of test_run.py (tests/ is on sys.path)

from backend.crossbus import facts_from_file


def kinds(facts):
    return {k: t for k, t in facts}


def test_the_facts_of_a_stylesheet():
    css = ":root {\n  --primary: #c0392b;\n  --bg: #fff8f0;\n}\n.hero { color: var(--primary); }\n#menu .item { border: 1px solid #2c3e50; }\n"
    f = kinds(facts_from_file("css/style.css", css))
    assert "--primary #c0392b" in f["palette"] and "--bg #fff8f0" in f["palette"] and "#2c3e50" in f["palette"]
    assert ".hero" in f["interface"] and "#menu" in f["interface"] and ".item" in f["interface"]
    assert f["palette"].startswith("css/style.css")


def test_the_facts_of_a_page():
    html = '<html><head><link rel="stylesheet" href="css/style.css"></head><body><header id="top" class="hero dark"><h1>Pizzeria Da Gino</h1></header><h2>Il menu</h2><script src="js/app.js"></script></body></html>'
    f = kinds(facts_from_file("index.html", html))
    assert "#top" in f["interface"] and ".hero" in f["interface"] and ".dark" in f["interface"]
    assert "Pizzeria Da Gino" in f["copy"] and "Il menu" in f["copy"]
    assert "css/style.css" in f["links"] and "js/app.js" in f["links"]


def test_the_facts_of_code_text_and_data():
    js = kinds(facts_from_file("js/app.js", "export function initMenu() {}\nexport const API_URL = '/api';\nfunction helper() {}\nclass Cart {}\n"))
    assert all(n in js["interface"] for n in ("initMenu", "API_URL", "helper", "Cart"))
    py = kinds(facts_from_file("api/server.py", "def load_menu():\n    pass\n\nasync def order(id):\n    pass\n\nclass Order:\n    pass\n"))
    assert all(n in py["interface"] for n in ("load_menu", "order", "Order"))
    md = kinds(facts_from_file("content/home.md", "# Benvenuti\n\nTesto.\n\n## Le nostre pizze\n"))
    assert "Benvenuti" in md["copy"] and "Le nostre pizze" in md["copy"]
    data = kinds(facts_from_file("data/menu.json", json.dumps({"pizze": [], "bevande": [], "orari": {}})))
    assert all(k in data["keys"] for k in ("pizze", "bevande", "orari"))
    assert facts_from_file("notes/plain.txt", "just a sentence without anything") == []


# ---------- the update a worker receives ----------


def setup_run(demo_ctx):
    """Two linked workstreams (w2 builds on w1) and an unrelated one (w3)."""
    from backend.plan import new_task
    from backend.run import Run

    run = Run(goal="Il sito della pizzeria", ctx=demo_ctx)
    ws = lambda i, deps=(): {"id": i, "team": "dev", "title": i, "objective": "", "deliverables": [], "acceptance": [], "dependsOn": list(deps), "status": "running", "summary": ""}  # noqa: E731
    run.data["workstreams"] = [ws("w1"), ws("w2", ["w1"]), ws("w3")]
    t = lambda i, w, team, title: new_task({"id": i, "wsId": w, "team": team, "title": title, "description": title, "acceptance": [], "outputs": [], "dependsOn": []})  # noqa: E731
    run.data["tasks"] = [t("w1.1", "w1", "design", "Palette e stile"), t("w1.2", "w1", "content", "Testi del menu"), t("w2.1", "w2", "dev", "Pagina del menu con i colori del brand"), t("w3.1", "w3", "research", "Analisi dei concorrenti")]
    return run


AGENTS = {"w1.1": {"id": "ugo", "name": "Ugo"}, "w1.2": {"id": "gaia", "name": "Gaia"}, "w2.1": {"id": "nina", "name": "Nina"}, "w3.1": {"id": "sara", "name": "Sara"}}


def write(run, task_id, path, content):
    task = run.task_by_id(task_id)
    run.publish_file(task, AGENTS[task_id], path, content)


def deliver(run, task_id, summary):
    task = run.task_by_id(task_id)
    run.remember_event("delivery", f"{task['title']}: {summary}", task, AGENTS[task_id])


FULL = {"key": "x/big", "compact": False, "tier": "smart"}
SMALL = {"key": "x/small", "compact": True, "tier": "fast"}


def test_a_linked_delivery_brings_a_live_update_with_the_real_paths_and_facts(demo_ctx):
    run = setup_run(demo_ctx)
    me = run.task_by_id("w2.1")
    cursor = run.memory_cursor()
    write(run, "w1.1", "css/style.css", ":root { --primary: #c0392b; }\n.hero { color: var(--primary); }")
    block, after = run.cross_update(me, cursor, FULL)
    assert block is None and after == cursor  # a file alone is no trigger: the facts wait for one
    deliver(run, "w1.1", "Palette del brand in css/style.css")
    block, after = run.cross_update(me, cursor, FULL)
    assert block and block.startswith("[LIVE CROSS-AGENT UPDATE]")
    assert "css/style.css" in block and "--primary #c0392b" in block and ".hero" in block
    assert after == run.memory_cursor()
    assert run.cross_update(me, after, FULL) == (None, after)  # never the same fact twice


def test_an_unrelated_workstream_brings_nothing(demo_ctx):
    run = setup_run(demo_ctx)
    me = run.task_by_id("w2.1")
    cursor = run.memory_cursor()
    write(run, "w3.1", "research/competitors.md", "# Concorrenti\n")
    deliver(run, "w3.1", "Tre concorrenti")
    block, _ = run.cross_update(me, cursor, FULL)
    assert block is None


def test_a_model_switch_brings_the_update_without_a_delivery(demo_ctx):
    run = setup_run(demo_ctx)
    me = run.task_by_id("w2.1")
    cursor = run.memory_cursor()
    write(run, "w1.2", "content/menu.md", "# Il menu\n## Pizze rosse\n")
    block, _ = run.cross_update(me, cursor, FULL, switched=True)
    assert block and "content/menu.md" in block and "Il menu" in block


def test_the_update_is_ordered_by_relevance_and_sized_for_the_model(demo_ctx):
    run = setup_run(demo_ctx)
    me = run.task_by_id("w2.1")  # "Pagina del menu con i colori del brand"
    cursor = run.memory_cursor()
    for i in range(8):
        write(run, "w1.2", f"content/note{i}.md", f"# Nota {i}\n## Orari di apertura {i}\n")
    write(run, "w1.1", "css/brand.css", ":root { --brand: #c0392b; }\n.menu-colori { color: var(--brand); }")
    deliver(run, "w1.1", "I colori del brand per la pagina del menu")
    full, _ = run.cross_update(me, cursor, FULL)
    small, _ = run.cross_update(me, cursor, SMALL)
    facts = [l for l in full.splitlines() if l.startswith("- [") and not l.startswith("- [file]")]
    assert "brand" in facts[0] or "menu" in facts[0], facts  # RRF: the closest to the task first
    assert len(small.splitlines()) < len(full.splitlines())  # a small model gets a shorter update (D7)


@pytest.mark.asyncio
async def test_the_worker_receives_the_update_before_its_next_step():
    """The Tasker asks for the update before every step and puts it in the conversation."""
    from test_tasker import AGENT, TASK, FakeRun

    from backend.tasker import Tasker

    class CrossRun(FakeRun):
        def __init__(self, replies):
            super().__init__(replies)
            self.sent = []
            self.cursor_asks = []

        def memory_cursor(self):
            return 0

        def cross_update(self, task, since, profile, switched=False):
            self.cursor_asks.append(since)
            if len(self.cursor_asks) == 2:  # before the second step, a teammate delivered
                return "[LIVE CROSS-AGENT UPDATE]\n- [file] css/style.css (Ugo, w1)", 7
            return None, since

        async def chat(self, **kwargs):
            self.sent.append([m["content"] for m in kwargs["messages"]])
            return await super().chat(**kwargs)

    run = CrossRun(
        [
            json.dumps({"thought": "look", "tool": "list_files", "args": {"path": "."}}),
            json.dumps({"thought": "write", "tool": "write_file", "args": {"path": "out.md", "content": "x"}}),
            json.dumps({"thought": "deliver", "tool": "finish", "args": {"summary": "Done", "files": ["out.md"]}}),
        ]
    )
    await Tasker(run, dict(TASK, history=[]), AGENT).work()
    assert not any("[LIVE CROSS-AGENT UPDATE]" in c for c in run.sent[0])
    assert any(c.startswith("[LIVE CROSS-AGENT UPDATE]") for c in run.sent[1])
    assert sum(c.startswith("[LIVE CROSS-AGENT UPDATE]") for c in run.sent[2]) == 1  # sent once, kept in the conversation
    assert run.cursor_asks == [0, 0, 7]  # the cursor the update returned is the one asked next time
