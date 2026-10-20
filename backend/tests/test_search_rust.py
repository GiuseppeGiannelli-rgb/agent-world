"""P6 contract for the Rust bridge (Spec 04 §4.8, decision D1): whatever
object the bm25() factory hands out -- native aw_core.Bm25 or the pure-Python
fallback -- must behave exactly like the reference Bm25 on a golden corpus:
same ranking, same scores (within float noise). The factory itself must fall
back to Python when the native module is missing or fails the parity probe."""

import math

import pytest

from backend import search as search_mod
from backend.search import Bm25, bm25, tokenize

# Golden corpus: accents, case, punctuation, weights, stopwords, a field with
# no usable tokens and a doc that tokenizes to nothing (zero-length edge).
GOLDEN_DOCS = [
    ("img", [{"text": "image prompting", "weight": 4}, {"text": "write prompts for image generation models"}]),
    ("sec", [{"text": "security review", "weight": 4}, {"text": "find XSS and injection in web code"}]),
    ("pizza", [{"text": "Più cose per una pizza: ricetta della tradizione", "weight": 2}]),
    ("café", [{"text": "CAFÉ menù, caffè e cappuccino al banco"}]),
    ("voice", [{"text": "text to speech voice over", "weight": 3}, {"text": "audio narration"}]),
    ("deploy", [{"text": "deploy static site to the edge CDN"}]),
    ("empty-field", [{"text": "", "weight": 5}, {"text": None}]),
    ("zero", [{"text": "il la di un per"}]),  # only stopwords -> len 0
    ("svg", [{"text": "inline SVG icons and illustrations", "weight": 2}, {"text": "vector art for the web"}]),
    ("tests", [{"text": "unit tests integration tests end to end tests", "weight": 2}]),
    ("brain", [{"text": "memory notes recall past decisions and facts", "weight": 3}]),
    ("router", [{"text": "route each prompt to the cheapest capable model"}]),
    # spec 11 T03: code tokens and other scripts
    ("gate", [{"text": "budget_gate() and std::collections::HashMap", "weight": 2}, {"text": "@pytest.fixture for user@example.com"}]),
    ("ru", [{"text": "Сервер отвечает на запросы"}]),
    ("el", [{"text": "Ο λόγος της απόφασης", "weight": 2}]),
    ("hi", [{"text": "हिन्दी भाषा का सर्वर"}]),
]

GOLDEN_QUERIES = [
    "generate a hero image",
    "controlla XSS injection",
    "ricetta pizza",
    "caffè al banco",
    "voice over narration",
    "deploy sito statico",
    "test end to end",
    "ricorda decisioni passate",
    "   ",          # no terms -> []
    "xyzzy",        # no hits -> []
    "image image image",  # repeated terms are deduped
    "budget_gate",
    "HashMap std::collections",
    "@pytest",
    "СЕРВЕР",
    "ΛΟΓΟΣ",
    "भाषा",
]


def _reference_results() -> dict:
    idx = Bm25()
    for doc_id, fields in GOLDEN_DOCS:
        idx.add(doc_id, fields)
    return {q: idx.search(q, 8) for q in GOLDEN_QUERIES}


def test_factory_returns_bm25_interface():
    idx = bm25()
    idx.add("x", [{"text": "image prompting", "weight": 4}])
    idx.add("y", [{"text": "security review"}])
    out = idx.search("image", 5)
    assert out and out[0]["id"] == "x" and out[0]["score"] > 0
    assert idx.search("   ") == []


def test_factory_falls_back_to_python_without_aw_core():
    # aw_core is not built in this environment (no Rust toolchain yet), so
    # the factory must hand out the pure-Python class.
    if search_mod.RUST_BM25 is None:
        assert isinstance(bm25(), Bm25)


def test_golden_corpus_parity():
    ref = _reference_results()
    idx = bm25()
    for doc_id, fields in GOLDEN_DOCS:
        idx.add(doc_id, fields)
    for q in GOLDEN_QUERIES:
        got = idx.search(q, 8)
        assert [r["id"] for r in got] == [r["id"] for r in ref[q]], f"ranking mismatch on {q!r}"
        for a, b in zip(got, ref[q]):
            assert math.isclose(a["score"], b["score"], rel_tol=1e-9, abs_tol=1e-12), f"score mismatch on {q!r}"


def test_incremental_avg_len_matches_recomputed():
    # The optimized Python fallback keeps a running total instead of summing
    # all docs on every add; same additions in the same order, so the result
    # must be bit-identical to the naive version.
    idx = Bm25()
    for doc_id, fields in GOLDEN_DOCS:
        idx.add(doc_id, fields)
        naive = sum(d["len"] for d in idx.docs) / len(idx.docs)
        assert idx.avg_len == naive


