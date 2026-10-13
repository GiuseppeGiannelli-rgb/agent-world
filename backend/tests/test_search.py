def test_bm25_ranks_by_relevance():
    from backend.search import Bm25

    idx = Bm25()
    idx.add("img", [{"text": "image prompting", "weight": 4}, {"text": "write prompts for image generation models"}])
    idx.add("sec", [{"text": "security review", "weight": 4}, {"text": "find XSS and injection in web code"}])
    assert idx.search("generate a hero image")[0]["id"] == "img"
    assert idx.search("controlla XSS injection")[0]["id"] == "sec"


def test_bm25_empty_query_returns_nothing():
    from backend.search import Bm25

    idx = Bm25()
    idx.add("a", [{"text": "hello world"}])
    assert idx.search("   ") == []


def test_tokenize_strips_accents_and_stopwords():
    from backend.search import tokenize

    assert tokenize("Più cose per una pizza") == ["cose", "pizza"]
