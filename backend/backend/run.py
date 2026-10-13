"""Mirrors server/engine/run.js: the mission orchestrator -- plan, schedule,
work, review, wrap up.

Adaptations from Node, all forced by asyncio (documented, not silent):
- AbortController -> an asyncio.Event (`self._abort`); every cancellable
  wait (sleep, gate, schedule, the QA acquire) watches it and raises
  RunStopped, which start() maps to the "stopped" status exactly like
  Node's aborted branch. stop() never cancels tasks from outside.
- Router.chat() has no signal parameter (P3): a stop lands at the next
  gate between steps, not mid-request.
- Node's setTimeout debounce in emitRun -> loop.call_later; with no running
  loop (sync callers in tests) the frame is emitted inline instead.
- new Date().toISOString() -> ISO 8601 UTC with milliseconds and "Z", so
  run files written by either backend stay interchangeable.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.json_repair import extract_json
from backend.plan import normalize_plan, normalize_subtasks, safe_rel_path, single_subtask, slugify, strings
from backend.prompts import (
    advisor_prompt,
    ceo_plan_prompt,
    judge_prompt,
    lead_plan_prompt,
    librarian_prompt,
    prompt_eng_prompt,
    rescue_prompt,
    synth_prompt,
    work_teams,
)
from backend.tasker import Tasker
from backend.tools import Workspace, run_command
from backend.web import web_fetch, web_search

TERMINAL = {"done", "failed", "skipped"}
TERMINAL_RUN = {"completed", "completed_with_failures", "failed", "stopped"}
TEXT_EXT = {".md", ".txt", ".html", ".htm", ".css", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".svg", ".py", ".csv", ".yml", ".yaml", ".xml", ".sh", ".php", ".sql"}


def clip(s: str, n: int) -> str:
    return f"{s[:n]}\n… [truncated, {len(s) - n} more chars]" if len(s) > n else s


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class RunStopped(Exception):
    """Raised inside a run when stop() lands; start() maps it to 'stopped'."""


class Run:
    def __init__(self, *, goal: str, ctx, options: dict | None = None):
        options = options or {}
        self.ctx = ctx
        self._abort = asyncio.Event()
        self._resume = asyncio.Event()
        self._resume.set()
        self.active: set[str] = set()
        self.preparing: set[str] = set()
        self.answer_waiters: dict[str, object] = {}
        self.steering: list[dict] = []
        self.seen_steering: dict[str, set] = {}
        self._last_run_emit = 0.0
        self._run_emit_timer: asyncio.TimerHandle | None = None
        self._finish_schedule: asyncio.Event | None = None
        run_id = uuid.uuid4().hex[:8]
        slug = f"{slugify(goal)}-{run_id}"
        approve = options["approvePlan"] if "approvePlan" in options else ctx.config.get()["limits"].get("approvePlan")
        self.data = {
            "id": run_id,
            "slug": slug,
            "goal": goal,
            "status": "planning",
            "complexity": None,
            "paused": False,
            "approvePlan": bool(approve),
            "mode": ctx.router.mode(),
            "createdAt": _iso_now(),
            "finishedAt": None,
            "planSummary": "",
            "workstreams": [],
            "tasks": [],
            "messages": [],
            "waiting": [],
            "report": "",
            "error": None,
            "usage": {"calls": 0, "tokensIn": 0, "tokensOut": 0, "escalations": 0, "subAgents": 0},
            "workspace": str(Path(ctx.workspace_root) / slug),
        }
        self.ws = Workspace(self.data["workspace"])

    @property
    def cfg(self) -> dict:
        return self.ctx.config.get()

    @property
    def team(self):
        return self.ctx.team

    @property
    def ceo(self) -> dict:
        return self.team.ceo()

    def task_by_id(self, id: str) -> dict | None:
        return next((t for t in self.data["tasks"] if t["id"] == id), None)

    def ws_by_id(self, id: str) -> dict | None:
        return next((w for w in self.data["workstreams"] if w["id"] == id), None)

    # ---------- events ----------

    def emit_run(self, force: bool = False) -> None:
        self.ctx.store.save(self.data, force)
        now = time.time() * 1000
        if not force and now - self._last_run_emit < 200:
            if self._run_emit_timer is not None:
                self._run_emit_timer.cancel()
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None  # sync caller (tests): emit inline instead
            if loop is not None:
                self._run_emit_timer = loop.call_later(0.22, self.emit_run, True)
                return
        if self._run_emit_timer is not None:
            self._run_emit_timer.cancel()
            self._run_emit_timer = None
        self._last_run_emit = now
        self.ctx.bus.emit("run", self.data)

    def emit_task(self, task: dict) -> None:
        self.ctx.bus.emit("task", {"runId": self.data["id"], "task": task})
        self.emit_run()

    def emit_ws(self, ws: dict) -> None:
        self.ctx.bus.emit("workstream", {"runId": self.data["id"], "ws": ws})
        self.emit_run()

    def message(self, from_: str, to: str, kind: str, text: str) -> None:
        m = {"id": uuid.uuid4().hex[:8], "runId": self.data["id"], "ts": _now_ms(), "from": from_, "to": to, "kind": kind, "text": str(text)[:4000]}
        self.data["messages"].append(m)
        if len(self.data["messages"]) > 800:
            del self.data["messages"][: len(self.data["messages"]) - 800]
        self.ctx.bus.emit("message", m)
        self.emit_run()

    def note(self, task: dict, agent: dict, kind: str, text: str, **extra) -> None:
        task["history"].append({"ts": _now_ms(), "agentId": agent["id"], "kind": kind, "text": str(text)[:600], **extra})
        if len(task["history"]) > 80:
            del task["history"][: len(task["history"]) - 80]

    def step(self, task: dict, agent: dict, action: dict) -> None:
        a = action["args"]
        target = a.get("path") or a.get("url") or a.get("query") or a.get("cmd") or a.get("question") or a.get("name") or a.get("title") or a.get("prompt") or ""
        self.note(task, agent, "step", action["thought"], tool=action["tool"], target=str(target)[:200])
        self.team.set(agent["id"], {"state": "thinking" if action["tool"] == "finish" else "tool", "tool": action["tool"], "text": action["thought"], "toolTarget": str(target)[:120]})
        self.emit_run()

    # ---------- flow control ----------

    async def sleep(self, ms: float) -> None:
        if self._abort.is_set():
            raise RunStopped("Stopped by the user")
        try:
            await asyncio.wait_for(self._abort.wait(), timeout=max(ms, 0) / 1000)
        except asyncio.TimeoutError:
            return
        raise RunStopped("Stopped by the user")

    async def gate(self, agent: dict | None = None) -> None:
        if self._abort.is_set():
            raise RunStopped("Stopped by the user")
        if not self.data["paused"]:
            return
        if agent:
            self.team.set(agent["id"], {"state": "paused"})
        await self._resume.wait()
        if self._abort.is_set():
            raise RunStopped("Stopped by the user")
        if agent:
            self.team.set(agent["id"], {"state": "thinking"})

    def pause(self) -> None:
        if self.data["status"] in TERMINAL_RUN:
            return
        self.data["paused"] = True
        self._resume.clear()
        self.message(self.ceo["id"], "*", "system", "Run in pausa: il lavoro in corso termina il passo attuale.")
        self.emit_run(True)

    def resume(self) -> None:
        if not self.data["paused"]:
            return
        self.data["paused"] = False
        self._resume.set()
        self.message(self.ceo["id"], "*", "system", "Si riparte.")
        self.emit_run(True)
        self.tick()

    def stop(self) -> None:
        if self.data["status"] in TERMINAL_RUN:
            return
        self._abort.set()
        self._resume.set()
        self.team.abort_waiters(self.data["id"])  # close the handoff window, like Node's sync abort listener
        for done in list(self.answer_waiters.values()):
            done(None)

    # The owner's messages, routed to everyone ("all"), a team or one agent.
    def steer(self, scope: str, text: str) -> None:
        self.steering.append({"id": uuid.uuid4().hex[:6], "scope": scope, "text": str(text)[:2000]})

    def take_steering(self, task: dict, agent: dict) -> list[str]:
        seen = self.seen_steering.setdefault(agent["id"], set())
        scopes = {"all", f"team:{task['team']}", f"agent:{agent['id']}"}
        fresh = [s for s in self.steering if s["scope"] in scopes and s["id"] not in seen]
        for s in fresh:
            seen.add(s["id"])
        return [s["text"] for s in fresh]

    # ---------- waiting for the owner ----------

    def add_waiting(self, item: dict) -> dict:
        w = {"id": uuid.uuid4().hex[:8], "status": "open", "answer": None, "createdAt": _now_ms(), **item}
        self.data["waiting"].append(w)
        self.ctx.bus.emit("waiting", {"runId": self.data["id"], "item": w})
        self.emit_run(True)
        return w

    async def wait_answer(self, item: dict, timeout_ms: float):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        timer = None

        def done(answer) -> None:
            nonlocal timer
            if timer is not None:
                timer.cancel()
                timer = None
            self.answer_waiters.pop(item["id"], None)
            if item["status"] == "open":
                item["status"] = "answered" if answer else "expired"
            self.ctx.bus.emit("waiting", {"runId": self.data["id"], "item": item})
            self.emit_run(True)
            if not future.done():
                future.set_result(answer)

        self.answer_waiters[item["id"]] = done
        if timeout_ms:
            timer = loop.call_later(timeout_ms / 1000, done, None)
        return await future

    def answer(self, id: str, answer: dict) -> bool:
        text = answer.get("text", "")
        decision = answer.get("decision") if answer.get("decision") in ("approve", "reject") else None
        item = next((w for w in self.data["waiting"] if w["id"] == id), None)
        done = self.answer_waiters.get(id)
        if not item or not done or item["status"] != "open":
            return False
        item["answer"] = {"text": str(text)[:4000], "decision": decision, "at": _now_ms()}
        item["status"] = "answered"
        label = f"{'Approvato' if decision == 'approve' else 'Rifiutato'}{': ' + text if text else ''}" if decision else text
        self.message("user", item["from"], "reply", label)
        done(item["answer"])
        return True

    # ---------- model calls ----------

    async def chat(self, *, role, use=None, messages, json=False, max_tokens=None, agent=None, task=None) -> dict:
        res = await self.ctx.router.chat(
            role=role,
            use=use,
            messages=messages,
            json=json,
            max_tokens=max_tokens,
            meta={"runId": self.data["id"], "taskId": task["id"] if task else None, "agentId": agent["id"] if agent else None},
        )
        usage = self.data["usage"]
        usage["calls"] += 1
        usage["tokensIn"] += (res.get("usage") or {}).get("in", 0)
        usage["tokensOut"] += (res.get("usage") or {}).get("out", 0)
        if agent and self.team.get(agent["id"]):
            self.team.get(agent["id"])["model"] = res["target"]
        return res

    async def chat_json(self, opts: dict, validate=None, tries: int = 2):
        messages = list(opts["messages"])
        for _ in range(tries):
            res = await self.chat(**{**opts, "messages": messages}, json=True)
            obj = extract_json(res["text"])
            if obj and (not validate or validate(obj)):
                return obj
            messages = [*messages, {"role": "assistant", "content": res["text"][:3000]}, {"role": "user", "content": "That was not the JSON object I asked for. Reply again with ONLY the JSON object, exactly in the requested shape."}]
        return None

    # ---------- lifecycle ----------

    async def start(self) -> None:
        try:
            await self.ws.ensure()
            await self.plan()
            if self.data["approvePlan"]:
                await self.approval()
            self.data["status"] = "running"
            self.emit_run(True)
            await self.schedule()
            self.data["status"] = "synthesizing"
            self.emit_run(True)
            await self.synthesize()
            failed = any(w["status"] != "done" for w in self.data["workstreams"])
            self.data["status"] = "completed_with_failures" if failed else "completed"
        except RunStopped as err:
            self.data["status"] = "stopped"
            if self.data["error"] is None:
                self.data["error"] = None if str(err) == "Stopped by the user" else str(err)
            for t in self.data["tasks"]:
                if t["status"] not in TERMINAL:
                    t["status"] = "skipped"
            for w in self.data["workstreams"]:
                if w["status"] not in TERMINAL:
                    w["status"] = "skipped"
        except Exception as err:
            self.data["status"] = "failed"
            self.data["error"] = str(err)
            self.message(self.ceo["id"], "*", "error", f"Il run si è fermato: {err}")
        finally:
            self.data["finishedAt"] = _iso_now()
            self.data["paused"] = False
            for w in self.data["waiting"]:
                if w["status"] == "open":
                    w["status"] = "expired"
            for a in self.team.list():
                if a["runId"] == self.data["id"] or a["kind"] == "ceo":
                    patch = {"state": "celebrating", "text": "Missione compiuta!"} if a["kind"] == "ceo" and self.data["status"] == "completed" else {}
                    self.team.release(a["id"], patch)
            self.emit_run(True)
            self.ctx.bus.emit("run.done", {"runId": self.data["id"], "status": self.data["status"]})

    async def plan(self) -> None:
        ceo = self.ceo
        self.team.set(ceo["id"], {"state": "thinking", "runId": self.data["id"], "text": "Studio l'obiettivo e organizzo i team…"})
        self.message("user", ceo["id"], "goal", self.data["goal"])
        memory = "\n".join(f"- {n['title']}: {n['text'][:240]}" for n in self.ctx.brain.search(self.data["goal"], 4, agent_id=ceo["id"]))
        obj = await self.chat_json(
            {"role": "ceo", "messages": ceo_plan_prompt(cfg=self.cfg, ceo=ceo, goal=self.data["goal"], memory=memory), "max_tokens": 6000, "agent": ceo},
            lambda o: isinstance(o.get("workstreams"), list) and len(o["workstreams"]) > 0,
        )
        if not obj:
            raise Exception("The CEO could not produce a valid plan")
        plan = normalize_plan(obj, self.cfg)
        self.data["complexity"] = plan["complexity"]
        self.data["planSummary"] = plan["summary"]
        self.data["workstreams"] = plan["workstreams"]
        self.ctx.bus.emit("plan", {"runId": self.data["id"], "workstreams": plan["workstreams"], "complexity": plan["complexity"], "summary": plan["summary"]})
        label = lambda t: (self.cfg["teams"].get(t) or {}).get("label") or t
        listing = "\n".join(f"{w['id']} · {w['title']} → {label(w['team'])}{' (dopo ' + ', '.join(w['dependsOn']) + ')' if w['dependsOn'] else ''}" for w in plan["workstreams"])
        self.message(ceo["id"], "*", "plan", f"{'Missione complessa' if plan['complexity'] == 'complex' else 'Missione semplice'}. {plan['summary']}\n\n{listing}")
        self.team.set(ceo["id"], {"state": "idle", "text": f"Piano: {len(plan['workstreams'])} workstream"})
        self.emit_run(True)
        await self.sleep(1200 + len(plan["workstreams"]) * 200)

    async def approval(self) -> None:
        self.data["status"] = "awaiting_approval"
        label = lambda t: (self.cfg["teams"].get(t) or {}).get("label") or t
        item = self.add_waiting({"kind": "plan", "from": self.ceo["id"], "text": f"Approvi il piano?\n{self.data['planSummary']}\n\n" + "\n".join(f"{w['id']} · {w['title']} → {label(w['team'])}" for w in self.data["workstreams"])})
        self.team.set(self.ceo["id"], {"state": "asking", "text": "Aspetto la tua approvazione del piano"})
        answer = await self.wait_answer(item, 0)
        if self._abort.is_set():
            raise RunStopped(str(self.data.get("error") or "Stopped by the user"))
        if answer and answer.get("decision") == "reject":
            self.data["error"] = f"Piano rifiutato{': ' + answer['text'] if answer.get('text') else ''}"
            self._abort.set()
            raise RunStopped(self.data["error"])
        if answer and answer.get("text"):
            self.steer("all", answer["text"])
        self.team.set(self.ceo["id"], {"state": "idle", "text": "Piano approvato"})

    async def schedule(self) -> None:
        self._finish_schedule = asyncio.Event()
        self.tick()
        finish_wait = asyncio.ensure_future(self._finish_schedule.wait())
        abort_watch = asyncio.ensure_future(self._abort.wait())
        await asyncio.wait({finish_wait, abort_watch}, return_when=asyncio.FIRST_COMPLETED)
        finish_wait.cancel()
        abort_watch.cancel()
        if self._abort.is_set():
            raise RunStopped("Stopped by the user")

    def tick(self) -> None:
        if self._finish_schedule is None or self._abort.is_set():
            return
        ws_all = self.data["workstreams"]
        tasks = self.data["tasks"]
        bad = lambda s: s in ("failed", "skipped")

        changed = True
        while changed:
            changed = False
            for w in ws_all:
                blocker = next((d for d in w["dependsOn"] if bad((self.ws_by_id(d) or {}).get("status"))), None)
                if w["status"] == "queued" and blocker:
                    w["status"] = "skipped"
                    w["error"] = f"Dipende da {blocker}, che non è stato completato"
                    self.emit_ws(w)
                    changed = True
            for t in tasks:
                blocker = next((d for d in t["dependsOn"] if bad((self.task_by_id(d) or {}).get("status"))), None)
                if t["status"] == "queued" and blocker:
                    t["status"] = "skipped"
                    t["error"] = f"Dipende da {blocker}, che non è stato completato"
                    self.emit_task(t)
                    changed = True
            for w in ws_all:
                if w["status"] != "running":
                    continue
                mine = [t for t in tasks if t["wsId"] == w["id"]]
                if not mine or not all(t["status"] in TERMINAL for t in mine):
                    continue
                w["status"] = "done" if all(t["status"] == "done" for t in mine) else "failed"
                w["summary"] = " ".join(t["summary"] for t in mine if t["summary"])[:1500]
                w["finishedAt"] = _iso_now()
                self.emit_ws(w)
                lead = self.team.lead(w["team"])
                ok = w["status"] == "done"
                self.message((lead or self.ceo)["id"], self.ceo["id"], "deliver" if ok else "error", f"{w['id']} completato: {w['title']}" if ok else f"{w['id']} chiuso con task non completati")
                changed = True

        if not self.data["paused"]:
            for w in ws_all:
                if w["status"] != "queued" or not all((self.ws_by_id(d) or {}).get("status") == "done" for d in w["dependsOn"]):
                    continue
                lead = self.team.try_acquire_lead(w["team"], self.data["id"])
                if not lead:
                    continue
                w["status"] = "preparing"
                w["leadId"] = lead["id"]
                w["startedAt"] = _iso_now()
                self.preparing.add(w["id"])
                self.emit_ws(w)

                async def prepare_one(w=w, lead=lead):
                    try:
                        await self.prepare(w, lead)
                        w["status"] = "running"
                        self.emit_ws(w)
                    except RunStopped:
                        return
                    except Exception as err:
                        if self._abort.is_set():
                            return
                        w["status"] = "failed"
                        w["error"] = str(err)
                        self.message(lead["id"], self.ceo["id"], "error", f"Non riesco a organizzare {w['id']}: {err}")
                        self.emit_ws(w)
                    finally:
                        self.preparing.discard(w["id"])
                        if not self._abort.is_set():
                            self.team.release(lead["id"])
                        self.tick()

                asyncio.ensure_future(prepare_one())
            for t in tasks:
                if len(self.active) >= self.cfg["limits"]["maxParallel"]:
                    break
                if t["status"] != "queued" or (self.ws_by_id(t["wsId"]) or {}).get("status") != "running":
                    continue
                if not all((self.task_by_id(d) or {}).get("status") == "done" for d in t["dependsOn"]):
                    continue
                spawn_limit = (self.cfg["teams"].get(t["team"]) or {}).get("maxSubAgents") or 0 if self.data["complexity"] == "complex" else 0
                agent = self.team.try_acquire(t["team"], self.data["id"], allow_lead=True, spawn_limit=spawn_limit)
                if not agent:
                    continue
                if agent["kind"] == "sub" and not agent.get("counted"):
                    agent["counted"] = True
                    self.data["usage"]["subAgents"] += 1
                    self.message((self.team.lead(t["team"]) or self.ceo)["id"], agent["id"], "spawn", f"Ti ho creato per {t['id']} · {t['title']}")
                self.active.add(t["id"])

                async def run_one(t=t, agent=agent):
                    try:
                        await self.run_task(t, agent)
                    except RunStopped:
                        return
                    except Exception as err:
                        if self._abort.is_set():
                            return
                        t["status"] = "failed"
                        t["error"] = str(err)
                        t["finishedAt"] = _iso_now()
                        self.note(t, agent, "error", str(err))
                        self.message(agent["id"], (self.team.lead(t["team"]) or self.ceo)["id"], "error", f"Non riesco a completare \"{t['title']}\": {err}")
                        self.emit_task(t)
                    finally:
                        self.active.discard(t["id"])
                        if not self._abort.is_set():
                            self.team.release(agent["id"])
                        self.tick()

                asyncio.ensure_future(run_one())

        if not self.active and not self.preparing and all(w["status"] in TERMINAL for w in ws_all):
            self._finish_schedule.set()

    # ---------- a lead organises one workstream ----------

    async def prepare(self, ws: dict, lead: dict) -> None:
        pacing = self.cfg["pacing"]
        complex_ = self.data["complexity"] == "complex"
        self.message(self.ceo["id"], lead["id"], "brief", f"{ws['id']} · {ws['title']}\n{ws['objective']}")
        self.team.set(lead["id"], {"state": "fetching", "wsId": ws["id"], "runId": self.data["id"], "text": ws["title"]})
        await self.sleep(pacing["fetchMs"])
        self.team.set(lead["id"], {"state": "thinking", "text": "Divido il lavoro del team…"})

        tasks = single_subtask(ws)
        if complex_:
            upstream = [f"{w['id']} {w['title']}: {w['summary'] or 'done'} (files: {', '.join(w['deliverables'])})" for w in (self.ws_by_id(d) for d in ws["dependsOn"])]
            raw = await self.chat_json(
                {"role": ws["team"], "messages": lead_plan_prompt(cfg=self.cfg, lead=lead, team=ws["team"], goal=self.data["goal"], ws=ws, upstream=upstream), "max_tokens": 4000, "agent": lead},
                lambda o: isinstance(o.get("subtasks"), list),
            )
            if raw:
                tasks = normalize_subtasks(raw, ws, self.cfg)

        await self.assign_skills(tasks, lead, complex_)
        if complex_:
            await self.refine_briefs(tasks, lead)

        self.data["tasks"].extend(tasks)
        self.ctx.bus.emit("subtasks", {"runId": self.data["id"], "wsId": ws["id"], "leadId": lead["id"], "tasks": tasks})
        listing = "\n".join(f"{t['id']} · {t['title']}{' (dopo ' + ', '.join(t['dependsOn']) + ')' if t['dependsOn'] else ''}" for t in tasks)
        self.message(lead["id"], self.ceo["id"], "split", f"{ws['id']} diviso in {len(tasks)} sotto-task:\n{listing}" if len(tasks) > 1 else f"{ws['id']}: lo affido al team così com'è.")
        self.team.set(lead["id"], {"state": "idle", "text": f"{len(tasks)} sotto-task pronti"})
        self.emit_run(True)

    async def assign_skills(self, tasks: list[dict], lead: dict, complex_: bool) -> None:
        lib = self.ctx.skills
        if not lib.skills:
            return
        per_task = (self.cfg.get("skills") or {}).get("perTask", 3)
        librarian = self.team.lead("skills") or (self.team.of_team("skills") or [None])[0]
        if librarian:
            self.team.set(librarian["id"], {"state": "tool", "tool": "search_skills", "toolTarget": f"{len(lib.skills)} skill", "text": f"Cerco le skill giuste per {len(tasks)} task", "runId": self.data["id"]})

        async def for_task(t):
            label = (self.cfg["teams"].get(t["team"]) or {}).get("label") or ""
            candidates = lib.search(f"{t['title']} {t['description']} {label} {t['team']} {' '.join(t['outputs'])}", 10)
            if not candidates:
                return
            picks = None
            if complex_ and librarian and len(candidates) > 1:
                obj = await self.chat_json(
                    {"role": "skills", "messages": librarian_prompt(librarian=librarian, goal=self.data["goal"], task=t, candidates=candidates, per_task=per_task), "max_tokens": 800, "agent": librarian, "task": t},
                    lambda o: isinstance(o.get("picks"), list),
                )
                if obj:
                    picks = [c for p in obj["picks"] for c in candidates if c["id"] == p.get("id") or c["name"] == p.get("id")]
            if picks is None:
                picks = [c for c in candidates if c.get("score", 0) >= max(1.2, candidates[0].get("score", 0) * 0.55)]
            seen = {}
            for p in picks:
                seen[p["id"]] = {"id": p["id"], "name": p["name"], "source": p["source"]}
            t["skills"] = list(seen.values())[:per_task]

        await asyncio.gather(*(for_task(t) for t in tasks))
        if librarian:
            lines = [f"{t['id']} → {', '.join(s['name'] for s in t['skills'])}" for t in tasks if t["skills"]]
            self.message(librarian["id"], lead["id"], "skills", "\n".join(lines) if lines else "Nessuna skill adatta: meglio niente che una sbagliata.")
            self.team.set(librarian["id"], {"state": "idle", "tool": None, "text": ""})

    async def refine_briefs(self, tasks: list[dict], lead: dict) -> None:
        pe = next((a for a in self.team.of_team("prompt") if not a["busy"]), None)
        if not pe:
            return
        pe["busy"] = True
        try:
            self.team.set(pe["id"], {"state": "thinking", "runId": self.data["id"], "text": f"Riscrivo {len(tasks)} brief"})

            async def for_task(t):
                obj = await self.chat_json(
                    {"role": "prompt", "messages": prompt_eng_prompt(pe=pe, goal=self.data["goal"], task=t, team=(self.cfg["teams"].get(t["team"]) or {}).get("label") or t["team"], skills=[s["name"] for s in t["skills"]]), "max_tokens": 1500, "agent": pe, "task": t},
                    lambda o: isinstance(o.get("brief"), str),
                )
                if not obj:
                    return
                t["brief"] = obj["brief"][:3000]
                t["acceptance"] = list(dict.fromkeys([*t["acceptance"], *strings(obj.get("acceptance"), 2)]))[:6]
                t["pitfalls"] = strings(obj.get("pitfalls"), 4)

            await asyncio.gather(*(for_task(t) for t in tasks))
            self.message(pe["id"], lead["id"], "prompt", f"Brief affinati per {', '.join(t['id'] for t in tasks)}")
        finally:
            pe["busy"] = False
            self.team.set(pe["id"], {"state": "idle", "runId": None, "text": ""})

    def inputs_for(self, task: dict) -> list[dict]:
        ws = self.ws_by_id(task["wsId"])
        done = [t for t in self.data["tasks"] if t["status"] == "done" and (t["id"] in task["dependsOn"] or t["wsId"] in (ws["dependsOn"] if ws else []))]
        return [{"id": t["id"], "title": t["title"], "agent": (self.team.get(t["agentId"]) or {}).get("name") or t["team"], "summary": t["summary"], "files": t["files"] if t["files"] else t["outputs"]} for t in done]

    async def skills_text(self, task: dict) -> str:
        parts = []
        budget = 9000
        for s in task.get("skills") or []:
            if budget <= 0:
                break
            try:
                out = await self.ctx.skills.read(s["id"], min(4000, budget))
                budget -= len(out["text"])
                parts.append(f"### {s['name']}\n{out['text']}")
            except Exception:
                pass  # a skill that disappeared is skipped
        return "\n\n".join(parts)

    # ---------- one subtask ----------

    async def run_task(self, task: dict, agent: dict) -> None:
        limits, pacing, router_cfg = self.cfg["limits"], self.cfg["pacing"], self.cfg["router"]
        lead = self.team.lead(task["team"])
        task["agentId"] = agent["id"]
        task["status"] = "assigned"
        task["startedAt"] = _iso_now()
        self.emit_task(task)
        self.team.set(agent["id"], {"state": "assigned", "taskId": task["id"], "wsId": task["wsId"], "runId": self.data["id"], "text": task["title"], "target": lead["id"] if lead and lead["id"] != agent["id"] else None})
        if lead and lead["id"] != agent["id"]:
            self.message(lead["id"], agent["id"], "assign", f"{task['id']} · {task['title']}\n{task['description']}")
        await self.sleep(pacing["pickupMs"])

        task["status"] = "working"
        self.emit_task(task)
        tasker = Tasker(self, task, agent)
        feedback = None
        rescued = False
        while True:
            task["attempts"] += 1
            out = await tasker.work(feedback)
            problems = [f"Hai esaurito i {limits['maxSteps']} passi disponibili senza chiamare finish. Concentrati sui file richiesti e consegna."] if out.get("stepLimit") else await self.machine_check(task)

            if not problems:
                task["summary"] = out["summary"]
                task["files"] = out["files"] if out.get("files") else task["outputs"]
                task["status"] = "review"
                self.emit_task(task)
                self.team.set(agent["id"], {"state": "waiting", "tool": None, "text": "In attesa di revisione"})
                verdict = await self.review(task, agent, out)
                if verdict["verdict"] == "pass":
                    task["status"] = "done"
                    task["finishedAt"] = _iso_now()
                    self.emit_task(task)
                    self.team.set(agent["id"], {"state": "delivering", "text": "Consegnato!"})
                    if lead and lead["id"] != agent["id"]:
                        self.message(agent["id"], lead["id"], "deliver", f"{task['id']} consegnato: {task['summary']}")
                    await self.sleep(pacing["deliverMs"])
                    return
                feedback = verdict["feedback"] or "Il revisore chiede di migliorare il lavoro rispetto ai criteri di accettazione."
            else:
                feedback = "\n".join(problems)
                self.note(task, agent, "check", feedback)

            task["revisions"] += 1
            if task["revisions"] >= limits["escalateAfter"] and not tasker.use and self.cfg["combos"].get(router_cfg["escalationCombo"]):
                tasker.use = router_cfg["escalationCombo"]
                task["escalated"] = True
                self.data["usage"]["escalations"] += 1
                self.note(task, agent, "escalate", f"Escalation al modello \"{router_cfg['escalationCombo']}\"")
                self.message((lead or self.ceo)["id"], agent["id"], "escalate", f"Dopo {task['revisions']} revisioni passo {task['id']} al modello più forte ({router_cfg['escalationCombo']}).")
            if task["revisions"] > limits["maxRevisions"]:
                if rescued:
                    raise Exception(f"Ancora non approvato dopo l'aiuto del lead. Ultimo feedback: {feedback[:300]}")
                decision = await self.rescue(task, agent, feedback)
                if decision["action"] == "skip":
                    raise Exception(f"Il lead ha deciso di saltarlo: {decision['guidance']}")
                rescued = True
                feedback = f"Indicazioni del lead: {decision['guidance']}\n\nUltimo feedback del revisore:\n{feedback}"
            task["status"] = "revise"
            self.emit_task(task)
            self.team.set(agent["id"], {"state": "thinking", "tool": None, "text": "Riprovo con un modello più forte…" if task["escalated"] else "Correggo seguendo il feedback…", "escalated": task["escalated"]})

    async def missing_outputs(self, task: dict) -> list[str]:
        missing = []
        for p in task["outputs"]:
            if await self.ws.size(p) <= 0:
                missing.append(p)
        return missing

    async def machine_check(self, task: dict) -> list[str]:
        missing = await self.missing_outputs(task)
        return [f"File mancanti o vuoti: {', '.join(missing)}"] if missing else []

    async def file_dump(self, task: dict) -> str:
        paths = list(dict.fromkeys(p for p in (safe_rel_path(x) for x in [*task["outputs"], *(task.get("files") or [])]) if p))
        budget = 26000
        parts = []
        for p in paths:
            if budget <= 0:
                break
            size = await self.ws.size(p)
            if size < 0:
                parts.append(f"=== {p} ===\n(missing)")
                continue
            if Path(p).suffix.lower() not in TEXT_EXT:
                parts.append(f"=== {p} ===\n(binary file, {size} bytes — generated media; judge it by the task description and prompt used)")
                continue
            text = await self.ws.read(p, min(9000, budget))
            budget -= len(text)
            parts.append(f"=== {p} ===\n{text}")
        return "\n\n".join(parts)

    async def review(self, task: dict, agent: dict, out: dict) -> dict:
        pacing = self.cfg["pacing"]
        has_qa = len(self.team.of_team("qa")) > 0
        if has_qa:
            # the QA team is shared: wait for a free reviewer, but let stop()
            # land instead of hanging on the queue
            acquire = asyncio.ensure_future(self.team.acquire("qa", self.data["id"], abort=self._abort))
            abort_watch = asyncio.ensure_future(self._abort.wait())
            await asyncio.wait({acquire, abort_watch}, return_when=asyncio.FIRST_COMPLETED)
            abort_watch.cancel()
            if self._abort.is_set():
                # The handoff may have landed before stop(): acquire is then
                # already done with a judge in hand, and raising without
                # releasing would leak the judge busy forever (P7 QA).
                acquire.cancel()
                try:
                    judge = await acquire
                except asyncio.CancelledError:
                    judge = None
                if judge is not None:
                    self.team.release(judge["id"])
                raise RunStopped("Stopped by the user")
            judge = acquire.result()
        else:
            judge = self.ceo
        security = task["team"] == "dev" or any(__import__("re").search(r"\.(js|mjs|ts|tsx|jsx|py|html?|php|sh|sql)$", p, __import__("re").IGNORECASE) for p in task["outputs"])
        try:
            self.team.set(judge["id"], {"state": "reviewing", "target": agent["id"], "taskId": task["id"], "runId": self.data["id"], "text": f"{'Qualità e sicurezza' if security else 'Controllo'}: \"{task['title']}\"", "verdict": None})
            self.message(agent["id"], judge["id"], "review", f"Pronto per la revisione: {task['title']}")
            await self.sleep(pacing["reviewWalkMs"])
            raw = await self.chat_json(
                {"role": "qa", "messages": judge_prompt(judge=judge, goal=self.data["goal"], task=task, attempt=task["attempts"], summary=out["summary"], file_dump=await self.file_dump(task), checks="", security=security), "max_tokens": 2000, "agent": judge, "task": task},
                lambda o: o.get("verdict") in ("pass", "revise"),
            )
            raw = raw or {"verdict": "pass", "score": None, "feedback": ""}
            fb = raw.get("feedback")
            feedback = fb if isinstance(fb, str) else "\n".join(fb) if isinstance(fb, list) else ""
            v = {"verdict": raw["verdict"], "score": raw.get("score"), "feedback": feedback, "judgeId": judge["id"], "attempt": task["attempts"], "security": security, "ts": _now_ms()}
            task["verdicts"].append(v)
            lesson = raw.get("lesson")
            if isinstance(lesson, str) and lesson.strip():
                self.ctx.brain.add(title=f"Lezione · {task['title']}", text=lesson.strip(), team=task["team"], agent_id=judge["id"], run_id=self.data["id"], kind="lesson", tags=[task["team"], "qa"])
            self.note(task, judge, "verdict", f"Approvato ({v['score'] if v['score'] is not None else '–'}/10)" if v["verdict"] == "pass" else feedback)
            self.team.set(judge["id"], {"state": "verdict", "verdict": v["verdict"], "target": agent["id"], "text": f"Approvato! {v['score'] or ''}/10" if v["verdict"] == "pass" else "Da rivedere"})
            self.message(judge["id"], agent["id"], "pass" if v["verdict"] == "pass" else "revise", f"Approvato ({v['score'] if v['score'] is not None else '–'}/10)" if v["verdict"] == "pass" else feedback)
            await self.sleep(pacing["verdictMs"])
            return v
        finally:
            if has_qa:
                self.team.release(judge["id"])
            else:
                self.team.set(judge["id"], {"state": "idle", "target": None})

    def progress_text(self, team: str | None = None) -> str:
        lines = [f"- {t['id']} [{t['status']}] {t['title']}{': ' + t['summary'][:200] if t['summary'] else ''}" for t in self.data["tasks"] if not team or t["team"] == team]
        return "\n".join(lines) or "- (nothing yet)"

    async def advise(self, task: dict, agent: dict, question: str) -> str:
        lead = self.team.lead(task["team"]) or self.ceo
        responder = self.ceo if lead["id"] == agent["id"] else lead
        self.message(agent["id"], responder["id"], "question", question)
        res = await self.chat(
            role="ceo" if responder["kind"] == "ceo" else task["team"],
            messages=advisor_prompt(lead=responder, team=(self.cfg["teams"].get(task["team"]) or {}).get("label") or task["team"], goal=self.data["goal"], ws=self.ws_by_id(task["wsId"]), task=task, from_=agent["name"], question=question, progress=self.progress_text(task["team"])),
            max_tokens=800,
            agent=responder,
            task=task,
        )
        answer = res["text"].strip()[:1500]
        self.message(responder["id"], agent["id"], "answer", answer)
        return f"{responder['name']} answers: {answer}"

    async def ask_user(self, task: dict, agent: dict, question: str) -> str:
        item = self.add_waiting({"kind": "question", "from": agent["id"], "taskId": task["id"], "text": question})
        self.team.set(agent["id"], {"state": "asking", "text": question})
        self.message(agent["id"], "user", "ask_user", question)
        answer = await self.wait_answer(item, self.cfg["limits"]["askUserTimeoutMs"])
        if self._abort.is_set():
            raise RunStopped("Stopped by the user")
        self.team.set(agent["id"], {"state": "thinking", "text": "Ho la risposta, continuo" if answer else "Nessuna risposta, decido io"})
        if answer and answer.get("text"):
            return f"The owner answers: {answer['text']}"
        return "No answer from the owner in time: make the most reasonable decision yourself and state it in your summary."

    async def rescue(self, task: dict, agent: dict, feedback: str) -> dict:
        lead = self.team.lead(task["team"]) or self.ceo
        self.message(agent["id"], lead["id"], "stuck", f"Bloccato su \"{task['title']}\" dopo {task['revisions']} revisioni.")
        d = await self.chat_json(
            {"role": "ceo" if lead["kind"] == "ceo" else task["team"], "messages": rescue_prompt(lead=lead, goal=self.data["goal"], task=task, feedback=feedback), "max_tokens": 1000, "agent": lead, "task": task},
            lambda o: o.get("action") in ("retry", "skip"),
        )
        d = d or {"action": "retry", "guidance": "Riparti dai criteri di accettazione uno per uno."}
        self.message(lead["id"], agent["id"], "guidance", f"{'Saltiamo questo task' if d['action'] == 'skip' else 'Riprova'}: {d['guidance']}")
        return {"action": d["action"], "guidance": str(d.get("guidance") or "")}

    async def write_media(self, task: dict, agent: dict, kind: str, args: dict) -> str:
        is_image = kind == "image"
        fallback = f"assets/{slugify(args.get('prompt') or task['title'], 30)}.png" if is_image else f"audio/{slugify(task['title'], 30)}.mp3"
        path = safe_rel_path(args.get("path")) or fallback
        ext = Path(path).suffix[1:].lower()
        out = await (self.ctx.media.image({"prompt": str(args.get("prompt") or ""), "size": str(args.get("size") or "1024x1024"), "ext": ext}) if is_image else self.ctx.media.speech({"text": str(args.get("text") or ""), "voice": args.get("voice")}))
        if is_image and ext == "svg" and out["ext"] != "svg":
            import re

            path = re.sub(r"\.svg$", ".png", path, flags=re.IGNORECASE)
        r = await self.ws.write_bytes(path, out["bytes"])
        self.ctx.bus.emit("file", {"runId": self.data["id"], "agentId": agent["id"], "taskId": task["id"], "path": r["path"], "bytes": r["bytes"], "media": kind})
        renamed = f" (saved as {r['path']})" if r["path"] != args.get("path") and args.get("path") else ""
        return f"Generated {r['path']} with {out['target']}{' (demo generator)' if out.get('demo') else ''}, {r['bytes']} bytes{renamed}."

    async def exec_tool(self, task: dict, agent: dict, action: dict) -> str:
        tool, args = action["tool"], action["args"]
        skills, brain = self.ctx.skills, self.ctx.brain
        try:
            if tool == "list_files":
                return await self.ws.list_text(args.get("path") or ".") or "(empty folder)"
            if tool == "read_file":
                return await self.ws.read(args.get("path"))
            if tool == "write_file":
                if not isinstance(args.get("content"), str):
                    return 'ERROR: "content" must be a string with the whole file.'
                r = await self.ws.write(args.get("path"), args["content"])
                self.ctx.bus.emit("file", {"runId": self.data["id"], "agentId": agent["id"], "taskId": task["id"], "path": r["path"], "bytes": r["bytes"]})
                return f"Wrote {r['path']} ({r['bytes']} bytes)."
            if tool == "web_search":
                return await web_search(args.get("query"))
            if tool == "web_fetch":
                return await web_fetch(str(args.get("url") or ""))
            if tool == "run_command":
                if not self.cfg["limits"].get("allowShell"):
                    return "ERROR: shell commands are disabled on this machine. Verify by reading files instead."
                r = await run_command(str(args.get("cmd") or ""), self.ws.root, self.cfg["limits"]["commandTimeoutMs"], self._abort)
                return f"exit code {r['code']}\n{r['output']}"
            if tool == "generate_image":
                return await self.write_media(task, agent, "image", args)
            if tool == "generate_speech":
                return await self.write_media(task, agent, "speech", args)
            if tool == "search_skills":
                hits = skills.search(str(args.get("query") or task["title"]), 8)
                return "\n".join(f"- {h['name']} ({h['source']}): {h['description'][:200]}" for h in hits) if hits else "No skill matches that query."
            if tool == "read_skill":
                return (await skills.read(str(args.get("name") or args.get("id") or "")))["text"]
            if tool == "remember":
                n = brain.add(title=args.get("title"), text=args.get("text"), tags=args.get("tags"), team=task["team"], agent_id=agent["id"], run_id=self.data["id"])
                return f"Saved in the Brain as \"{n['title']}\"."
            if tool == "recall":
                hits = brain.search(str(args.get("query") or ""), 5, agent_id=agent["id"])
                return "\n".join(f"- {n['title']}: {n['text'][:400]}" for n in hits) if hits else "The Brain has nothing on that yet."
            if tool == "ask_lead":
                return await self.advise(task, agent, str(args.get("question") or ""))
            if tool == "ask_user":
                return await self.ask_user(task, agent, str(args.get("question") or ""))
            return f"ERROR: unknown tool {tool}"
        except RunStopped:
            raise
        except Exception as err:
            return f"ERROR: {err}"

    # ---------- wrap-up ----------

    async def synthesize(self) -> None:
        ceo = self.ceo
        self.team.set(ceo["id"], {"state": "thinking", "runId": self.data["id"], "text": "Scrivo il report finale…"})
        files = await self.ws.list_text()
        res = await self.chat(
            role="ceo",
            messages=synth_prompt(ceo=ceo, goal=self.data["goal"], plan_summary=self.data["planSummary"], workstreams=self.data["workstreams"], tasks=self.data["tasks"], files=files or "(none)"),
            max_tokens=3000,
            agent=ceo,
        )
        self.data["report"] = clip(res["text"].strip(), 20000)
        await self.ws.write("REPORT.md", self.data["report"])
        self.ctx.brain.add(
            title=f"Missione · {self.data['goal'][:90]}",
            text=f"{self.data['planSummary']}\n" + "\n".join(f"{w['id']} {w['title']} ({w['team']}): {w['status']}" for w in self.data["workstreams"]),
            kind="run",
            tags=["missione", *dict.fromkeys(w["team"] for w in self.data["workstreams"])],
            agent_id=ceo["id"],
            run_id=self.data["id"],
        )
        self.message(ceo["id"], "*", "report", "Report finale pronto: REPORT.md")
