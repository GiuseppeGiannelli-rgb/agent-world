"""Spec 05: hybrid retrieval -- local vectors, semantic chunking, cosine top-k,
RRF fusion, the embedder (remote + cache + fallback), Brain and Skill Hub."""

import json
import math

import httpx
import pytest

from backend.embed import LOCAL, Embedder, dot, merge_pieces, ngram_vector, split_pieces
from backend.search import HybridIndex, _cosine_top_k_py, cosine_top_k, rrf


class Cfg:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


# ---------- local vectors ----------


def test_ngram_vector_is_deterministic_unit_and_folds_accents():
    a, b = ngram_vector("Caffè e tipografia"), ngram_vector("caffe E TIPOGRAFIA")
    assert a == b
    assert len(a) == 256
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert ngram_vector("il la di") == [0.0] * 256  # only stopwords: no tokens, zero vector


def test_ngram_vector_ranks_shared_stems_above_unrelated_text():
    # measured on 2026-10-14: word variants 0.44-0.76; 66 unrelated pairs of skill
    # descriptions max 0.241 (p90 0.13) -> rag.minCosine 0.25. Across languages on
    # longer texts the local vectors are weak (that is what provider models are for).
    related = dot(ngram_vector("typographic"), ngram_vector("typography"))
    unrelated = dot(ngram_vector("typographic"), ngram_vector("pizza napoletana forno a legna"))
    assert related > 0.25 > unrelated


# ---------- semantic chunking ----------


def test_split_pieces_glues_headings_and_cuts_long_paragraphs():
    text = "# Title\n\nFirst paragraph.\n\n## Part\n\n" + "Sentence one. " * 40
    pieces = split_pieces(text, 200)
    assert pieces[0] == "# Title\nFirst paragraph."
    assert pieces[1].startswith("## Part\n")
    assert all(len(p) <= 200 for p in pieces)
    assert "".join(pieces).count("Sentence one.") == 40  # nothing lost


def test_merge_pieces_joins_similar_neighbours_only():
    pieces = ["pizza oven dough", "pizza dough hydration", "kubernetes cluster", "## Deploy\nkubernetes pods"]
    vecs = [ngram_vector(p) for p in pieces]
    chunks = merge_pieces(pieces, vecs, max_chars=1000, min_similarity=0.3)
    texts = [t for t, _ in chunks]
    assert texts[0] == "pizza oven dough\n\npizza dough hydration"  # similar: one chunk
    assert texts[1] == "kubernetes cluster"  # a change of topic opens a chunk
    assert texts[2].startswith("## Deploy")  # a heading always opens a chunk
    assert all(math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-9) for _, v in chunks)


def test_merge_pieces_respects_max_chars():
    pieces = ["pizza dough " * 5] * 4
    chunks = merge_pieces(pieces, [ngram_vector(p) for p in pieces], max_chars=130, min_similarity=0.0)
    assert len(chunks) == 2 and all(len(t) <= 130 for t, _ in chunks)


# ---------- cosine top-k and fusion ----------


def test_cosine_top_k_orders_best_first_ties_by_row():
    vectors = [[1.0, 0.0], [0.6, 0.8], [0.0, 1.0], [0.6, 0.8]]
    got = cosine_top_k([0.8, 0.6], vectors, 3)
    assert [i for i, _ in got] == [1, 3, 0]
    assert got == _cosine_top_k_py([0.8, 0.6], vectors, 3)
    assert cosine_top_k([1.0, 0.0], [], 3) == []


def test_rrf_sums_weighted_reciprocal_ranks():
    fused = rrf([(["a", "b"], 1.0), (["b", "c"], 2.0)], k=60)
    assert math.isclose(fused["a"], 1 / 61)
    assert math.isclose(fused["b"], 1 / 62 + 2 / 61)
    assert math.isclose(fused["c"], 2 / 62)


def _index(docs, *, vectors=True):
    idx = HybridIndex(min_cosine=0.25)
    for id_, text in docs.items():
        idx.add(id_, [{"text": text}])
        if vectors:
            idx.add_vectors(id_, [ngram_vector(text)], LOCAL)
    return idx


DOCS = {
    "typo": "typography and color palette for the site",
    "pizza": "pizza napoletana forno a legna",
    "k8s": "kubernetes cluster autoscaling",
}


def test_hybrid_without_query_vector_is_bm25():
    idx = _index(DOCS)
    hits = idx.search("pizza forno", 5)
    assert [h["id"] for h in hits] == ["pizza"]
    assert hits[0]["bm25"] > 0 and hits[0]["cosine"] == 0.0


def test_hybrid_finds_by_vector_what_bm25_misses():
    idx = _index(DOCS)
    query = "typographic"
    assert idx.bm25.search(query, 5) == []  # no shared token
    hits = idx.search(query, 5, ngram_vector(query))
    assert [h["id"] for h in hits] == ["typo"]  # the unrelated docs stay under min_cosine
    assert hits[0]["cosine"] > 0.25 and hits[0]["bm25"] == 0.0


def test_hybrid_puts_documents_found_both_ways_first():
    idx = _index({**DOCS, "fonts": "web fonts and typographic scale"})
    query = "typography palette"
    hits = idx.search(query, 5, ngram_vector(query))
    assert hits[0]["id"] == "typo" and hits[0]["bm25"] > 0 and hits[0]["cosine"] > 0


