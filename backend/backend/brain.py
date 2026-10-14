"""Mirrors server/engine/brain.js: shared memory that outlives runs.

Spec 05: notes are searched with BM25 fused with vector similarity
(search.HybridIndex). add() feeds BM25 incrementally (the old full rebuild on
every note cost ~0.4-0.7 s at the 5000-note cap); vectors are computed lazily,
in one batch, by the next search()."""

import asyncio
import json
import time
import uuid
from pathlib import Path

from backend.embed import Embedder
from backend.search import HybridIndex

MAX_NOTES = 5000


def _fields(n: dict) -> list[dict]:
    return [
        {"text": n["title"], "weight": 3},
        {"text": n["text"]},
        {"text": " ".join(n.get("tags") or []), "weight": 2},
        {"text": n.get("team") or "", "weight": 1},
    ]


def _embed_text(n: dict) -> str:
    return f"{n['title']}\n{n['text']}\n{' '.join(n.get('tags') or [])}"


class Brain:
    def __init__(self, file: Path, bus=None, embedder: Embedder | None = None):
        self.file = Path(file)
        self.bus = bus
        self.embedder = embedder or Embedder(None)
        self.notes: list[dict] = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else []
        self._vector_lock = asyncio.Lock()
        self.reindex()

    def _new_index(self) -> HybridIndex:
        rag = self.embedder.rag
        fusion = rag.get("fusion") or {}
        return HybridIndex(
            rrf_k=int(fusion.get("k", 60)),
            weights={"bm25": float(fusion.get("bm25", 1.0)), "vector": float(fusion.get("vector", 1.0))},
            min_cosine=float(rag.get("minCosine", 0.2)),
        )

    def reindex(self) -> None:
        self.index = self._new_index()
        for n in self.notes:
            self.index.add(n["id"], _fields(n))

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
        if len(self.notes) > MAX_NOTES:
            # the oldest notes leave: only then the index is rebuilt
            self.notes = self.notes[len(self.notes) - MAX_NOTES :]
            self.reindex()
        else:
            self.index.add(note["id"], _fields(note))
        self.save()
        if self.bus is not None:
            self.bus.emit("brain", {"op": "remember", "agentId": agent_id, "count": len(self.notes), "note": note})
        return note

    async def ensure_vectors(self) -> None:
        """Embeds, in one batch, every note that has no vector yet. If the model
        of the index stops answering (a key removed), all vectors are rebuilt
        with the first model that works."""
        async with self._vector_lock:
            missing = [n for n in self.notes if n["id"] not in self.index.has_vectors]
            if not missing:
                return
            try:
                model, vectors = await self.embedder.embed([_embed_text(n) for n in missing], model=self.index.model)
            except Exception:  # noqa: BLE001 -- the index model is gone: start the vectors over
                self.reindex()
                missing = list(self.notes)
                model, vectors = await self.embedder.embed([_embed_text(n) for n in missing])
            for n, vec in zip(missing, vectors):
                self.index.add_vectors(n["id"], [vec], model)

    async def search(self, query: str, k: int = 5, *, agent_id=None, quiet: bool = False) -> list[dict]:
        await self.ensure_vectors()
        query_vec = None
        if self.index.model is not None:
            try:
                _, (query_vec,) = await self.embedder.embed([query], model=self.index.model)
            except Exception:  # noqa: BLE001 -- no query vector: BM25 alone
                query_vec = None
        by_id = {n["id"]: n for n in self.notes}
        hits = [by_id[h["id"]] for h in self.index.search(query, k, query_vec) if h["id"] in by_id]
        if not quiet and self.bus is not None:
            self.bus.emit("brain", {"op": "recall", "agentId": agent_id, "count": len(self.notes), "hits": len(hits)})
        return hits

    def list(self, limit: int = 200) -> list[dict]:
        return list(reversed(self.notes[-limit:]))

    @property
    def count(self) -> int:
        return len(self.notes)
