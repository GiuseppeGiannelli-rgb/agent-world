"""Spec 11 T04: the Tasker's checkpoints and its time-travel at the escalation.

- A worker takes a light snapshot of its subtask after the brief and after every
  valid step; the first error (a reply that is not JSON, a tool that fails, a
  finish refused, a rejection) makes its context dirty.
- When it reaches limits.escalateAfter rejections and moves to the escalation
  combo, its conversation goes back to the last clean snapshot: the attempts the
  review rejected come back as one revision, not as a trail of errors.
- The snapshots reach the disk while the run works (data/runs/sessions/), not
  only when it ends: a server that dies mid-run no longer loses its workers."""

import asyncio
import json
from pathlib import Path

import pytest

from test_attachments import ctx  # noqa: F401 -- the fixture

DOC = "Un documento di analisi per il bar"


async def until(pred, timeout=60.0, step=0.01):
    for _ in range(int(timeout / step)):
        if pred():
            return True
        await asyncio.sleep(step)
    raise AssertionError("condition not reached")


def act(tool, **args):
    return json.dumps({"thought": tool, "tool": tool, "args": args})


@pytest.mark.asyncio
async def test_the_escalation_rewinds_the_worker_to_its_last_clean_snapshot(ctx, monkeypatch):  # noqa: F811
    from backend.plan import new_task
    from backend.run import Run

    run = Run(goal=DOC, ctx=ctx)
    run.data["workstreams"] = [{"id": "w1", "team": "research", "title": "t", "objective": "o", "deliverables": ["out.md"], "acceptance": [], "dependsOn": [], "status": "running"}]
    task = new_task({"id": "w1.1", "wsId": "w1", "team": "research", "title": "Analisi", "description": "d", "acceptance": [], "outputs": ["out.md"], "dependsOn": []})
    run.data["tasks"] = [task]
    replies = iter(
        [
            act("list_files", path="."),  # attempt 1: a valid step, the last clean one
            "this is not JSON",  # the first error
            act("write_file", path="out.md", content="v1"),
            act("finish", summary="one", files=["out.md"]),
            act("write_file", path="out.md", content="v2"),  # attempt 2
            act("finish", summary="two", files=["out.md"]),
            act("read_file", path="out.md"),  # attempt 3, on the escalation combo
            act("write_file", path="out.md", content="v3 with sources"),
            act("finish", summary="three", files=["out.md"]),
        ]
    )
    sent = []
    real = run.chat

    async def chat(**kw):
        if not kw["messages"][0]["content"].startswith("[[role:tasker"):
            return await real(**kw)
        sent.append(kw)
        return {"text": next(replies), "target": "mock/mock-research", "profile": {"key": "mock/mock-research", "compact": False, "tier": "smart"}}

    verdicts = iter([("revise", "Add the sources"), ("revise", "Still no sources"), ("pass", "")])

    async def review(task, agent, out):
        verdict, feedback = next(verdicts)
        v = {"verdict": verdict, "score": 6, "feedback": feedback, "judgeId": "bruno", "attempt": task["attempts"], "security": False, "ts": 0}
        task["verdicts"].append(v)
        return v

    monkeypatch.setattr(run, "chat", chat)
    monkeypatch.setattr(run, "review", review)
    agent = next(a for a in ctx.team.list() if a["team"] == "research" and a["kind"] == "worker")
    await asyncio.wait_for(run.run_task(task, agent), timeout=30)

    assert task["status"] == "done" and task["escalated"] and run.data["usage"]["escalations"] == 1
    first = next(kw for kw in sent if kw.get("use") == "frontier")
    msgs = first["messages"]
    # the system prompt, the brief, the clean step and its result, then one revision
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user", "user"]
    assert json.loads(msgs[2]["content"])["tool"] == "list_files"
    assert not any("FORMAT ERROR" in m["content"] or "this is not JSON" in m["content"] for m in msgs)
    revision = msgs[-1]["content"]
    assert revision.startswith("REVISION REQUESTED (attempt 3)")
    assert "- attempt 1: Add the sources" in revision and "- attempt 2: Still no sources" in revision and "out.md" in revision
    kinds = [h["kind"] for h in task["history"]]
    assert kinds.index("rewind") == kinds.index("escalate") + 1
    note = task["history"][kinds.index("rewind")]
    # dropped: the format error (2), the write and the finish of attempt 1 (3), the old revision and attempt 2 (4)
    assert (note["step"], note["dropped"]) == (1, 9)
    assert note["text"] == run.t("rewind_note", step=1, dropped=9)
    assert task["checkpoint"] == {"step": 4, "attempt": 3, "clean": True}  # the clean point, read, write, finish


