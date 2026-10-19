"""Mirrors server/engine/brain.js: shared memory that outlives runs.

Spec 05: notes are searched with BM25 fused with vector similarity
(search.HybridIndex). add() feeds BM25 incrementally (the old full rebuild on
every note cost ~0.4-0.7 s at the 5000-note cap); vectors are computed lazily,
in one batch, by the next search().

Spec 11 T03: the agents' own notes (QA lessons, notes, mission summaries) age.
search() multiplies their fused score by a time decay (D15), and consolidate()
merges the near-duplicates of a run into the newest one (D14). What the owner
wrote or gave (kind "user", "document") neither ages nor merges. Settings in
config rag.brain, read at every call."""

import asyncio
import json
import time
import uuid
from pathlib import Path

from backend.embed import Embedder, dot
from backend.search import HybridIndex

MAX_NOTES = 5000
DAY_MS = 86_400_000
# D14-D15: only the agents' notes age and merge
AGENT_KINDS = {"lesson", "note", "run"}
DEFAULTS = {"dedupeCosine": 0.88, "halfLifeDays": 30, "decayFloor": 0.5}


def _fields(n: dict) -> list[dict]:
    return [
        {"text": n["title"], "weight": 3},
        {"text": n["text"]},
        {"text": " ".join(n.get("tags") or []), "weight": 2},
        {"text": n.get("team") or "", "weight": 1},
    ]


def _embed_text(n: dict) -> str:
    return f"{n['title']}\n{n['text']}\n{' '.join(n.get('tags') or [])}"


def _kind(n: dict) -> str:
    return n.get("kind") or "note"  # a note saved before "kind" existed is an agent note


