"""Vectors for the hybrid search (Spec 05): text -> unit vector, and semantic chunking.

The model comes from config `rag.embeddings`, an ordered list like a combo:
- a provider model ("openai/text-embedding-3-small", "mistral/mistral-embed",
  "ollama/nomic-embed-text", ...) is called on the provider's OpenAI-compatible
  /embeddings endpoint: real semantic embeddings, cached on disk by text hash;
- "local/ngram" hashes the character 3- and 4-grams of every token into a fixed
  vector (feature hashing). No model, no network, deterministic: it matches shared
  stems and spelling variants ("tipografia" ~ "typography"), not meaning. It is the
  fallback in demo mode and whenever no provider of the list is ready or answers.

Every vector is L2-normalized, so cosine similarity is a dot product.
"""

import asyncio
import hashlib
import json
import math
import os
import re
import zlib
from pathlib import Path

from backend.search import tokenize

LOCAL = "local/ngram"
DEFAULT_LOCAL_DIM = 256
BATCH = 64
TIMEOUT_S = 30


def normalize(vec: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in vec))
    return [x / n for x in vec] if n > 0 else vec


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def ngram_vector(text, dim: int = DEFAULT_LOCAL_DIM) -> list[float]:
    """Signed feature hashing of " token " 3- and 4-grams and of whole tokens.
    Tokens come from search.tokenize (lowercase, accents folded, [a-z0-9] only),
    so every gram is ASCII. Mirrored by aw_core.ngram_vector (CRC-32 IEEE)."""
    vec = [0.0] * dim
    for token in tokenize(text):
        grams = [f"w:{token}"]
        padded = f" {token} "
        for n in (3, 4):
            grams += [padded[i : i + n] for i in range(len(padded) - n + 1)]
        for g in grams:
            h = zlib.crc32(g.encode("ascii"))
            vec[h % dim] += -1.0 if h & 0x80000000 else 1.0
    return normalize(vec)


def _load_rust_ngram():
    """aw_core.ngram_vector, only if it reproduces the Python vectors exactly:
    vectors of the two implementations must never be mixed in one index."""
    try:
        import aw_core

        fn = aw_core.ngram_vector
        probes = ["Caffè e tipografia", "Check the HMAC signature of every webhook", "", "il la di", "naïve façade 2026"]
        return fn if all(list(fn(s, DEFAULT_LOCAL_DIM)) == ngram_vector(s) for s in probes) else None
    except Exception:
        return None


RUST_NGRAM = _load_rust_ngram()


def local_vectors(texts: list[str], dim: int = DEFAULT_LOCAL_DIM) -> list[list[float]]:
    if RUST_NGRAM is not None:
        try:
            return [list(RUST_NGRAM(t, dim)) for t in texts]
        except Exception:
            pass
    return [ngram_vector(t, dim) for t in texts]


# ---------- semantic chunking ----------

_HEADING = re.compile(r"^#{1,6}\s")


