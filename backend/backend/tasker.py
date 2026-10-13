"""Mirrors server/engine/tasker.js: one worker on one subtask. The
conversation survives revisions, so a worker sent back by review keeps
everything it already learned. compact() keeps the context bounded: the
brief stays, old steps become a one-line log, and the content of old file
writes is replaced by its length."""

import json

from backend.json_repair import extract_json
from backend.prompts import TOOL_DOCS, tasker_brief, tasker_system, tools_for

KEEP_RECENT = 16
ALL_TOOLS = list(TOOL_DOCS.keys())


def _dumps(obj) -> str:
    """JSON.stringify without spaces and without escaping non-ASCII."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def describe_step(content: str) -> str:
    a = extract_json(content)
    if not a:
        return "- (unreadable step)"
    args = a.get("args") if isinstance(a.get("args"), dict) else {}
    target = args.get("path") or args.get("url") or args.get("query") or args.get("cmd") or args.get("question") or args.get("name") or ""
    return f"- {a.get('tool')} {str(target)[:80]}"


def shrink_step(content: str) -> str:
    a = extract_json(content)
    if a and a.get("tool") == "write_file" and isinstance(a.get("args"), dict) and isinstance(a["args"].get("content"), str) and len(a["args"]["content"]) > 300:
        return _dumps({**a, "args": {**a["args"], "content": f"[{len(a['args']['content'])} chars written]"}})
    return content


def compact(messages: list[dict]) -> list[dict]:
    head = list(messages[:2])
    tail = list(messages[2:])
    dropped: list[dict] = []
    if len(tail) > KEEP_RECENT:
        cut = len(tail) - KEEP_RECENT
        while cut < len(tail) and tail[cut]["role"] != "assistant":
            cut += 1
        dropped = tail[:cut]
        tail = tail[cut:]
    assistant_at = [i for i, m in enumerate(tail) if m["role"] == "assistant"]
    keep_full_from = assistant_at[-2] if len(assistant_at) >= 2 else 0
    tail = [
        {"role": m["role"], "content": shrink_step(m["content"])} if m["role"] == "assistant" and i < keep_full_from else m
        for i, m in enumerate(tail)
    ]
    if dropped:
        log = [describe_step(m["content"]) for m in dropped if m["role"] == "assistant"]
        keep = [m["content"][:1500] for m in dropped if m["role"] == "user" and (m["content"].startswith("REVISION REQUESTED") or m["content"].startswith("MESSAGE FROM THE USER"))]
        extra = f"\n\nEARLIER INSTRUCTIONS STILL VALID:\n{'\n---\n'.join(keep)}" if keep else ""
        head[1] = {"role": "user", "content": f"{head[1]['content']}\n\nEARLIER STEPS (compacted):\n{chr(10).join(log)}{extra}"}
    return [*head, *tail]


def parse_action(text: str, allowed: list[str] | None = None) -> dict | None:
    allowed = allowed or ALL_TOOLS
    obj = extract_json(text)
    if not obj:
        return None
    action = obj.get("action")
    tool = obj.get("tool")
    if tool is None and isinstance(action, dict):
        tool = action.get("tool")
    if tool is None:
        tool = obj.get("name")
    if tool is None:
        tool = action
    if not isinstance(tool, str) or tool not in allowed:
        return None
    args = obj.get("args")
    if args is None:
        args = obj.get("arguments")
    if args is None and isinstance(action, dict):
        args = action.get("args")
    if args is None:
        args = obj.get("parameters")
    if not isinstance(args, dict):
        args = {}
    return {"thought": str(obj.get("thought") if obj.get("thought") is not None else obj.get("reasoning") or "")[:400], "tool": tool, "args": args}


class Tasker:
    def __init__(self, run, task: dict, agent: dict):
        self.run = run
        self.task = task
        self.agent = agent
        self.messages: list[dict] | None = None
        self.use: str | None = None  # combo override after an escalation
        self.tools = tools_for(run.cfg, task["team"])

    async def init(self) -> None:
        run, task, agent = self.run, self.task, self.agent
        cfg = run.cfg
        ws = run.ws_by_id(task["wsId"])
        inputs = run.inputs_for(task)
        memory = "\n".join(f"- {n['title']}: {n['text'][:280]}" for n in run.ctx.brain.search(f"{task['title']} {task['description']}", 3, agent_id=agent["id"]))
        self.messages = [
            {"role": "system", "content": tasker_system(agent=agent, team_cfg=cfg["teams"][task["team"]], lead=run.team.lead(task["team"]), tools=self.tools, skills_text=await run.skills_text(task))},
            {"role": "user", "content": tasker_brief(goal=run.data["goal"], ws=ws, task=task, inputs=inputs, files=await run.ws.list_text(), memory=memory)},
        ]

    async def work(self, feedback: str | None = None) -> dict:
        run, task, agent = self.run, self.task, self.agent
        if self.messages is None:
            await self.init()
        if feedback:
            self.messages.append({"role": "user", "content": f"REVISION REQUESTED (attempt {task['attempts']}):\n{feedback}\n\nFix every point, check the files, then call finish again."})
        max_steps = run.cfg["limits"]["maxSteps"]
        for _step in range(max_steps):
            await run.gate(agent)
            for note in run.take_steering(task, agent):
                self.messages.append({"role": "user", "content": f"MESSAGE FROM THE USER (the owner): {note}\nTake it into account from now on."})
            run.team.set(agent["id"], {"state": "thinking", "tool": None, "toolTarget": None})
            res = await run.chat(role=task["team"], use=self.use, messages=compact(self.messages), json=True, max_tokens=8000, agent=agent, task=task)
            action = parse_action(res["text"], self.tools)
            if not action:
                self.messages.append({"role": "assistant", "content": res["text"][:2000]})
                self.messages.append({"role": "user", "content": f'FORMAT ERROR: reply with exactly one JSON object {{"thought": "...", "tool": "one of {", ".join(self.tools)}", "args": {{...}}}} and nothing else.'})
                run.note(task, agent, "error", "Risposta non valida, riprovo")
                continue
            self.messages.append({"role": "assistant", "content": _dumps(action)})
            run.step(task, agent, action)

            if action["tool"] == "finish":
                missing = await run.missing_outputs(task)
                if missing:
                    self.messages.append({"role": "user", "content": f"CANNOT FINISH YET: these expected files are missing or empty: {', '.join(missing)}. Create them first."})
                    continue
                files = action["args"].get("files")
                return {"summary": str(action["args"].get("summary") or "")[:2000], "files": [str(f) for f in files] if isinstance(files, list) else task["outputs"]}
            observation = await run.exec_tool(task, agent, action)
            self.messages.append({"role": "user", "content": f"RESULT of {action['tool']}:\n{observation}"})
        return {"stepLimit": True}
