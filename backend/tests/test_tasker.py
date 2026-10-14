"""Contract tests for backend/tasker.py, ported from server/engine/tasker.js.
The Tasker loop is exercised against a scripted FakeRun -- no model, no
filesystem beyond tmp_path."""

import json

import pytest

TASK = {"id": "w1.1", "wsId": "w1", "team": "dev", "title": "Scrivere il modulo", "description": "Scrivi x.", "acceptance": ["Funziona"], "outputs": ["out.md"], "dependsOn": [], "attempts": 0, "skills": [], "brief": "", "pitfalls": [], "history": []}
AGENT = {"id": "nina", "name": "Nina", "team": "dev", "kind": "worker"}


class TestParseAction:
    def test_happy_path(self):
        from backend.tasker import parse_action

        a = parse_action('{"thought": "scrivo", "tool": "write_file", "args": {"path": "a.md", "content": "x"}}')
        assert a == {"thought": "scrivo", "tool": "write_file", "args": {"path": "a.md", "content": "x"}}

    def test_alternate_shapes(self):
        from backend.tasker import parse_action

        assert parse_action('{"action": {"tool": "recall", "args": {"query": "q"}}, "reasoning": "perché"}')["tool"] == "recall"
        assert parse_action('{"name": "finish", "arguments": {"summary": "s"}}')["args"] == {"summary": "s"}
        assert parse_action('{"action": "list_files"}')["tool"] == "list_files"
        # parameters is the last-resort args key; non-object args become {}
        assert parse_action('{"tool": "list_files", "parameters": "nope"}')["args"] == {}

    def test_rejects_unknown_tool_and_bad_json(self):
        from backend.tasker import parse_action

        assert parse_action("not json at all") is None
        assert parse_action('{"tool": "rm_rf"}') is None
        assert parse_action('{"tool": "recall"}', allowed=["finish"]) is None

    def test_thought_is_capped(self):
        from backend.tasker import parse_action

        a = parse_action(json.dumps({"thought": "t" * 500, "tool": "finish"}))
        assert len(a["thought"]) == 400


class TestCompact:
    def _msgs(self, n_steps):
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "brief"}]
        for i in range(n_steps):
            msgs.append({"role": "assistant", "content": json.dumps({"thought": f"s{i}", "tool": "list_files", "args": {"path": "."}})})
            msgs.append({"role": "user", "content": f"RESULT {i}"})
        return msgs

    def test_short_conversations_pass_through(self):
        from backend.tasker import compact

        msgs = self._msgs(3)
        assert compact(msgs) == msgs

    def test_old_steps_become_a_log_and_big_writes_shrink(self):
        from backend.tasker import KEEP_RECENT, compact

        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "brief"}]
        big = json.dumps({"thought": "scrivo", "tool": "write_file", "args": {"path": "big.md", "content": "c" * 500}}, ensure_ascii=False)
        msgs += [{"role": "assistant", "content": big}, {"role": "user", "content": "ok"}]
        msgs += [{"role": "assistant", "content": json.dumps({"thought": "cerco", "tool": "web_search", "args": {"query": "q"}})}, {"role": "user", "content": "REVISION REQUESTED (attempt 1):\nfix"}]
        steps = self._msgs(20)[2:]
        # step 13 lands inside the KEPT tail but older than the last two
        # assistants: its big write must be shrunk, not dropped
        steps[26] = {"role": "assistant", "content": big}
        msgs += steps
        out = compact(msgs)
        assert len(out) == 2 + KEEP_RECENT
        assert "EARLIER STEPS (compacted):" in out[1]["content"]
        assert "write_file big.md" in out[1]["content"]
        assert "EARLIER INSTRUCTIONS STILL VALID:" in out[1]["content"]  # the REVISION survives compaction
        blob = json.dumps(out)
        assert "c" * 500 not in blob  # no write body survives, dropped or shrunk
        assert "500 chars written" in blob
        assert out[0]["content"] == "sys"
        # the cut lands on an assistant message: the tail starts with one
        assert out[2]["role"] == "assistant"

    def test_last_two_assistant_messages_keep_full_content(self):
        from backend.tasker import compact

        # 4 steps: tail of 8, no drop -- isolates the shrink rule alone.
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "brief"}]
        for i in range(4):
            big = json.dumps({"thought": f"s{i}", "tool": "write_file", "args": {"path": f"f{i}.md", "content": "x" * 400}})
            msgs += [{"role": "assistant", "content": big}, {"role": "user", "content": f"RESULT {i}"}]
        out = compact(msgs)
        assistants = [m["content"] for m in out if m["role"] == "assistant"]
        shrunk = [c for c in assistants if "[400 chars written]" in c]
        full = [c for c in assistants if "x" * 400 in c]
        assert len(shrunk) == 2  # the two oldest assistants are shrunk
        assert len(full) == 2  # the two newest survive intact
        assert "EARLIER STEPS" not in out[1]["content"]


