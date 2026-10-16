"""Spec 08 §4: every model gets a context sized to what it can take, and every
agent sees what the others already did in this run.

- Budget: a large model (frontier, >= 128k, not free) gets up to 5 Brain notes,
  its whole assigned skills and the detailed run context. A fast, free or local
  model gets the compact mode: the top-2 passages of its skills (RRF, a stricter
  minCosine), the Brain and QA notes as short bullets, and an explicit JSON
  output contract at the end of its system prompt.
- JSON repair: the answers small models really give (single quotes, unquoted
  keys, a tool called "Write_File()", args as a string, OpenAI's function-call
  shape, args at the top level, closing brackets cut off) become an action
  instead of "Risposta non valida, riprovo".
- Run memory: files written, verdicts, QA lessons, blocks and deliveries are
  indexed as they happen (BM25 + local n-gram vectors, no network), tagged with
  workstream, task and team; a worker, a spawned sub-agent and a worker whose
  model changed (fallback or escalation) get the relevant ones."""

import json
import types

import pytest

from backend.router import profiler

BIG = profiler.profile("anthropic/claude-opus-5-5")
SMALL = profiler.profile("gemini/gemini-2.5-flash")
LOCAL = profiler.profile("ollama/qwen3:8b")
RAG = {"minCosine": 0.25, "chunk": {"maxChars": 1200}}


# ---------- the budget ----------


def test_a_large_model_gets_the_full_context():
    from backend.rag_budget import budget

    b = budget(BIG, RAG)
    assert b["mode"] == "full"
    assert b["brainNotes"] == 5 and b["skills"] == 3 and b["passageChars"] == 1200
    assert b["jsonContract"] is False


@pytest.mark.parametrize("p", [SMALL, LOCAL, profiler.profile("openrouter/meta-llama/llama-3.3-70b-instruct:free")])
def test_a_small_free_or_local_model_gets_the_compact_context(p):
    from backend.rag_budget import budget

    b = budget(p, RAG)
    assert b["mode"] == "compact"
    assert b["passages"] == 2 and b["minCosine"] > RAG["minCosine"]
    assert b["brainNotes"] <= 3 and b["noteChars"] <= 160
    assert b["jsonContract"] is True


def test_the_compact_prompt_ends_with_the_json_contract():
    from backend.prompts import tasker_system

    common = dict(agent={"id": "nina", "name": "Nina", "team": "dev", "kind": "worker"}, team_cfg={"label": "Dev", "title": "Engineer", "brief": "Builds."}, lead={"name": "Leo"}, tools=["read_file", "write_file", "finish"], skills_text="")
    compact = tasker_system(**common, json_contract=True)
    full = tasker_system(**common)
    assert compact.startswith("[[role:tasker:dev]]")  # the demo provider still reads it
    tail = compact.rsplit("\n\n", 1)[1]
    assert tail.startswith("OUTPUT CONTRACT") and '"tool": "read_file | write_file | finish"' in tail
    assert "OUTPUT CONTRACT" not in full


# ---------- JSON repair ----------


@pytest.mark.parametrize(
    "text,tool,args",
    [
        ("Sure! Here it is:\n```json\n{\"thought\": \"x\", \"tool\": \"list_files\", \"args\": {}}\n```\nDone.", "list_files", {}),
        ("{'thought': 'x', 'tool': 'read_file', 'args': {'path': 'a.md'}, 'ok': True}", "read_file", {"path": "a.md"}),
        ('{thought: "x", tool: "read_file", args: {path: "a.md"}}', "read_file", {"path": "a.md"}),
        ('{"thought": "x", "tool": "Write_File()", "args": {"path": "a.md", "content": "c"}}', "write_file", {"path": "a.md", "content": "c"}),
        ('{"thought": "x", "tool": "functions.read_file", "args": {"path": "a.md"}}', "read_file", {"path": "a.md"}),
        ('{"tool": "read_file", "args": "{\\"path\\": \\"a.md\\"}"}', "read_file", {"path": "a.md"}),
        ('{"function": {"name": "read_file", "arguments": "{\\"path\\": \\"a.md\\"}"}}', "read_file", {"path": "a.md"}),
        ('{"thought": "x", "tool": "read_file", "path": "a.md"}', "read_file", {"path": "a.md"}),
        ('{"thought": "x", "tool": "read_file", "args": {"path": "a.md"', "read_file", {"path": "a.md"}),
    ],
)
def test_the_answers_of_small_models_become_actions(text, tool, args):
    from backend.tasker import parse_action

    a = parse_action(text)
    assert a is not None, text
    assert a["tool"] == tool and a["args"] == args