def test_tokenize_contract_unchanged():
    # The Rust tokenizer must reproduce this exact stream; pin it here.
    assert tokenize("Più cose per una pizza") == ["cose", "pizza"]
    assert tokenize("CAFÉ, Caffè!") == ["cafe", "caffe"]
    assert tokenize("a an the il di") == []  # len<=2 or stopwords
    assert tokenize(None) == []


# ---------- spec 11 T03: the tokenizer in the startup probe ----------


def test_the_probe_texts_cover_code_and_every_script():
    from backend.search import TOKENIZE_PROBES

    joined = " ".join(TOKENIZE_PROBES)
    for piece in ("_", "::", "@", "ς", "λ", "м", "ि", "数", "ø", "İ"):
        assert piece in joined, piece


def test_rust_tokenize_matches_python_on_the_probes():
    aw_core = pytest.importorskip("aw_core")
    from backend.search import TOKENIZE_PROBES

    for text in TOKENIZE_PROBES:
        assert list(aw_core.tokenize(text)) == tokenize(text), text


def _old_tokenize(text):
    """The [a-z0-9] tokenizer of spec 04-05: what an aw_core built before T03 does."""
    import re
    import unicodedata

    s = re.sub(r"[̀-ͯ]", "", unicodedata.normalize("NFD", str(text or "").lower()))
    return [w for w in re.split(r"[^a-z0-9]+", s) if len(w) > 2 and w not in search_mod.STOP]


def test_a_native_module_with_the_old_tokenizer_is_refused(monkeypatch):
    """The gate at startup: an aw_core whose BM25 ranks like Python on the old
    probe but tokenizes like before T03 must not be used, or the index and the
    queries would split words differently from the Python code around them."""
    import sys
    import types

    from backend import embed

    old = types.SimpleNamespace(Bm25=Bm25, tokenize=_old_tokenize, ngram_vector=lambda text, dim=256: _old_ngram(text, dim))
    monkeypatch.setitem(sys.modules, "aw_core", old)
    assert search_mod._load_rust() is None
    assert embed._load_rust_ngram() is None
    same = types.SimpleNamespace(Bm25=Bm25, tokenize=tokenize, ngram_vector=embed.ngram_vector)
    monkeypatch.setitem(sys.modules, "aw_core", same)
    assert search_mod._load_rust() is Bm25
    assert embed._load_rust_ngram() is embed.ngram_vector


def _old_ngram(text, dim):
    import zlib

    from backend.embed import normalize

    vec = [0.0] * dim
    for token in _old_tokenize(text):
        padded = f" {token} "
        for g in [f"w:{token}"] + [padded[i : i + n] for n in (3, 4) for i in range(len(padded) - n + 1)]:
            h = zlib.crc32(g.encode("ascii"))
            vec[h % dim] += -1.0 if h & 0x80000000 else 1.0
    return normalize(vec)


# ---------- Spec 05: vectors (run when aw_core is built) ----------

VECTOR_TEXTS = ["Caffè e tipografia", "Check the HMAC signature of every incoming webhook", "", "il la di", "x", "İstanbul ŞEHİR", "naïve façade — 2026!", "budget_gate() std::mem::take @app", "Ο λόγος, Сервер, हिन्दी, 数据库"]


def test_rust_ngram_vector_is_bit_identical():
    aw_core = pytest.importorskip("aw_core")
    from backend.embed import ngram_vector

    for text in VECTOR_TEXTS:
        for dim in (8, 256):
            assert list(aw_core.ngram_vector(text, dim)) == ngram_vector(text, dim), (text, dim)


def test_rust_cosine_top_k_matches_python():
    aw_core = pytest.importorskip("aw_core")
    from backend.embed import ngram_vector
    from backend.search import _cosine_top_k_py

    vectors = [ngram_vector(t) for t in VECTOR_TEXTS] + [ngram_vector(VECTOR_TEXTS[0])]  # a tie
    query = ngram_vector("tipografia del caffè")
    got = aw_core.cosine_top_k(query, [x for v in vectors for x in v], 256, 5)
    assert [(i, s) for i, s in got] == _cosine_top_k_py(query, vectors, 5)
    with pytest.raises(ValueError):
        aw_core.cosine_top_k(query, [1.0, 2.0, 3.0], 256, 1)


def test_vector_factories_fall_back_without_aw_core():
    from backend import embed
    from backend import search as s

    try:
        import aw_core  # noqa: F401
    except ImportError:
        assert embed.RUST_NGRAM is None and s.RUST_COSINE is None
        assert embed.local_vectors(["pizza"]) == [embed.ngram_vector("pizza")]