def split_pieces(text: str, max_chars: int) -> list[str]:
    """Paragraphs, with each heading glued to the paragraph after it; a paragraph
    longer than max_chars is cut at sentence ends (or hard, as a last resort)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text or "") if b.strip()]
    pieces: list[str] = []
    pending_heading = ""
    for block in blocks:
        if _HEADING.match(block) and "\n" not in block:
            pending_heading = f"{pending_heading}\n{block}".strip()
            continue
        block = f"{pending_heading}\n{block}".strip() if pending_heading else block
        pending_heading = ""
        while len(block) > max_chars:
            cut = max(block.rfind(". ", 0, max_chars), block.rfind("\n", 0, max_chars))
            cut = cut + 1 if cut > max_chars // 3 else max_chars
            pieces.append(block[:cut].strip())
            block = block[cut:].strip()
        if block:
            pieces.append(block)
    if pending_heading:
        pieces.append(pending_heading)
    return pieces


def merge_pieces(pieces: list[str], vectors: list[list[float]], *, max_chars: int, min_similarity: float) -> list[tuple[str, list[float]]]:
    """Semantic chunking: walk the pieces in order and keep adding to the current
    chunk while the next piece is similar to it (cosine with the chunk's running
    centroid >= min_similarity) and the chunk stays under max_chars. A heading
    always opens a new chunk. Chunk vector = normalized sum of its pieces."""
    chunks: list[tuple[str, list[float]]] = []
    text, total = "", None
    for piece, vec in zip(pieces, vectors):
        joinable = (
            total is not None
            and not _HEADING.match(piece)
            and len(text) + 2 + len(piece) <= max_chars
            and dot(normalize(total), vec) >= min_similarity
        )
        if joinable:
            text = f"{text}\n\n{piece}"
            total = [a + b for a, b in zip(total, vec)]
            continue
        if total is not None:
            chunks.append((text, normalize(total)))
        text, total = piece, list(vec)
    if total is not None:
        chunks.append((text, normalize(total)))
    return chunks


# ---------- the embedder ----------


class Embedder:
    """Picks the first ready model of `rag.embeddings` and turns texts into unit
    vectors. Remote vectors are cached per model in <data>/embeddings/."""

    def __init__(self, config, *, router=None, cache_dir: Path | None = None, client=None):
        self.config = config
        self.router = router
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.client = client or (router.client if router is not None else None)
        self._cache: dict[str, dict[str, list[float]]] = {}
        self._lock = asyncio.Lock()

    def _cfg(self) -> dict:
        return (self.config.get() if self.config is not None else None) or {}

    @property
    def rag(self) -> dict:
        return self._cfg().get("rag") or {}

    @property
    def local_dim(self) -> int:
        return int(self.rag.get("localDim") or DEFAULT_LOCAL_DIM)

    def candidates(self) -> list[str]:
        """Models to try, in order: the ready providers of the list, then local."""
        out = []
        providers = self._cfg().get("providers") or {}
        for target in self.rag.get("embeddings") or []:
            provider, _, model = str(target).partition("/")
            if provider == "local":
                continue
            p = providers.get(provider) or {}
            if not model or p.get("kind") != "openai" or self.router is None or self.client is None:
                continue
            if self.router.provider_ready(provider):
                out.append(target)
        return [*out, LOCAL]

    def embed_local(self, texts: list[str]) -> list[list[float]]:
        return local_vectors(texts, self.local_dim)

    async def embed(self, texts: list[str], *, model: str | None = None) -> tuple[str, list[list[float]]]:
        """(model used, vectors). With `model`, only that model is tried (a query
        must use the model of the index it searches) and errors propagate."""
        if model is not None:
            return model, await self._embed_with(model, texts)
        for target in self.candidates():
            try:
                return target, await self._embed_with(target, texts)
            except Exception:  # noqa: BLE001 -- a failing provider falls through to the next model
                continue
        return LOCAL, self.embed_local(texts)

    async def _embed_with(self, target: str, texts: list[str]) -> list[list[float]]:
        if target == LOCAL:
            return self.embed_local(texts)
        cache = await self._load_cache(target)
        keys = [hashlib.sha1(f"{target}\0{t}".encode()).hexdigest() for t in texts]
        missing = [i for i, k in enumerate(keys) if k not in cache]
        for start in range(0, len(missing), BATCH):
            batch = missing[start : start + BATCH]
            vectors = await self._remote(target, [texts[i] for i in batch])
            for i, vec in zip(batch, vectors):
                cache[keys[i]] = vec
        if missing:
            await self._save_cache(target)
        return [cache[k] for k in keys]

    async def _remote(self, target: str, inputs: list[str]) -> list[list[float]]:
        provider_id, _, model = target.partition("/")
        p = self._cfg()["providers"][provider_id]
        key = os.environ.get(p["keyEnv"]) if p.get("keyEnv") else None
        headers = {"authorization": f"Bearer {key}"} if key else {}
        body = {"model": model, "input": [t[:8000] or " " for t in inputs]}
        if self.rag.get("dimensions") and provider_id == "openai":
            body["dimensions"] = int(self.rag["dimensions"])
        res = await self.client.post(p["baseUrl"].rstrip("/") + "/embeddings", headers=headers, json=body, timeout=TIMEOUT_S)
        if res.status_code >= 400:
            raise RuntimeError(f"{target}: HTTP {res.status_code}")
        data = sorted(res.json()["data"], key=lambda d: d.get("index", 0))
        if len(data) != len(inputs):
            raise RuntimeError(f"{target}: {len(data)} vectors for {len(inputs)} inputs")
        return [normalize([float(x) for x in d["embedding"]]) for d in data]

    def _cache_file(self, target: str) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{re.sub(r'[^A-Za-z0-9._-]+', '_', target)}.json"

    async def _load_cache(self, target: str) -> dict[str, list[float]]:
        if target not in self._cache:
            file = self._cache_file(target)
            data = {}
            if file is not None and file.exists():
                try:
                    data = json.loads(await asyncio.to_thread(file.read_text, encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}  # a broken cache is rebuilt, never fatal
            self._cache[target] = data
        return self._cache[target]

    async def _save_cache(self, target: str) -> None:
        file = self._cache_file(target)
        if file is None:
            return
        async with self._lock:
            text = json.dumps({k: [round(x, 6) for x in v] for k, v in self._cache[target].items()})
            await asyncio.to_thread(file.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(file.write_text, text, encoding="utf-8")
