"""Mirrors server/engine/skills.js: every SKILL.md found in the configured
folders, indexed for search.

Spec 05: hybrid search. Each skill is a BM25 document and a set of chunk
vectors: one for "name + description", plus the semantic chunks of its body
(embed.split_pieces + embed.merge_pieces). All vectors of an index come from
one model, chosen by embed.Embedder."""

import asyncio
import hashlib
import os
import re
import shutil
from pathlib import Path

from backend.embed import Embedder, merge_pieces, split_pieces
from backend.plan import nz
from backend.search import HybridIndex

SKIP = {"node_modules", ".git", "dist", "build", ".next", "__pycache__", ".venv", "venv", ".incoming"}
MAX_FILES = 8000

FRONTMATTER_RE = re.compile(r"^﻿?---\r?\n(.*?)\r?\n---", re.DOTALL)
FRONTMATTER_KV_RE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
FRONTMATTER_CONT_RE = re.compile(r"^\s+\S")
HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
REPO_URL_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


def _expand(p: str, root: Path) -> Path:
    if p == "~" or p.startswith("~/") or p.startswith("~\\"):
        return Path.home() / p[2:]
    return (root / p).resolve()


def parse_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER_RE.match(text)
    meta: dict[str, str] = {}
    if m:
        key = None
        for line in m.group(1).splitlines():
            kv = FRONTMATTER_KV_RE.match(line)
            if kv:
                key = kv.group(1)
                meta[key] = re.sub(r'^["\']|["\']$', "", kv.group(2)).strip()
            elif key and FRONTMATTER_CONT_RE.match(line):
                meta[key] = f"{meta[key]} {line.strip()}".strip()
        body = text[m.end() :]
    else:
        body = text
    return meta, body


async def _head(path: Path, n: int = 6000) -> str:
    def read():
        with open(path, "rb") as f:
            return f.read(n)

    data = await asyncio.to_thread(read)
    return data.decode("utf-8", errors="replace")


