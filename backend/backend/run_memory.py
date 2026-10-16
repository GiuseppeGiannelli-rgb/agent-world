"""Spec 08 §4.2: the shared memory of one run.

Every file written, verdict, QA lesson, block and delivery is indexed the
moment it happens, tagged with its workstream, task, team and agent. Search
is BM25 fused with cosine on local n-gram vectors (search.HybridIndex, RRF):
no network and no cost on every write_file, and the same answer every time.
The Brain is the memory across runs; this one lives and dies with its run."""

import time

from backend.embed import LOCAL, local_vectors
from backend.search import HybridIndex

MAX_ITEMS = 2000
TEXT_CHARS = 1200


class RunMemory:
    def __init__(self, rag: dict | None = None):
        rag = rag or {}
        fusion = rag.get("fusion") or {}
        self.min_cosine = float(rag.get("minCosine", 0.25))
        self.dim = int(rag.get("localDim") or 256)
        self.index = HybridIndex(rrf_k=int(fusion.get("k", 60)), weights={"bm25": float(fusion.get("bm25", 1.0)), "vector": float(fusion.get("vector", 1.0))}, min_cosine=self.min_cosine)
        self.items: list[dict] = []

    def add(self, kind: str, text: str, *, ws_id=None, task_id=None, team=None, agent=None, path=None) -> dict | None:
        text = str(text or "").strip()
        if not text or len(self.items) >= MAX_ITEMS:
            return None
        item = {"id": len(self.items), "ts": int(time.time() * 1000), "kind": kind, "text": text[:TEXT_CHARS], "wsId": ws_id, "taskId": task_id, "team": team, "agent": agent, "path": path}
        self.items.append(item)
        self.index.add(item["id"], [{"text": item["text"]}, {"text": f"{kind} {team or ''} {path or ''}", "weight": 2}])
        self.index.add_vectors(item["id"], local_vectors([item["text"]], self.dim), LOCAL)
        return item

    def search(self, query: str, k: int = 5, *, exclude_task=None, kinds=None, min_cosine: float | None = None) -> list[dict]:
        if not self.items or k <= 0:
            return []
        self.index.min_cosine = self.min_cosine if min_cosine is None else min_cosine
        (query_vec,) = local_vectors([query], self.dim)
        out = []
        for hit in self.index.search(query, k * 4 + 8, query_vec):
            item = self.items[hit["id"]]
            if (exclude_task and item["taskId"] == exclude_task) or (kinds and item["kind"] not in kinds):
                continue
            out.append(item)
            if len(out) >= k:
                break
        return out

    def delivered_files(self, *, exclude_ws=None, limit: int = 12) -> list[dict]:
        """The real paths the other workstreams have written, newest last, one per path."""
        seen: dict[str, dict] = {}
        for item in self.items:
            if item["kind"] == "file" and item["path"] and item["wsId"] != exclude_ws:
                seen[item["path"]] = item
        return list(seen.values())[-limit:]
