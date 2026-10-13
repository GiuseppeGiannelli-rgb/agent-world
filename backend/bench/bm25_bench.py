"""P6 adoption benchmark (Spec 04, decision D1): the Rust BM25 enters
production only if it beats the optimized pure-Python Bm25 by at least 5x
on the measured corpus.

Corpus: the REAL data when available (data/brain.json notes + indexed skill
files), padded to size with a seeded generator over the same vocabulary, so
the measurement reflects the production token mix.

Run from the repo root:

    uv run --directory backend python bench/bm25_bench.py

Prints the timings, the speedup and the verdict (ADOPT / FALLBACK)."""

import json
import random
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from backend.search import Bm25, tokenize  # noqa: E402

try:
    import aw_core

    RUST = aw_core.Bm25
except Exception:
    RUST = None

N_DOCS = 20_000
N_QUERIES = 2_000
THRESHOLD = 5.0


def real_documents() -> list[tuple[str, list[dict]]]:
    docs = []
    brain = ROOT / "data" / "brain.json"
    if brain.exists():
        try:
            for n in json.loads(brain.read_text(encoding="utf-8")).get("notes", []):
                docs.append((n["id"], [{"text": n.get("title"), "weight": 4}, {"text": n.get("text")}]))
        except Exception:
            pass
    skills_dir = ROOT / "skills"
    if skills_dir.exists():
        for f in sorted(skills_dir.rglob("SKILL.md"))[:500]:
            try:
                docs.append((f"skill:{f.parent.name}", [{"text": f.parent.name, "weight": 4}, {"text": f.read_text(encoding="utf-8", errors="ignore")[:4000]}]))
            except Exception:
                pass
    return docs


def synthetic_documents(vocab: list[str], n: int, seed: int = 42) -> list[tuple[str, list[dict]]]:
    rng = random.Random(seed)
    docs = []
    for i in range(n):
        title = " ".join(rng.choices(vocab, k=rng.randint(2, 5)))
        body = " ".join(rng.choices(vocab, k=rng.randint(20, 120)))
        docs.append((f"syn-{i}", [{"text": title, "weight": 4}, {"text": body}]))
    return docs


def bench(cls, docs, queries) -> float:
    idx = cls()
    t0 = time.perf_counter()
    for doc_id, fields in docs:
        idx.add(doc_id, fields)
    t1 = time.perf_counter()
    for q in queries:
        idx.search(q, 10)
    t2 = time.perf_counter()
    return (t1 - t0, t2 - t1)


def main() -> int:
    docs = real_documents()
    vocab = sorted({t for _, fields in docs for f in fields for t in tokenize(f.get("text"))})
    if len(vocab) < 200:  # not enough real data yet: fall back to a generic mix
        vocab = sorted({t for _, fields in GOLDEN for t in tokenize(fields)})
    if len(docs) < N_DOCS:
        docs = docs + synthetic_documents(vocab, N_DOCS - len(docs))
    rng = random.Random(7)
    queries = [" ".join(rng.choices(vocab, k=rng.randint(1, 4))) for _ in range(N_QUERIES)]

    print(f"Corpus: {len(docs)} docs ({len(real_documents())} reali), {len(vocab)} termini, {N_QUERIES} query")
    py_add, py_search = bench(Bm25, docs, queries)
    print(f"Python  add {py_add:6.3f}s   search {py_search:6.3f}s")
    if RUST is None:
        print("Rust    NON DISPONIBILE (aw_core non compilato) -> FALLBACK Python attivo")
        print("Verdetto: FALLBACK (soglia 5x non misurabile)")
        return 0
    rs_add, rs_search = bench(RUST, docs, queries)
    print(f"Rust    add {rs_add:6.3f}s   search {rs_search:6.3f}s")
    speedup = (py_add + py_search) / (rs_add + rs_search)
    print(f"Speedup complessivo: {speedup:.1f}x  (soglia di adozione: {THRESHOLD:.0f}x)")
    print(f"Verdetto: {'ADOPT' if speedup >= THRESHOLD else 'FALLBACK'}")
    return 0


# Small built-in corpus when the repo has no real data yet.
GOLDEN = [
    ("a", [{"text": "image prompting generation models", "weight": 4}]),
    ("b", [{"text": "security review XSS injection web code"}]),
    ("c", [{"text": "deploy static site edge CDN cache"}]),
    ("d", [{"text": "text to speech voice over audio narration"}]),
    ("e", [{"text": "ricetta pizza tradizione forno legna"}]),
    ("f", [{"text": "memory notes recall past decisions facts"}]),
    ("g", [{"text": "route prompt cheapest capable model router"}]),
    ("h", [{"text": "unit tests integration end to end suite"}]),
]

if __name__ == "__main__":
    raise SystemExit(main())