@pytest.mark.asyncio
async def test_a_demo_mission_rewinds_its_escalated_task(ctx, monkeypatch):  # noqa: F811
    """The demo of "A simple document about coffee" escalates w2.1 (the simulator
    rejects it twice). Before T04 its first call on "frontier" carried 18 messages,
    with both revisions and the 8 steps of the two rejected attempts."""
    from backend.run import Run

    sent = []
    real = ctx.router.chat

    async def spy(**kw):
        sent.append(kw)
        return await real(**kw)

    monkeypatch.setattr(ctx.router, "chat", spy)
    run = Run(goal="A simple document about coffee", ctx=ctx, options={"language": "en"})
    await asyncio.wait_for(run.start(), timeout=120)
    assert run.data["status"] == "completed", run.data["error"]
    task = next(t for t in run.data["tasks"] if t["escalated"])
    calls = [kw for kw in sent if kw["messages"][0]["content"].startswith("[[role:tasker") and f"TASK ID: {task['id']}" in kw["messages"][1]["content"]]
    up = [i for i, kw in enumerate(calls) if kw.get("use") == "frontier"]
    msgs = calls[up[0]]["messages"]
    revisions = [m["content"] for m in msgs if m["role"] == "user" and m["content"].startswith("REVISION REQUESTED")]
    assert len(revisions) == 1 and msgs[-1]["content"] == revisions[0]
    assert "- attempt 1: " in revisions[0] and "- attempt 2: " in revisions[0]
    # the simulator makes no format error: the clean point is the end of attempt 1
    # (compared by shape: compact() shrinks the body of the older writes)
    last_of_attempt_1 = next(kw["messages"] for kw in reversed(calls[: up[0]]) if not any(m["content"].startswith("REVISION REQUESTED") for m in kw["messages"]))
    assert shape(msgs[: len(last_of_attempt_1)]) == shape(last_of_attempt_1)
    assert shape(msgs[len(last_of_attempt_1) :]) == [("assistant", "finish"), ("user", "REVISION REQUESTED (attempt 3)")]
    assert any(h["kind"] == "rewind" for h in task["history"])


def shape(messages):
    """(role, tool) of each message: the tool of a step, the opening of the rest."""
    from backend.json_repair import extract_json

    out = []
    for m in messages:
        if m["role"] == "assistant":
            out.append(("assistant", (extract_json(m["content"]) or {}).get("tool")))
        else:
            out.append((m["role"], m["content"].split(":")[0] if m["role"] == "user" else m["content"][:20]))
    return out


@pytest.mark.asyncio
async def test_the_checkpoints_reach_the_disk_while_the_run_works(ctx):  # noqa: F811
    """D18: the conversation of a worker is on disk within moments of its last
    valid step, while the run works. Before T04 it was written only when the run
    ended: a server that died mid-run lost every worker, and the resume started
    them from scratch."""
    from backend.run import Run

    run = Run(goal=DOC, ctx=ctx)
    started = asyncio.ensure_future(run.start())
    mid = {}

    def mid_task():
        for t in run.data["tasks"]:
            if t["status"] == "working" and len([h for h in t["history"] if h["kind"] == "step"]) >= 2:
                mid["id"] = t["id"]
                return True
        return False

    await until(mid_task)
    run.pause()  # the workers wait at their next step: nothing ends, nothing is saved at the end
    f = Path(ctx.store.dir) / "sessions" / f"{run.data['id']}.json"

    def saved():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data.get(mid["id"])

    try:
        await until(lambda: saved() is not None, timeout=5)
        session = saved()
        assert run.data["status"] == "running"
        assert any(m["role"] == "assistant" for m in session["messages"])
        assert session["step"] >= 1 and session["model"]
        assert run.task_by_id(mid["id"])["checkpoint"]["step"] >= 1
    finally:
        run.stop()
        await asyncio.wait_for(started, timeout=30)
