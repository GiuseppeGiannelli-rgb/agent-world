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


# ---------- spec 11 T03: the tokens of code and of every script ----------
# Before T03 the tokens were [a-z0-9] only: an identifier fell apart
# (budget_gate -> budget, gate) and Greek, Cyrillic, Devanagari or CJK text
# gave no token at all (measured on f66d1d7..2a47b88).

CODE_AND_SCRIPTS = [
    ("def run_command(cmd): budget_gate()", ["def", "run_command", "run", "command", "cmd", "budget_gate", "budget", "gate"]),
    ("use std::collections::HashMap;", ["use", "std::collections::hashmap", "std", "collections", "hashmap"]),
    ('@pytest.fixture @app.get("/api")', ["@pytest", "pytest", "fixture", "@app", "app", "get", "api"]),
    ("user@example.com", ["user@example", "user", "example", "com"]),
    ("__init__ self._in_flight", ["__init__", "init", "self", "_in_flight", "flight"]),
    ("foo:::bar @@baz qux@ ::lead", ["foo", "bar", "@baz", "baz", "qux", "lead"]),
    ("ΟΔΟΣ λόγος", ["οδοσ", "λογοσ"]),
    ("Привет мир сервер", ["привет", "мир", "сервер"]),
    ("हिन्दी भाषा", ["हिन्दी", "भाषा"]),
    ("数据库很快 東京", ["数据库很快"]),
    ("smørrebrød Straße", ["smørrebrød", "straße"]),
    ("İstanbul ŞEHİR", ["istanbul", "sehir"]),
]


def test_tokenize_keeps_code_tokens_and_every_script():
    from backend.search import tokenize

    for text, want in CODE_AND_SCRIPTS:
        assert tokenize(text) == want, text


def test_tokenize_folds_the_final_sigma_and_the_case():
    # Python lowers a final capital sigma to "ς" and Rust (char by char) to "σ":
    # both fold to "σ", so the two implementations and the two spellings agree
    from backend.search import tokenize

    assert tokenize("λόγος") == tokenize("ΛΌΓΟΣ") == tokenize("λογοσ") == ["λογοσ"]


def test_tokenize_counts_characters_not_bytes():
    from backend.search import tokenize

    assert tokenize("東京 数据库 мир ab_") == ["数据库", "мир", "ab_"]  # 2 chars out, 3 chars in


def test_the_ascii_path_and_the_scanner_never_disagree():
    """search.tokenize reads plain-ASCII chunks with a regex and the rest with
    the scanner (measured: 1.45x the old regex instead of 3.6x). On ASCII text
    the two must give the same tokens, for any mix of the joiners."""
    import random

    from backend.search import _ASCII_TOKEN, _scan

    rng = random.Random(1103)
    alphabet = "ab9_:@ x."
    for _ in range(3000):
        s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 14)))
        assert _ASCII_TOKEN.findall(s) == _scan(s), repr(s)


def test_an_identifier_finds_its_own_document_first():
    from backend.search import Bm25

    idx = Bm25()
    idx.add("words", [{"text": "the budget of a run and the gate of the office"}])
    idx.add("code", [{"text": "budget_gate() holds a slot for every call"}])
    assert [h["id"] for h in idx.search("budget_gate")] == ["code", "words"]
    assert idx.search("gate budget")  # the words still find both


def test_a_query_in_another_script_finds_its_document():
    from backend.search import Bm25

    idx = Bm25()
    idx.add("ru", [{"text": "Сервер отвечает на запросы"}])
    idx.add("el", [{"text": "Ο λόγος της απόφασης"}])
    idx.add("en", [{"text": "The server answers requests"}])
    assert idx.search("сервер")[0]["id"] == "ru"
    assert idx.search("ΛΟΓΟΣ")[0]["id"] == "el"


def test_local_vectors_take_every_script():
    from backend.embed import dot, ngram_vector

    greek, greek_caps, russian = ngram_vector("ο λόγος"), ngram_vector("Ο ΛΌΓΟΣ"), ngram_vector("сервер отвечает")
    assert greek == greek_caps
    assert any(russian) and abs(dot(russian, russian) - 1.0) < 1e-9
    assert dot(ngram_vector("budget_gate"), ngram_vector("budget gate")) > 0.5  # the parts are in the vector
    # different words stay apart: grams that lost their letters would all look alike
    assert dot(ngram_vector("сервер"), ngram_vector("запрос")) < 0.5
    assert dot(ngram_vector("λόγος"), ngram_vector("δρόμος")) < 0.5


def test_local_vectors_hash_the_utf8_bytes_of_each_gram():
    """The hash aw_core.ngram_vector reproduces: CRC-32 of the UTF-8 bytes of
    "w:<token>" and of the 3- and 4-character grams of " <token> "."""
    import zlib

    from backend.embed import ngram_vector, normalize

    want = [0.0] * 64
    padded = " мир "
    for g in ["w:мир", *(padded[i : i + n] for n in (3, 4) for i in range(len(padded) - n + 1))]:
        h = zlib.crc32(g.encode("utf-8"))
        want[h % 64] += -1.0 if h & 0x80000000 else 1.0
    assert ngram_vector("Мир", 64) == normalize(want)
