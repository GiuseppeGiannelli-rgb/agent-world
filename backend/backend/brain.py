"""Mirrors server/engine/brain.js: shared memory that outlives runs."""

import json
import time
import uuid
from pathlib import Path

from backend.search import bm25  # P6: native Rust when built+probed, Python otherwise


class Brain:
    def __init__(self, file: Path, bus=None):
        self.file = Path(file)
        self.bus = bus
        self.notes: list[dict] = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else []
        self.reindex()

    def reindex(self) -> None:
        self.index = bm25()
        for n in self.notes:
            self.index.add(
                n["id"],
                [
                    {"text": n["title"], "weight": 3},
                    {"text": n["text"]},
                    {"text": " ".join(n.get("tags") or []), "weight": 2},
                    {"text": n.get("team") or "", "weight": 1},
                ],
            )

    def save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(self.notes, indent=1), encoding="utf-8")

    def add(self, *, title=None, text=None, tags=None, team=None, agent_id=None, run_id=None, kind="note") -> dict:
        if isinstance(tags, list):
            tag_list = tags
        elif tags:
            tag_list = str(tags).split(",")
        else:
            tag_list = []
        note = {
            "id": uuid.uuid4().hex[:8],
            "ts": int(time.time() * 1000),
            "kind": kind,
            "title": (str(title or "")[:160] or "Nota"),
            "text": str(text or "")[:4000],
            "tags": [str(t).strip() for t in tag_list if str(t).strip()][:8],
            "team": team,
            "agentId": agent_id,
            "runId": run_id,
        }
        self.notes.append(note)
        if len(self.notes) > 5000:
            self.notes = self.notes[len(self.notes) - 5000 :]
        self.reindex()
        self.save()
        if self.bus is not None:
            self.bus.emit("brain", {"op": "remember", "agentId": agent_id, "count": len(self.notes), "note": note})
        return note

    def search(self, query: str, k: int = 5, *, agent_id=None, quiet: bool = False) -> list[dict]:
        by_id = {n["id"]: n for n in self.notes}
        hits = [by_id[h["id"]] for h in self.index.search(query, k) if h["id"] in by_id]
        if not quiet and self.bus is not None:
            self.bus.emit("brain", {"op": "recall", "agentId": agent_id, "count": len(self.notes), "hits": len(hits)})
        return hits

    def list(self, limit: int = 200) -> list[dict]:
        return list(reversed(self.notes[-limit:]))

    @property
    def count(self) -> int:
        return len(self.notes)
