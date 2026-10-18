"""Mirrors server/store.js: one run per file in data/runs/, debounced save."""

import asyncio
import json
from pathlib import Path

NON_TERMINAL_RESET = {"completed", "completed_with_failures", "failed", "stopped"}


class Store:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "runs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.runs: dict[str, dict] = {}
        self._timers: dict[str, asyncio.TimerHandle] = {}
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

    def save(self, run: dict, immediate: bool = False) -> None:
        self.runs[run["id"]] = run
        timer = self._timers.pop(run["id"], None)
        if timer is not None:
            timer.cancel()

        def write():
            self._timers.pop(run["id"], None)
            (self.dir / f"{run['id']}.json").write_text(json.dumps(run, indent=1), encoding="utf-8")

        if immediate:
            write()
        else:
            loop = asyncio.get_event_loop()
            self._timers[run["id"]] = loop.call_later(0.4, write)

    def has(self, id: str) -> bool:
        return id in self.runs or (self.dir / f"{id}.json").exists()
