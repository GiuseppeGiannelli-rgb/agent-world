"""Contract tests for backend/tasker.py, ported from server/engine/tasker.js.
The Tasker loop is exercised against a scripted FakeRun -- no model, no
filesystem beyond tmp_path."""

import json

import pytest

from backend.i18n import tr

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

    def role_combo(self, kind):  # spec 08
        return None

    def model_profile(self, role, use=None):  # spec 08
        from backend.router import profiler

        return profiler.profile("mock/mock-dev")

    async def rag_context(self, task, agent, profile, reason="start", extra=""):  # spec 08
        return {"skills": await self.skills_text(task), "memory": "", "shared": "", "jsonContract": False}

    async def gate(self, agent):
        return None

    def take_steering(self, task, agent):
        return []

    async def chat(self, **kwargs):
        return {"text": self.replies.pop(0) if self.replies else "niente"}

    def note(self, task, agent, kind, text, **extra):
        self.notes.append((kind, text))

    def t(self, key, **vars):  # Run.t: the run's own texts, in the run's language
        return tr(self.data.get("language"), key, **vars)

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
        assert ("error", tr(None, "invalid_answer")) in run.notes  # N17: English without a language

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


# ---------- spec 11 T04: checkpoints and time-travel ----------


def act(tool, **args):
    return json.dumps({"thought": tool, "tool": tool, "args": args})


FINISH = act("finish", summary="s", files=["out.md"])


class CheckpointRun(FakeRun):
    """A FakeRun that records the checkpoints it is given, fails the tools aimed at
    the paths it is told to, hands the owner's words before a chosen model call and
    has a run memory whose cursor moves with every call."""

    def __init__(self, replies, errors=(), notes=None, **kw):
        super().__init__(replies, **kw)
        self.cfg["limits"]["maxSteps"] = 10
        self.errors = set(errors)
        self.notes_at = dict(notes or {})  # model calls made so far -> the owner's words before the next one
        self.calls = 0
        self.cursor = 0
        self.saved = []
        self.seen_attachments = {}

    def take_steering(self, task, agent):
        note = self.notes_at.pop(self.calls, None)
        return [note] if note else []

    async def chat(self, **kwargs):
        self.calls += 1
        self.cursor += 1
        return await super().chat(**kwargs)

    def memory_cursor(self):
        return self.cursor

    def cross_update(self, task, since, profile, switched=False):
        return None, self.cursor  # nothing linked to deliver, the cursor moves on

    async def exec_tool(self, task, agent, action):
        self.tool_calls.append(action["tool"])
        if action["tool"] == "ask_user":
            return "The owner answers: blue, like the logo"
        target = action["args"].get("path") or ""
        return f"ERROR: {target} is not a file of this project." if target in self.errors else "fatto"

    def checkpoint(self, task, tasker, cp):
        self.saved.append(dict(cp))


def marks(tasker):
    return [(c["step"], c["at"], c["clean"]) for c in tasker.checkpoints]


@pytest.mark.asyncio
async def test_a_snapshot_after_the_brief_and_after_every_valid_step():
    """Spec 11 T04 (D16): a snapshot does not copy the conversation (it only grows at
    its end): it marks its length, with the step, the attempt, the cross-agent cursor
    and whether the context is still clean. One after the brief, one after every
    valid step (a tool that ran, a finish accepted); the first error makes the context
    dirty, and the snapshots after it are not clean."""
    from backend.tasker import Tasker

    run = CheckpointRun([act("list_files", path="."), "not json", act("write_file", path="out.md", content="x"), FINISH])
    tasker = Tasker(run, dict(TASK, history=[], attempts=1), AGENT)
    await tasker.work()
    # brief = 2 messages; list_files +2; the format error +2 (no snapshot); write_file +2; finish +1
    assert marks(tasker) == [(0, 2, True), (1, 4, True), (2, 8, False), (3, 9, False)]
    assert all(c["attempt"] == 1 for c in tasker.checkpoints)
    assert [c["cursor"] for c in tasker.checkpoints] == [0, 0, 2, 3]  # the cursor of the context at that point
    assert run.saved == tasker.checkpoints  # every snapshot reaches the run (and from there the disk)


