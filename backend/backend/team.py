"""Mirrors server/engine/team.js: who exists, who is free, and what each
one is doing right now.

Node's `acquire()` takes an AbortSignal to cancel a pending wait; Python's
native task cancellation does the same job more idiomatically, so a caller
aborts a pending acquire() by cancelling its task instead."""

from __future__ import annotations

import asyncio
import time


def _now_ms() -> int:
    return int(time.time() * 1000)


class Team:
    def __init__(self, bus=None):
        self.bus = bus
        self.agents: dict[str, dict] = {}
        self.waiters: list[dict] = []
        self.sub_seq: dict[str, int] = {}

    def load(self, staff: list[dict]) -> None:
        ids = {s["id"] for s in staff}
        for id_ in [id_ for id_, a in self.agents.items() if id_ not in ids and not a["busy"] and a["kind"] != "sub"]:
            del self.agents[id_]
        for s in staff:
            a = self.agents.get(s["id"])
            if a:
                a.update({"name": s["name"], "team": s["team"], "kind": s["kind"]})
            else:
                self.agents[s["id"]] = self._fresh(s)

    def _fresh(self, s: dict) -> dict:
        return {
            "id": s["id"], "name": s["name"], "team": s["team"], "kind": s["kind"], "slot": s.get("slot"),
            "busy": False, "state": "idle", "runId": None, "taskId": None, "wsId": None, "target": None,
            "text": "", "tool": None, "toolTarget": None, "model": None, "verdict": None, "since": _now_ms(),
        }

    def get(self, id: str) -> dict | None:
        return self.agents.get(id)

    def list(self) -> list[dict]:
        return list(self.agents.values())

    def of_team(self, team: str) -> list[dict]:
        return [a for a in self.list() if a["team"] == team]

    def ceo(self) -> dict | None:
        return next((a for a in self.list() if a["kind"] == "ceo"), None)

    def lead(self, team: str) -> dict | None:
        return next((a for a in self.list() if a["team"] == team and a["kind"] == "lead"), None)

    def set(self, id: str, patch: dict) -> None:
        a = self.agents.get(id)
        if not a:
            return
        a.update(patch)
        a["since"] = _now_ms()
        if self.bus is not None:
            self.bus.emit("agent", dict(a))

    def take(self, a: dict, run_id) -> dict:
        a["busy"] = True
        a["runId"] = run_id
        return a

    def try_acquire(self, team: str, run_id, *, allow_lead: bool = True, spawn_limit: int = 0) -> dict | None:
        # Deviation from Node's team.js (tryAcquire): Node takes a free worker
        # first and spawns a sub only when nobody is free. Here a positive
        # spawn_limit means sub-agents take the parallel work FIRST, so the
        # named staff stays available for coordination; staff is the fallback
        # once the spawn limit is reached. Contract fixed by test_team.py.
        members = self.of_team(team)
        subs = [a for a in members if a["kind"] == "sub"]
        if len(subs) < spawn_limit:
            return self.take(self.spawn(team, run_id, subs), run_id)
        worker = next((a for a in members if not a["busy"] and a["kind"] in ("worker", "sub")), None)
        if worker:
            return self.take(worker, run_id)
        if allow_lead:
            lead = next((a for a in members if not a["busy"] and a["kind"] == "lead"), None)
            if lead:
                return self.take(lead, run_id)
        return None

    def try_acquire_lead(self, team: str, run_id) -> dict | None:
        lead = self.lead(team)
        if lead and not lead["busy"]:
            return self.take(lead, run_id)
        return None

    def spawn(self, team: str, run_id, existing: list[dict]) -> dict:
        used = {s.get("slot") for s in existing}
        slot = 0
        while slot in used:
            slot += 1
        n = self.sub_seq.get(team, 0) + 1
        self.sub_seq[team] = n
        a = self._fresh({"id": f"{team}-sub{n}", "name": f"Sub {slot + 1}", "team": team, "kind": "sub", "slot": slot})
        a["runId"] = run_id
        self.agents[a["id"]] = a
        if self.bus is not None:
            self.bus.emit("agent.spawn", dict(a))
        return a

    def despawn(self, id: str) -> None:
        a = self.agents.get(id)
        if not a or a["kind"] != "sub":
            return
        del self.agents[id]
        if self.bus is not None:
            self.bus.emit("agent.despawn", {"id": id, "team": a["team"]})

    async def acquire(self, team: str, run_id, abort: "asyncio.Event | None" = None):
        """Waits for a free member of a service team. Cancel the returned
        task to abort a pending wait (see the module docstring). `abort` is
        the run's abort event: once set, the waiter must never receive an
        agent (release() checks it synchronously)."""
        a = self.try_acquire(team, run_id, allow_lead=True)
        if a:
            return a
        future = asyncio.get_event_loop().create_future()
        waiter = {"team": team, "runId": run_id, "future": future, "abort": abort}
        self.waiters.append(waiter)
        try:
            return await future
        except asyncio.CancelledError:
            if waiter in self.waiters:
                self.waiters.remove(waiter)
            raise

    @staticmethod
    def _waiter_alive(w: dict) -> bool:
        # A waiter is handoff-able only while its future is pending AND its
        # run is not aborted. Node removes aborted waiters synchronously in
        # the abort listener; asyncio delivers cancellation a loop turn later,
        # and a handoff to a dead run leaves the agent busy forever (P7 QA:
        # both QA judges stuck idle+busy after stop()).
        if w["future"].done():
            return False
        abort = w.get("abort")
        return abort is None or not abort.is_set()

    def abort_waiters(self, run_id) -> None:
        """Synchronously cancel every pending acquire of a run (Run.stop()).
        Mirrors Node, where the abort listener removes waiters during the
        abort dispatch itself. asyncio delivers cancellation a loop turn
        later; without this a release() in between could hand an agent to a
        waiter of the stopping run and leave it busy forever (P7 QA)."""
        for w in [w for w in self.waiters if w["runId"] == run_id]:
            self.waiters.remove(w)
            if not w["future"].done():
                w["future"].cancel()

    def release(self, id: str, patch: dict | None = None) -> None:
        patch = patch or {}
        a = self.agents.get(id)
        if not a:
            return
        a["busy"] = False
        # Hand the agent only to a waiter that is still alive (pending future
        # AND run not aborted) -- see _waiter_alive.
        i = next((i for i, w in enumerate(self.waiters) if w["team"] == a["team"] and self._waiter_alive(w)), -1)
        if i >= 0:
            w = self.waiters.pop(i)
            self.take(a, w["runId"])
            self.set(id, {"state": "idle", "taskId": None, "wsId": None, "target": None, "tool": None, "text": ""})
            if not w["future"].done():
                w["future"].set_result(a)
            return
        if a["kind"] == "sub":
            self.set(id, {"state": "idle", "taskId": None, "target": None, "tool": None, "text": ""})
            self.despawn(id)
            return
        self.set(id, {"state": "idle", "runId": None, "taskId": None, "wsId": None, "target": None, "tool": None, "text": "", "verdict": None, **patch})
