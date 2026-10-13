"""Tiny BM25 index, ported 1:1 from server/engine/search.js. Used by the
skill library and the brain. No dependencies."""

import math
import re
import unicodedata

STOP = set(
    "the and for with that this from into your you are not but all any can una uno per con che del della delle "
    "dei degli gli le la il lo di da in su tra fra come cosa sono non piu più anche".split(" ")
)

_SPLIT_RE = re.compile(r"[^a-z0-9]+")
_COMBINING_RE = re.compile(r"[̀-ͯ]")  # combining diacritics, after NFD decomposition


def tokenize(text) -> list[str]:
    s = str(text if text is not None else "").lower()
    s = _COMBINING_RE.sub("", unicodedata.normalize("NFD", s))
    return [w for w in _SPLIT_RE.split(s) if len(w) > 2 and w not in STOP]


class Bm25:
    def __init__(self, k1: float = 1.4, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[dict] = []
        self.df: dict[str, int] = {}
        # P6: incremental index -- a running total instead of re-summing every
        # doc on each add. Same additions in the same order, so avg_len is
        # bit-identical to the naive version (pinned by test_search_rust.py).
        self._total_len = 0.0

    @property
    def avg_len(self) -> float:
        return self._total_len / len(self.docs) if self.docs else 0.0

    def add(self, id, fields: list[dict]) -> None:
        """fields: [{text, weight}]"""
        tf: dict[str, float] = {}
        length = 0.0
        for f in fields:
            weight = f.get("weight", 1)
            for t in tokenize(f.get("text")):
                tf[t] = tf.get(t, 0) + weight
                length += weight
        for t in tf:
            self.df[t] = self.df.get(t, 0) + 1
        self.docs.append({"id": id, "tf": tf, "len": length})
        self._total_len += length

    def search(self, query: str, k: int = 10) -> list[dict]:
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms:
            return []
        n = len(self.docs)
        scored = []
        for d in self.docs:
            score = 0.0
            for t in terms:
                f = d["tf"].get(t)
                if not f:
                    continue
                df = self.df.get(t, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += idf * ((f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + (self.b * d["len"]) / (self.avg_len or 1))))
            if score > 0:
                scored.append({"id": d["id"], "score": score})
        scored.sort(key=lambda x: -x["score"])
        return scored[:k]


# ---------- P6: Rust bridge seam (Spec 04 §4.8, D1) ----------
#
# crates/aw_core (PyO3, built with maturin) exposes a native Bm25 with the
# same interface. It is adopted only past the 5x threshold measured by
# bench/bm25_bench.py; until then -- or whenever the native module is missing
# or fails the probe below -- every caller transparently gets the pure-Python
# class. Nothing else in the codebase changes either way.


def _load_rust():
    try:
        import aw_core

        return aw_core.Bm25
    except Exception:
        return None


def _parity_probe(rust_cls) -> bool:
    """Adoption gate: the native index is used only if it reproduces the
    pure-Python ranking (ids, order and scores) on a tiny probe corpus."""
    try:
        rust, py = rust_cls(), Bm25()
        probe = [
            ("a", [{"text": "Più cose per una pizza", "weight": 2}, {"text": "ricetta della tradizione"}]),
            ("b", [{"text": "security review", "weight": 4}, {"text": "find XSS and injection"}]),
            ("c", [{"text": "il la di un per"}]),  # zero-length doc
        ]
        for doc_id, fields in probe:
            rust.add(doc_id, fields)
            py.add(doc_id, fields)
        for q in ("pizza ricetta", "XSS", "   ", "xyzzy"):
            r, p = rust.search(q, 5), py.search(q, 5)
            if [x["id"] for x in r] != [x["id"] for x in p]:
                return False
            if any(not math.isclose(x["score"], y["score"], rel_tol=1e-9, abs_tol=1e-12) for x, y in zip(r, p)):
                return False
        return True
    except Exception:
        return False


RUST_BM25 = _load_rust()
if RUST_BM25 is not None and not _parity_probe(RUST_BM25):
    RUST_BM25 = None  # native module present but off-contract: ignore it


def bm25(k1: float = 1.4, b: float = 0.75):
    """Factory for the BM25 index: native Rust when the aw_core module is
    built and passes the parity probe, otherwise the pure-Python Bm25.
    Same add(id, fields) / search(query, k) interface either way."""
    if RUST_BM25 is not None:
        try:
            return RUST_BM25(k1, b)
        except Exception:
            pass
    return Bm25(k1, b)