@pytest.mark.asyncio
async def test_a_tool_error_or_a_refused_finish_is_no_valid_step():
    from backend.tasker import Tasker

    run = CheckpointRun([act("read_file", path="missing.md"), FINISH], errors={"missing.md"})
    tasker = Tasker(run, dict(TASK, history=[], attempts=1), AGENT)
    await tasker.work()
    assert marks(tasker) == [(0, 2, True), (1, 5, False)]  # the failed read is no step, and it dirties

    run = CheckpointRun([FINISH, FINISH], missing_first=True)
    tasker = Tasker(run, dict(TASK, history=[], attempts=1), AGENT)
    await tasker.work()
    assert marks(tasker) == [(0, 2, True), (1, 5, False)]  # "CANNOT FINISH YET" is an error too

    run = CheckpointRun([act("write_file", path="out.md", content=""), FINISH])
    tasker = Tasker(run, dict(TASK, history=[], attempts=1), AGENT)
    await tasker.init()
    tasker.shape = "small"  # spec 10 §R4: a small model's action without its arguments
    await tasker.work()
    assert marks(tasker) == [(0, 2, True), (1, 5, False)]


def run_with_two_rejections(**kw):
    """Attempt 1: a valid step, a format error, a write, a finish (rejected); attempt 2,
    after the owner's words: another write and a finish (rejected); attempt 3: a finish."""
    return CheckpointRun(
        [
            act("list_files", path="."),
            "not json",
            act("write_file", path="out.md", content="v1"),
            FINISH,
            act("write_file", path="assets/extra.md", content="v2"),
            FINISH,
            FINISH,
        ],
        notes={4: "Use a warmer tone"},
        **kw,
    )


@pytest.mark.asyncio
async def test_the_escalation_goes_back_to_the_last_clean_snapshot():
    """D17: at the escalation the conversation goes back to the last clean snapshot.
    On top come back the owner's words said since, then one revision with every
    rejection since (attempt by attempt) and the files the rejected attempts left in
    the folder. The format error, the old revision and the rejected steps are gone;
    the cross-agent cursor is the snapshot's; the context is clean again."""
    from backend.tasker import Tasker

    run = run_with_two_rejections()
    task = dict(TASK, history=[], attempts=1)
    tasker = Tasker(run, task, AGENT)
    await tasker.work()
    task["attempts"] = 2
    await tasker.work("Missing the final section")
    before = list(tasker.messages)
    assert len(before) == 14 and before[9]["content"].startswith("REVISION REQUESTED (attempt 2)")
    owner = before[10]
    assert owner["content"].startswith("MESSAGE FROM THE USER (the owner): Use a warmer tone")
    assert tasker.cross_cursor == 5

    assert tasker.rewind() == {"step": 1, "dropped": 9}
    assert tasker.messages == [*before[:4], owner]
    assert tasker.cross_cursor == 0  # the cursor of the clean snapshot: linked work since then comes again
    assert marks(tasker) == [(0, 2, True), (1, 4, True)]

    task["attempts"] = 3
    out = await tasker.work("Still no sources")
    assert out["summary"] == "s"
    text = json.dumps(tasker.messages, ensure_ascii=False)
    assert "FORMAT ERROR" not in text and "not json" not in text
    revisions = [m["content"] for m in tasker.messages if m["role"] == "user" and m["content"].startswith("REVISION REQUESTED")]
    assert len(revisions) == 1 and revisions[0].startswith("REVISION REQUESTED (attempt 3)")
    assert "- attempt 1: Missing the final section" in revisions[0] and "- attempt 2: Still no sources" in revisions[0]
    assert "out.md" in revisions[0] and "assets/extra.md" in revisions[0]  # the files of the rejected attempts
    assert tasker.messages[:5] == [*before[:4], owner]
    # the revision is the new clean point, then the step of the stronger model
    assert marks(tasker) == [(0, 2, True), (1, 4, True), (1, 6, True), (2, 7, True)]