class FakeTeam:
    def __init__(self):
        self.sets = []

    def lead(self, team):
        return {"id": "leo", "name": "Leo"}

    def set(self, id, patch):
        self.sets.append((id, patch))


class FakeRun:
    """The smallest duck that satisfies Tasker: scripted chat() replies."""

    def __init__(self, replies: list[str], missing_first: bool = False):
        self.cfg = {"limits": {"maxSteps": 4}, "teams": {"dev": {"label": "Sviluppo", "title": "Engineer", "brief": "Scrive.", "tools": []}}}
        self.data = {"goal": "obiettivo demo"}
        self.replies = list(replies)
        self.team = FakeTeam()
        self.notes = []
        self.steps = []
        self.tool_calls = []
        self._missing_first = missing_first
        import types

        async def no_hits(*a, **k):  # Brain.search is async since Spec 05
            return []

        self.ctx = types.SimpleNamespace(brain=types.SimpleNamespace(search=no_hits))
        from backend.tools import Workspace
        import tempfile

        self.ws = Workspace(tempfile.mkdtemp())

    def ws_by_id(self, id):
        return {"id": "w1", "title": "WS", "objective": "obiettivo"}

    def inputs_for(self, task):
        return []

    async def skills_text(self, task):
        return ""

    async def gate(self, agent):
        return None

    def take_steering(self, task, agent):
        return []

    async def chat(self, **kwargs):
        return {"text": self.replies.pop(0) if self.replies else "niente"}

    def note(self, task, agent, kind, text, **extra):
        self.notes.append((kind, text))

    def step(self, task, agent, action):
        self.steps.append(action["tool"])

    async def missing_outputs(self, task):
        if self._missing_first:
            self._missing_first = False
            return ["out.md"]
        return []

    async def exec_tool(self, task, agent, action):
        self.tool_calls.append(action["tool"])
        return "fatto"


class TestTaskerWork:
    @pytest.mark.asyncio
    async def test_full_loop_format_error_tool_finish(self):
        from backend.tasker import Tasker

        run = FakeRun(
            [
                "questa non è JSON",  # -> FORMAT ERROR
                json.dumps({"thought": "scrivo", "tool": "write_file", "args": {"path": "out.md", "content": "x"}}),
                json.dumps({"thought": "consegno", "tool": "finish", "args": {"summary": "Fatto tutto", "files": ["out.md"]}}),
            ]
        )
        tasker = Tasker(run, dict(TASK, history=[]), AGENT)
        out = await tasker.work()
        assert out == {"summary": "Fatto tutto", "files": ["out.md"]}
        text = json.dumps(tasker.messages, ensure_ascii=False)
        assert "FORMAT ERROR" in text
        assert "RESULT of write_file" in text
        assert run.tool_calls == ["write_file"]
        assert run.steps == ["write_file", "finish"]
        assert ("error", "Risposta non valida, riprovo") in run.notes

    @pytest.mark.asyncio
    async def test_finish_blocked_until_outputs_exist(self):
        from backend.tasker import Tasker

        run = FakeRun([json.dumps({"thought": "fine", "tool": "finish", "args": {"summary": "s"}})] * 2, missing_first=True)
        tasker = Tasker(run, dict(TASK, history=[]), AGENT)
        out = await tasker.work()
        assert out["summary"] == "s"
        assert out["files"] == TASK["outputs"]  # falls back to the task's own outputs
        assert "CANNOT FINISH YET" in json.dumps(tasker.messages)

    @pytest.mark.asyncio
    async def test_step_limit_returns_flag(self):
        from backend.tasker import Tasker

        run = FakeRun(["non json"] * 10)
        tasker = Tasker(run, dict(TASK, history=[]), AGENT)
        out = await tasker.work()
        assert out == {"stepLimit": True}

    @pytest.mark.asyncio
    async def test_feedback_opens_a_revision_round(self):
        from backend.tasker import Tasker

        run = FakeRun([json.dumps({"thought": "sistemo", "tool": "finish", "args": {"summary": "s", "files": []}})])
        task = dict(TASK, history=[], attempts=2, files=["out.md"])
        tasker = Tasker(run, task, AGENT)
        await tasker.work("Manca la sezione finale")
        assert any(m["role"] == "user" and m["content"].startswith("REVISION REQUESTED (attempt 2)") for m in tasker.messages)

    @pytest.mark.asyncio
    async def test_init_builds_mock_readable_messages(self):
        from backend.router import mock
        from backend.tasker import Tasker

        run = FakeRun([json.dumps({"thought": "fine", "tool": "finish", "args": {"summary": "s"}})])
        tasker = Tasker(run, dict(TASK, history=[]), AGENT)
        await tasker.work()
        system, user = tasker.messages[0]["content"], tasker.messages[1]["content"]
        assert system.startswith("[[role:tasker:dev]]")
        assert mock.field(user, "TASK ID") == "w1.1"
        assert mock.field(user, "GOAL") == "obiettivo demo"
        assert mock.csv(mock.field(user, "OUTPUTS")) == ["out.md"]