async def _git(args: list[str]) -> None:
    proc = await asyncio.create_subprocess_exec("git", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git ha risposto {proc.returncode}: {err.decode(errors='replace')[-300:]}")


class SkillLibrary:
    def __init__(self, root, config, bus=None, embedder: Embedder | None = None):
        self.root = Path(root)
        self.config = config
        self.bus = bus
        self.embedder = embedder or Embedder(config)
        # Spec 05: CUSTOM_DOWNLOAD_PATH joins as the "downloads" source; its skills
        # are third-party and are marked so in the prompts
        self.extra_sources: list[dict] = []
        self.skills: list[dict] = []
        self.by_id: dict[str, dict] = {}
        self.index = self._new_index()
        self._indexing: asyncio.Task | None = None
        self.vendor_dir = self.root / "skills" / "vendor"

    def _new_index(self) -> HybridIndex:
        rag = self.embedder.rag
        fusion = rag.get("fusion") or {}
        return HybridIndex(
            rrf_k=int(fusion.get("k", 60)),
            weights={"bm25": float(fusion.get("bm25", 1.0)), "vector": float(fusion.get("vector", 1.0))},
            min_cosine=float(rag.get("minCosine", 0.2)),
        )

    @property
    def sources(self) -> list[dict]:
        srcs = nz((self.config.get().get("skills") or {}).get("sources"), ["skills"])
        return [{"label": s, "dir": _expand(s, self.root)} for s in srcs] + list(self.extra_sources)

    async def _walk(self, dir: Path, out: list[Path], depth: int = 0) -> None:
        if depth > 9 or len(out) >= MAX_FILES:
            return
        try:
            entries = await asyncio.to_thread(lambda: list(os.scandir(dir)))
        except OSError:
            return
        for e in entries:
            if e.name in SKIP:
                continue
            full = Path(e.path)
            if e.is_dir(follow_symlinks=False):
                await self._walk(full, out, depth + 1)
            elif e.name.lower() == "skill.md":
                out.append(full)

    def reindex(self):
        if self._indexing is None:
            task = asyncio.ensure_future(self._do_index())
            self._indexing = task

            def clear(_):
                if self._indexing is task:
                    self._indexing = None

            task.add_done_callback(clear)
        return self._indexing

    async def _do_index(self) -> int:
        skills = []
        bodies: dict[str, str] = {}  # skill id -> body text, only for chunking
        seen = set()
        for src in self.sources:
            if not src["dir"].exists():
                continue
            files: list[Path] = []
            await self._walk(src["dir"], files)
            for file in files:
                try:
                    text = await _head(file)
                except OSError:
                    continue
                meta, body = parse_frontmatter(text)
                name = (meta.get("name") or file.parent.name)[:80]
                first_para = re.sub(r"^#.*$", "", body, count=1, flags=re.MULTILINE).strip().split("\n\n")[0]
                description = (meta.get("description") or first_para or "")[:600]
                key = f"{name}|{description[:80]}"
                if key in seen:
                    continue
                seen.add(key)
                id_ = hashlib.sha1(str(file).encode()).hexdigest()[:10]
                headings = " ".join(m.group(1) for m in list(HEADING_RE.finditer(body))[:12])
                rel = os.path.relpath(file.parent, src["dir"]).replace(os.sep, "/")
                skills.append({"id": id_, "name": name, "description": description, "source": src["label"], "path": str(file), "rel": rel if rel != "." else name, "headings": headings, "thirdParty": bool(src.get("thirdParty"))})
                bodies[id_] = body
        index = self._new_index()
        for s in skills:
            index.add(
                s["id"],
                [
                    {"text": re.sub(r"[-_]", " ", s["name"]), "weight": 4},
                    {"text": s["description"], "weight": 2},
                    {"text": s["headings"]},
                    {"text": re.sub(r"[/_-]", " ", s["rel"])},
                ],
            )
        await self._add_vectors(index, skills, bodies)
        self.skills = skills
        self.by_id = {s["id"]: s for s in skills}
        self.index = index
        if self.bus is not None:
            self.bus.emit("skills", {"count": len(skills)})
        return len(skills)

    def find(self, id_or_name) -> dict | None:
        if id_or_name in self.by_id:
            return self.by_id[id_or_name]
        q = str(id_or_name or "").lower()
        return next((s for s in self.skills if s["name"].lower() == q), None)

    async def _add_vectors(self, index: HybridIndex, skills: list[dict], bodies: dict[str, str]) -> None:
        """One embedding call for every piece of every skill, then semantic
        chunking per skill. The header ("name: description") is its own chunk."""
        chunk_cfg = self.embedder.rag.get("chunk") or {}
        max_chars = int(chunk_cfg.get("maxChars", 1200))
        min_sim = float(chunk_cfg.get("minSimilarity", 0.5))
        owners, texts = [], []
        for s in skills:
            pieces = [f"{s['name']}: {s['description']}", *split_pieces(bodies.get(s["id"], ""), max_chars)]
            owners.append(len(pieces))
            texts += pieces
        if not texts:
            return
        model, vectors = await self.embedder.embed(texts)
        at = 0
        for s, n in zip(skills, owners):
            pieces, vecs = texts[at : at + n], vectors[at : at + n]
            at += n
            chunks = merge_pieces(pieces[1:], vecs[1:], max_chars=max_chars, min_similarity=min_sim)
            index.add_vectors(s["id"], [vecs[0], *(v for _, v in chunks)], model)

    async def search(self, query: str, k: int = 8) -> list[dict]:
        query_vec = None
        if self.index.model is not None:
            try:
                _, (query_vec,) = await self.embedder.embed([query], model=self.index.model)
            except Exception:  # noqa: BLE001 -- the model stopped answering: BM25 alone
                query_vec = None
        out = []
        for h in self.index.search(query, k, query_vec):
            s = dict(self.by_id[h["id"]])
            s["score"] = round(h["score"], 4)
            s["bm25"] = round(h["bm25"], 2)
            s["cosine"] = round(h["cosine"], 3)
            out.append(s)
        return out

    async def read(self, id_or_name, max: int = 12000) -> dict:
        s = self.find(id_or_name)
        if not s:
            raise ValueError(f"Skill not found: {id_or_name}")
        text = await asyncio.to_thread(Path(s["path"]).read_text, encoding="utf-8")
        if len(text) > max:
            text = f"{text[:max]}\n… [truncated]"
        return {"skill": s, "text": text}

    def summary(self) -> dict:
        by_source: dict[str, int] = {}
        for s in self.skills:
            by_source[s["source"]] = by_source.get(s["source"], 0) + 1
        return {"count": len(self.skills), "vectors": {"model": self.index.model, "chunks": len(self.index.chunk_vec)}, "sources": [{"label": s["label"], "dir": str(s["dir"]), "exists": s["dir"].exists(), "count": by_source.get(s["label"], 0)} for s in self.sources]}

    async def refresh(self):
        if self._indexing is not None:
            await self._indexing
        return await self.reindex()

    def repo(self, url) -> dict | None:
        m = REPO_URL_RE.match(str(url or "").strip())
        if not m:
            return None
        owner, name = m.group(1), m.group(2)
        return {"slug": f"{owner}/{name}", "url": f"https://github.com/{owner}/{name}.git", "dir": self.vendor_dir / f"{owner}-{name}"}

    async def add_repo(self, url) -> dict:
        repo = self.repo(url)
        if not repo:
            raise ValueError("Serve un indirizzo GitHub del tipo https://github.com/utente/repo")
        self.vendor_dir.mkdir(parents=True, exist_ok=True)
        if repo["dir"].exists():
            await _git(["-C", str(repo["dir"]), "pull", "--ff-only"])
        else:
            await _git(["clone", "--depth", "1", repo["url"], str(repo["dir"])])
        before = len(self.skills)
        await self.refresh()
        return {"repo": repo["slug"], "path": str(repo["dir"]), "added": len(self.skills) - before, "total": len(self.skills)}

    async def ensure_repos(self) -> list[str]:
        added = []
        for url in (self.config.get().get("skills") or {}).get("repos") or []:
            repo = self.repo(url)
            if not repo:
                print(f"Skill Hub    →  repo ignorata, non è un indirizzo GitHub: {url}")
                continue
            if repo["dir"].exists():
                continue
            tmp = self.vendor_dir / ".incoming" / repo["dir"].name
            try:
                await asyncio.to_thread(shutil.rmtree, tmp, True)
                await asyncio.to_thread(tmp.parent.mkdir, parents=True, exist_ok=True)
                await _git(["clone", "--depth", "1", repo["url"], str(tmp)])
                await asyncio.to_thread(os.rename, tmp, repo["dir"])
                added.append(repo["slug"])
            except Exception as err:  # noqa: BLE001 -- never throws, like ensureRepos() in Node
                await asyncio.to_thread(shutil.rmtree, tmp, True)
                if not repo["dir"].exists():
                    print(f"Skill Hub    →  {repo['slug']} non scaricata: {str(err).splitlines()[0]}")
        if added:
            await self.refresh()
        return added