@pytest.mark.asyncio
async def test_the_owners_answer_survives_the_rewind():
    """The owner's answer to the worker's question (ask_user) is the owner's word
    too: it comes back after the clean point, with the question it answers."""
    from backend.tasker import Tasker

    run = CheckpointRun([act("list_files", path="."), "not json", act("ask_user", question="Which colour?"), FINISH, FINISH])
    task = dict(TASK, history=[], attempts=1)
    tasker = Tasker(run, task, AGENT)
    await tasker.work()
    task["attempts"] = 2
    await tasker.work("Missing the final section")
    before = list(tasker.messages)
    assert before[7]["content"].startswith("RESULT of ask_user:\nThe owner answers: blue")
    assert tasker.rewind() == {"step": 1, "dropped": 5}
    assert tasker.messages == [*before[:4], before[6], before[7]]


@pytest.mark.asyncio
async def test_no_rewind_on_a_clean_context():
    from backend.tasker import Tasker

    run = CheckpointRun([act("list_files", path="."), FINISH])
    tasker = Tasker(run, dict(TASK, history=[], attempts=1), AGENT)
    await tasker.work()
    before = list(tasker.messages)
    assert tasker.rewind() is None
    assert tasker.messages == before
    assert "clean" not in tasker.session()  # a clean worker saves no second copy


@pytest.mark.asyncio
async def test_a_resumed_worker_keeps_its_clean_point():
    """D18: the session of a dirty worker carries its clean point (the conversation
    compacted, the owner's words and the files since, the rejections): after a
    resume the rewind still lands there."""
    from backend.tasker import Tasker

    run = run_with_two_rejections()
    task = dict(TASK, history=[], attempts=1)
    tasker = Tasker(run, task, AGENT)
    await tasker.work()
    task["attempts"] = 2
    await tasker.work("Missing the final section")
    saved = json.loads(json.dumps(tasker.session()))
    clean = saved["clean"]
    assert clean["messages"] == tasker.messages[:4]
    assert [m["content"] for m in clean["owner"]] == [tasker.messages[10]["content"]]
    assert clean["files"] == ["out.md", "assets/extra.md"]
    assert clean["rejections"] == [{"attempt": 1, "feedback": "Missing the final section"}]
    assert (clean["step"], saved["step"]) == (1, 5)  # list, write, finish, write, finish
    assert "cursor" not in clean  # the run memory is rebuilt at a resume: an old cursor means nothing there

    again = Tasker(CheckpointRun([FINISH]), task, AGENT)
    again.restore(saved)
    assert again.messages[-1]["content"].startswith("RUN RESUMED")
    assert again.rewind() == {"step": 1, "dropped": len(saved["messages"]) + 1 - 5}
    assert again.messages == [*clean["messages"], *clean["owner"]]
    # stopped right after the rewind, before its revision: the rejections are not lost
    pending = json.loads(json.dumps(again.session()))
    assert pending["rewound"] == {"files": ["out.md", "assets/extra.md"], "rejections": [{"attempt": 1, "feedback": "Missing the final section"}]}
    later = Tasker(CheckpointRun([FINISH]), task, AGENT)
    later.restore(pending)
    task["attempts"] = 3
    await later.work("Still no sources")
    revision = next(m["content"] for m in later.messages if m["content"].startswith("REVISION REQUESTED"))
    assert "- attempt 1: Missing the final section" in revision and "- attempt 2: Still no sources" in revision and "out.md" in revision
    assert sum(1 for m in later.messages if m["content"].startswith("REVISION REQUESTED")) == 1


def test_compaction_never_drops_what_the_owner_said_or_gave():
    """Spec 09: the owner's words to a task and the files they added stay valid
    after compaction, like a revision request."""
    from backend.tasker import KEEP_RECENT, compact

    head = [{"role": "system", "content": "[[role:tasker:dev]]"}, {"role": "user", "content": "GOAL: g"}]
    early = [
        {"role": "user", "content": "MESSAGE FROM THE OWNER about this task: use my photo for the hero"},
        {"role": "user", "content": "FILES FROM THE OWNER (just added; ...):\n- attachments/hero.jpg (image jpeg 1600x900)"},
    ]
    steps = [m for i in range(KEEP_RECENT) for m in ({"role": "assistant", "content": '{"tool": "list_files", "args": {}}'}, {"role": "user", "content": f"RESULT of list_files:\n{i}"})]
    out = compact(head + early + steps)
    assert "use my photo for the hero" in out[1]["content"] and "attachments/hero.jpg (image jpeg 1600x900)" in out[1]["content"]
    assert len(out) < len(head + early + steps)