class Brain:
    def __init__(self, file: Path, bus=None, embedder: Embedder | None = None):
        self.file = Path(file)
        self.bus = bus
        self.embedder = embedder or Embedder(None)
        self.clock = time.time  # seconds; the tests set a fixed one
        self.notes: list[dict] = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else []
        self._vector_lock = asyncio.Lock()
        self.reindex()

    def settings(self) -> dict:
        return {**DEFAULTS, **((self.embedder.rag or {}).get("brain") or {})}

    def _new_index(self) -> HybridIndex:
        rag = self.embedder.rag
        fusion = rag.get("fusion") or {}
        return HybridIndex(
            rrf_k=int(fusion.get("k", 60)),
            weights={"bm25": float(fusion.get("bm25", 1.0)), "vector": float(fusion.get("vector", 1.0))},
            min_cosine=float(rag.get("minCosine", 0.2)),
        )

    def reindex(self, keep_vectors: set | None = None) -> None:
        """BM25 from scratch; keep_vectors: the ids whose vectors move to the new
        index (spec 11 T03: a consolidation re-embeds only what it changed)."""
        old = getattr(self, "index", None)
        self.index = self._new_index()
        for n in self.notes:
            self.index.add(n["id"], _fields(n))
        if keep_vectors and old is not None and old.model is not None:
            for doc, vec in zip(old.chunk_doc, old.chunk_vec):
                if doc in keep_vectors:
                    self.index.add_vectors(doc, [vec], old.model)

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

    def decay(self, note: dict, now: float) -> float:
        """D15: floor + (1 - floor) * 0.5 ** (age / half life), for the agents'
        notes; 1 for the owner's, and when halfLifeDays is 0 (decay off)."""
        s = self.settings()
        half = float(s.get("halfLifeDays") or 0)
        if half <= 0 or _kind(note) not in AGENT_KINDS:
            return 1.0
        floor = min(max(float(s.get("decayFloor") or 0), 0.0), 1.0)
        age_days = max(0.0, (now * 1000 - float(note.get("ts") or now * 1000)) / DAY_MS)
        return floor + (1 - floor) * 0.5 ** (age_days / half)

    async def search(self, query: str, k: int = 5, *, agent_id=None, quiet: bool = False) -> list[dict]:
        await self.ensure_vectors()
        query_vec = None
        if self.index.model is not None:
            try:
                _, (query_vec,) = await self.embedder.embed([query], model=self.index.model)
            except Exception:  # noqa: BLE001 -- no query vector: BM25 alone
                query_vec = None
        by_id = {n["id"]: n for n in self.notes}
        now = self.clock()
        boost = lambda d: self.decay(by_id[d], now) if d in by_id else 1.0  # noqa: E731
        hits = [by_id[h["id"]] for h in self.index.search(query, k, query_vec, boost=boost) if h["id"] in by_id]
        if not quiet and self.bus is not None:
            self.bus.emit("brain", {"op": "recall", "agentId": agent_id, "count": len(self.notes), "hits": len(hits)})
        return hits

    async def consolidate(self, *, run_id=None, threshold: float | None = None) -> int:
        """D14: merges near-duplicate agent notes (cosine > dedupeCosine, same
        kind) into the newest of each pair: its tags take the older ones', and
        "repeats" counts what it absorbed. With run_id only that run's notes are
        compared with the others (measured: 30 new notes against 5000 take 1.3 s,
        a full pass of 5000 about 107 s); without, every note. Returns how many
        notes left; the index keeps the vectors of the notes it did not touch."""
        thr = float(self.settings()["dedupeCosine"] if threshold is None else threshold)
        await self.ensure_vectors()
        vectors = dict(zip(self.index.chunk_doc, self.index.chunk_vec))  # one vector per note
        pool = [n for n in self.notes if _kind(n) in AGENT_KINDS and n["id"] in vectors]
        new = [n for n in pool if run_id is None or n.get("runId") == run_id]
        if not new:
            return 0
        # the dot products in a thread (they are the cost); the notes change here, on the loop
        gone, updates = await asyncio.to_thread(self._merge, new, pool, vectors, thr)
        if not gone:
            return 0
        for n in self.notes:
            if n["id"] in updates:
                n["tags"], n["repeats"] = updates[n["id"]]
        self.notes = [n for n in self.notes if n["id"] not in gone]
        self.reindex(keep_vectors={n["id"] for n in self.notes} - set(updates))
        self.save()
        if self.bus is not None:
            self.bus.emit("brain", {"op": "consolidate", "agentId": None, "count": len(self.notes), "removed": len(gone), "runId": run_id})
        return len(gone)

    @staticmethod
    def _merge(new: list[dict], pool: list[dict], vectors: dict, thr: float) -> tuple[set, dict]:
        """Reads the notes, writes nothing: returns the ids that leave and, for
        each survivor, its (tags, repeats)."""
        gone: set = set()
        tags = {n["id"]: list(n.get("tags") or []) for n in pool}
        repeats = {n["id"]: int(n.get("repeats") or 0) for n in pool}
        updates: dict = {}
        order = {n["id"]: i for i, n in enumerate(pool)}
        age = lambda x: (x.get("ts") or 0, order[x["id"]])  # noqa: E731 -- newer is greater
        for n in sorted(new, key=age):  # oldest first
            if n["id"] in gone:
                continue
            for m in pool:
                if m["id"] == n["id"] or m["id"] in gone or _kind(m) != _kind(n):
                    continue
                if dot(vectors[n["id"]], vectors[m["id"]]) <= thr:  # strictly above the threshold
                    continue
                keep, drop = (n["id"], m["id"]) if age(n) >= age(m) else (m["id"], n["id"])
                tags[keep] = list(dict.fromkeys([*tags[keep], *tags[drop]]))[:8]
                repeats[keep] += 1 + repeats[drop]
                updates[keep] = (tags[keep], repeats[keep])
                updates.pop(drop, None)
                gone.add(drop)
                if drop == n["id"]:
                    break
        return gone, updates

    def list(self, limit: int = 200) -> list[dict]:
        return list(reversed(self.notes[-limit:]))

    @property
    def count(self) -> int:
        return len(self.notes)