def test_index_refuses_vectors_of_two_models():
    idx = _index(DOCS)
    with pytest.raises(ValueError):
        idx.add_vectors("x", [[1.0]], "openai/text-embedding-3-small")


# ---------- embedder ----------


class FakeRouter:
    def __init__(self, client):
        self.client = client

    def provider_ready(self, id):
        return id == "openai"


CFG = {
    "providers": {"openai": {"kind": "openai", "baseUrl": "https://api.example/v1", "keyEnv": "TEST_EMBED_KEY"}, "mock": {"kind": "mock"}},
    "rag": {"embeddings": ["openai/text-embedding-3-small"], "dimensions": 8},
}


def _transport(calls, *, status=200):
    def handler(request: httpx.Request):
        body = json.loads(request.content)
        calls.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        if status != 200:
            return httpx.Response(status, json={"error": "nope"})
        data = [{"index": i, "embedding": [float(len(t)), 1.0, 0.0]} for i, t in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})  # order restored by "index"

    return httpx.MockTransport(handler)


async def test_embedder_without_keys_uses_local():
    emb = Embedder(Cfg({"rag": CFG["rag"], "providers": CFG["providers"]}))  # no router: no provider
    model, vecs = await emb.embed(["pizza"])
    assert model == LOCAL and vecs[0] == ngram_vector("pizza")


async def test_embedder_calls_the_provider_caches_and_persists(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "k-test")
    calls = []
    client = httpx.AsyncClient(transport=_transport(calls))
    emb = Embedder(Cfg(CFG), router=FakeRouter(client), cache_dir=tmp_path)
    model, vecs = await emb.embed(["ab", "abcd"])
    assert model == "openai/text-embedding-3-small"
    assert calls[0]["url"] == "https://api.example/v1/embeddings"
    assert calls[0]["auth"] == "Bearer k-test"
    assert calls[0]["body"] == {"model": "text-embedding-3-small", "input": ["ab", "abcd"], "dimensions": 8}
    assert math.isclose(vecs[1][0], 4 / math.sqrt(17))  # normalized, in input order
    await emb.embed(["ab", "abcd"])
    assert len(calls) == 1  # second time from the cache
    fresh = Embedder(Cfg(CFG), router=FakeRouter(client), cache_dir=tmp_path)
    _, again = await fresh.embed(["abcd"], model=model)
    assert len(calls) == 1 and again[0] == pytest.approx(vecs[1], abs=1e-6)  # from disk
    await client.aclose()


async def test_embedder_falls_back_to_local_and_fixed_model_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_EMBED_KEY", "k-test")
    calls = []
    client = httpx.AsyncClient(transport=_transport(calls, status=500))
    emb = Embedder(Cfg(CFG), router=FakeRouter(client), cache_dir=tmp_path)
    model, vecs = await emb.embed(["pizza"])
    assert model == LOCAL and vecs[0] == ngram_vector("pizza")
    with pytest.raises(RuntimeError):
        await emb.embed(["pizza"], model="openai/text-embedding-3-small")
    await client.aclose()


# ---------- Brain and Skill Hub ----------


async def test_brain_add_is_incremental_and_search_uses_vectors(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    index = brain.index
    brain.add(title="Typography rules", text="use two font families at most")
    brain.add(title="Forno", text="pizza napoletana a 450 gradi")
    assert brain.index is index  # no rebuild on add
    hits = await brain.search("typographic", 3)
    assert [h["title"] for h in hits] == ["Typography rules"]
    assert brain.index.model == LOCAL and len(brain.index.chunk_vec) == 2


async def test_brain_rebuilds_vectors_when_the_index_model_fails(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    brain.add(title="Tipografia", text="font")
    await brain.search("font")
    brain.index.model = "openai/text-embedding-3-small"  # as if built with a provider now gone
    brain.add(title="Pizza", text="forno")
    hits = await brain.search("pizza forno")
    assert hits[0]["title"] == "Pizza" and brain.index.model == LOCAL
    assert len(brain.index.chunk_vec) == 2  # rebuilt, no duplicates


def _skill(dir, name, description, body):
    dir.mkdir(parents=True)
    (dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8")


async def test_skill_body_chunks_make_body_text_findable(tmp_path):
    from backend.skills import SkillLibrary

    _skill(tmp_path / "skills" / "hooks", "api-hardening", "Harden HTTP endpoints",
           "# Usage\n\nCheck the HMAC signature of every incoming webhook before trusting it.\n\n## Limits\n\nRate limit per client.")
    _skill(tmp_path / "skills" / "art", "hero-images", "Generate hero images", "# Usage\n\nWrite prompts for image models.")
    lib = SkillLibrary(tmp_path, Cfg({"skills": {"sources": ["skills"]}, "rag": {"minCosine": 0.25}}))
    await lib.reindex()
    query = "verify webhook signatures"
    assert lib.index.bm25.search(query, 5) == []  # body paragraphs are not BM25 fields
    hits = await lib.search(query, 5)
    assert hits[0]["name"] == "api-hardening" and hits[0]["cosine"] > 0.25
    summary = lib.summary()["vectors"]
    assert summary["model"] == LOCAL and summary["chunks"] >= 4  # header + body chunks, per skill