def test_a_file_cut_off_mid_content_is_not_written():
    """Closing brackets are repaired; a string cut in the middle is not: that
    would write half a file. The worker gets the FORMAT ERROR and tries again."""
    from backend.tasker import parse_action

    assert parse_action('{"thought": "x", "tool": "write_file", "args": {"path": "a.md", "content": "half of the fi') is None


def test_python_literals_never_run_code():
    from backend.json_repair import extract_json

    assert extract_json("{'tool': __import__('os').system('echo hi')}") is None


# ---------- run memory ----------


def test_the_run_memory_finds_what_happened():
    from backend.run_memory import RunMemory

    m = RunMemory(RAG)
    m.add("file", "research/notes.md: audience is young families, three competitors, hero section first", ws_id="w1", task_id="w1.1", team="research", agent="Rino", path="research/notes.md")
    m.add("verdict", "Revise: the CSS has no variables for the palette and the hero image is missing", ws_id="w2", task_id="w2.1", team="design", agent="Vera")
    m.add("lesson", "In design tasks: define the palette as CSS variables before the layout", ws_id="w2", task_id="w2.1", team="design", agent="Vera")
    m.add("block", "generate_speech failed: no credit on OpenAI", ws_id="w5", task_id="w5.1", team="genai", agent="Dario")
    hits = m.search("palette CSS variables for the design", 2)
    assert [h["kind"] for h in hits] == ["lesson", "verdict"] or {h["kind"] for h in hits} == {"lesson", "verdict"}
    assert all("ts" in h and h["team"] == "design" for h in hits)
    files = m.search("audience research notes", 3, kinds=("file",))
    assert files and files[0]["path"] == "research/notes.md"
    assert not m.search("audience research notes", 3, exclude_task="w1.1", kinds=("file",))


# ---------- the Tasker uses the budget ----------


class _Run:
    """The Tasker's view of a run, with a model profile and a RAG context."""

    def __init__(self, profile, replies, targets=None):
        from backend.tools import Workspace
        import tempfile

        self.cfg = {"limits": {"maxSteps": 6}, "teams": {"dev": {"label": "Dev", "title": "Engineer", "brief": "Builds.", "tools": []}}, "router": {}, "combos": {}}
        self.data = {"goal": "g", "language": "en"}
        self.profile = profile
        self.replies = list(replies)
        self.targets = list(targets or [])
        self.team = types.SimpleNamespace(lead=lambda team: {"id": "leo", "name": "Leo"}, set=lambda *a: None)
        self.ws = Workspace(tempfile.mkdtemp())
        self.refreshed = []

    def ws_by_id(self, id):
        return {"id": "w1", "title": "WS", "objective": "o"}

    def inputs_for(self, task):
        return []

    def role_combo(self, kind):
        return None

    def model_profile(self, role, use=None):
        return self.profile

    async def rag_context(self, task, agent, profile, reason="start", extra=""):
        self.refreshed.append((reason, profile["key"]))
        return {"skills": "", "memory": "- note", "shared": "- [file] research/notes.md", "jsonContract": profile["compact"]}

    async def gate(self, agent):
        return None

    def take_steering(self, task, agent):
        return []

    async def chat(self, **kw):
        target = self.targets.pop(0) if self.targets else self.profile["key"]
        return {"text": self.replies.pop(0), "target": target, "profile": profiler.profile(target)}

    def note(self, *a, **k):
        pass

    def step(self, *a, **k):
        pass

    async def missing_outputs(self, task):
        return []

    async def exec_tool(self, task, agent, action):
        return "done"


