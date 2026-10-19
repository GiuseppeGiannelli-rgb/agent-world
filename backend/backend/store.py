"""Mirrors server/store.js: one run per file in data/runs/, debounced save.

Spec 11 T04: the workers' checkpoints live next to the runs, one file per run in
data/runs/sessions/, written as often as a valid step (debounced the same way).
Every write goes to a temporary file first and then replaces the old one, so a
write cut halfway leaves the last good file instead of a broken one."""

import asyncio
import json
import os
from pathlib import Path

NON_TERMINAL_RESET = {"completed", "completed_with_failures", "failed", "stopped"}


def write_atomic(path: Path, text: str) -> None:
    """The whole text or the old file, never half of it."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        os.replace(tmp, path)
    except OSError:
        # Windows refuses to replace a file another process holds open (an
        # antivirus, an indexer): write it in place, as before T04
        path.write_text(text, encoding="utf-8")
        tmp.unlink(missing_ok=True)


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "runs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, dict] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
        self._writes: dict[str, object] = {}  # the newest pending write of each key
        for f in self.dir.rglob("*.tmp"):
            f.unlink(missing_ok=True)  # a write the server did not finish: the file it was replacing is intact
        for f in sorted(self.dir.glob("*.json")):
            try:
                run = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if run.get("status") not in NON_TERMINAL_RESET:
                run["status"] = "stopped"
                run.setdefault("error", "Interrupted: the server stopped while this run was active.")
                # spec 09: what was in flight is interrupted, not given up: a resume runs it again
                for item in (*(run.get("tasks") or []), *(run.get("workstreams") or [])):
                    if item.get("status") not in ("done", "failed", "skipped"):
                        item["status"] = "skipped"
                        item["stopped"] = True
            for w in run.get("waiting") or []:
                if w.get("status") == "open":
                    # spec 09: a question waits for the owner across sessions, the rest expires
                    w["status"] = "pending" if w.get("kind") == "question" else "expired"
            self.runs[run["id"]] = run

    def get(self, id: str) -> dict | None:
        return self.runs.get(id)

    def list(self) -> list[dict]:
        return sorted(self.runs.values(), key=lambda r: r["createdAt"], reverse=True)

    def _later(self, key: str, write, immediate: bool) -> None:
        """At most one write per key every 0.4 s, with the newest state: a newer
        call replaces the pending write but keeps its time (spec 11 T04: a delay
        that started again at every call never wrote while the workers kept
        stepping); an immediate one writes now and cancels the pending one."""
        self._writes[key] = write
        if immediate:
            timer = self._timers.pop(key, None)
            if timer is not None:
                timer.cancel()
            self._writes.pop(key)()
            return
        if key in self._timers:
            return

        def fire():
            self._timers.pop(key, None)
            pending = self._writes.pop(key, None)
            if pending is not None:
                pending()

        self._timers[key] = asyncio.get_event_loop().call_later(0.4, fire)

    def save(self, run: dict, immediate: bool = False) -> None:
        id = run["id"]
        self.runs[id] = run
        self._later(id, lambda: write_atomic(self.dir / f"{id}.json", json.dumps(self.runs[id], indent=1)), immediate)

    def has(self, id: str) -> bool:
        return id in self.runs or (self.dir / f"{id}.json").exists()

    # ---------- spec 11 T04: the workers' checkpoints ----------

    def sessions_path(self, run_id: str) -> Path:
        return self.dir / "sessions" / f"{run_id}.json"

    def save_sessions(self, run_id: str, sessions, immediate: bool = False) -> None:
        """The conversations of a run's unfinished workers (task id -> session):
        the dict, or a function that builds it when the write happens, so a
        debounced write costs one build for many steps. None left removes the file."""
        f = self.sessions_path(run_id)

        def write():
            data = sessions() if callable(sessions) else sessions
            if not data:
                f.unlink(missing_ok=True)
                return
            f.parent.mkdir(parents=True, exist_ok=True)
            write_atomic(f, json.dumps(data, ensure_ascii=False))

        self._later(f"sessions:{run_id}", write, immediate)

    def load_sessions(self, run_id: str) -> dict:
        try:
            data = json.loads(self.sessions_path(run_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}  # none, or unreadable: those workers start afresh, nothing else is lost
        return data if isinstance(data, dict) else {}