TASK = {"id": "w1.1", "wsId": "w1", "team": "dev", "title": "T", "description": "D", "acceptance": ["ok"], "outputs": [], "dependsOn": [], "attempts": 0, "skills": [], "brief": "", "pitfalls": [], "history": []}
AGENT = {"id": "nina", "name": "Nina", "team": "dev", "kind": "worker"}
STEP = json.dumps({"thought": "look", "tool": "list_files", "args": {}})
FINISH = json.dumps({"thought": "done", "tool": "finish", "args": {"summary": "s", "files": []}})


@pytest.mark.asyncio
@pytest.mark.parametrize("p,contract", [(BIG, False), (SMALL, True)])
async def test_the_tasker_builds_its_prompt_for_its_model(p, contract):
    from backend.tasker import Tasker

    t = Tasker(_Run(p, [FINISH]), dict(TASK), AGENT)
    await t.work()
    system, brief = t.messages[0]["content"], t.messages[1]["content"]
    assert ("OUTPUT CONTRACT" in system) is contract
    assert "FROM THE TEAM (this run):\n- [file] research/notes.md" in brief


@pytest.mark.asyncio
async def test_a_model_switch_in_flight_refreshes_the_context():
    """A fallback (or an escalation) moves the worker to another model: it gets
    the run context again, sized for the new model, with the JSON contract if
    the new model is a small one."""
    from backend.tasker import Tasker

    run = _Run(BIG, [STEP, STEP, FINISH], targets=["anthropic/claude-opus-5-5", "gemini/gemini-2.5-flash", "gemini/gemini-2.5-flash"])
    t = Tasker(run, dict(TASK), AGENT)
    await t.work()
    assert run.refreshed == [("start", "anthropic/claude-opus-5-5"), ("switch", "gemini/gemini-2.5-flash")]
    switch = next(m["content"] for m in t.messages if m["role"] == "user" and m["content"].startswith("MODEL SWITCH"))
    assert "gemini/gemini-2.5-flash" in switch and "OUTPUT CONTRACT" in switch and "research/notes.md" in switch


@pytest.mark.asyncio
async def test_a_revision_brings_the_qa_lessons():
    from backend.tasker import Tasker

    run = _Run(BIG, [FINISH, FINISH])
    t = Tasker(run, dict(TASK), AGENT)
    await t.work()
    await t.work("Missing the final section")
    assert run.refreshed[-1] == ("revision", BIG["key"])
    revision = next(m["content"] for m in t.messages if m["content"].startswith("REVISION REQUESTED"))
    assert "FROM THE TEAM (this run)" in revision


# ---------- compact skills: the top passages ----------


@pytest.mark.asyncio
async def test_compact_mode_takes_the_best_passages_of_the_assigned_skills(tmp_path):
    from backend.skills import SkillLibrary

    class Cfg:
        def get(self):
            return {"skills": {"sources": ["skills"], "repos": []}, "rag": {"chunk": {"maxChars": 300}}}

    class Bus:
        def emit(self, *a):
            pass

    d = tmp_path / "skills" / "css-palette"
    d.mkdir(parents=True)
    body = "\n\n".join(
        [
            "# CSS palette",
            "## Colours\nDefine every colour of the palette as a CSS custom property on :root, then use var(--name) everywhere.",
            "## Typography\nPick two font families at most and set a modular scale for the headings.",
            "## Deployment\nUpload the static files to the host and purge the CDN cache.",
        ]
    )
    (d / "SKILL.md").write_text(f"---\nname: css-palette\ndescription: palette and type for a site\n---\n{body}\n", encoding="utf-8")
    lib = SkillLibrary(tmp_path, Cfg(), Bus())
    await lib.reindex()
    hits = await lib.passages(["css-palette"], "palette colours as CSS variables", k=2, max_chars=300, min_cosine=0.35)
    assert 1 <= len(hits) <= 2
    assert "custom property" in hits[0]["text"] and hits[0]["skill"]["name"] == "css-palette"
    assert all(len(h["text"]) <= 300 for h in hits)
    assert not any("CDN cache" in h["text"] for h in hits[:1])
