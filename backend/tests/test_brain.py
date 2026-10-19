import json


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


async def test_add_search_list_count(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    note = brain.add(title="Pizza tips", text="Use a hot oven for Neapolitan pizza", tags=["pizza"], team="research")
    assert note["title"] == "Pizza tips"
    assert len(note["id"]) == 8
    assert brain.count == 1
    hits = await brain.search("neapolitan pizza oven")
    assert hits and hits[0]["id"] == note["id"]
    assert brain.list(10)[0]["id"] == note["id"]


def test_persists_to_disk_and_reloads(tmp_path):
    from backend.brain import Brain

    file = tmp_path / "brain.json"
    b1 = Brain(file)
    b1.add(title="A", text="first note")
    assert file.exists()
    b2 = Brain(file)
    assert b2.count == 1
    assert b2.list()[0]["title"] == "A"


def test_caps_at_5000_notes(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    # Pre-seed 5000 notes directly (skipping add()'s per-call reindex/save,
    # which is the very O(N^2) hotspot this spec flags for the Rust bridge --
    # exercising it 5000 times here would make this single test the slowest
    # thing in the suite for no extra coverage) and then exercise the real
    # add() path twice to prove the cap behavior itself.
    brain.notes = [{"id": f"n{i:04d}", "ts": i, "kind": "note", "title": f"n{i}", "text": "x", "tags": [], "team": None, "agentId": None, "runId": None} for i in range(5000)]
    brain.add(title="n5000", text="x")
    brain.add(title="n5001", text="x")
    assert brain.count == 5000
    assert brain.list(1)[0]["title"] == "n5001"  # the oldest were dropped


async def test_emits_bus_events(tmp_path):
    from backend.brain import Brain

    bus = Bus()
    brain = Brain(tmp_path / "brain.json", bus)
    brain.add(title="A", text="x", agent_id="sara")
    assert bus.events[0] == ("brain", {"op": "remember", "agentId": "sara", "count": 1, "note": brain.list(1)[0]})
    await brain.search("x", agent_id="sara")
    assert bus.events[1][1]["op"] == "recall"


async def test_search_quiet_suppresses_event(tmp_path):
    from backend.brain import Brain

    bus = Bus()
    brain = Brain(tmp_path / "brain.json", bus)
    brain.add(title="A", text="x")
    bus.events.clear()
    await brain.search("x", quiet=True)
    assert bus.events == []


def test_tags_as_comma_string(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    note = brain.add(title="A", text="x", tags="a, b ,c")
    assert note["tags"] == ["a", "b", "c"]


# ---------- spec 11 T03: consolidation and time decay ----------

DAY_MS = 86_400_000
LESSON = "Validate every form field on the server too, never trust the browser checks alone"


def _note(brain, *, title, text, kind="lesson", days_ago=0.0, run_id="r1", tags=None, team="qa", now_ms=1_800_000_000_000):
    n = brain.add(title=title, text=text, kind=kind, run_id=run_id, tags=tags or [], team=team)
    n["ts"] = int(now_ms - days_ago * DAY_MS)
    return n


async def test_consolidate_merges_near_duplicate_lessons_into_the_newest(tmp_path):
    from backend.brain import Brain

    bus = Bus()
    brain = Brain(tmp_path / "brain.json", bus)
    old = _note(brain, title="Form checks", text=LESSON, days_ago=20, run_id="r0", tags=["qa", "forms"])
    other = _note(brain, title="Hero images", text="Use real photos in the hero, never stock clip art", days_ago=10, run_id="r0")
    new = _note(brain, title="Form checks", text=LESSON, days_ago=0, run_id="r1", tags=["qa", "security"])
    bus.events.clear()
    removed = await brain.consolidate(run_id="r1")
    assert removed == 1
    assert [n["id"] for n in brain.notes] == [other["id"], new["id"]]
    survivor = brain.notes[-1]
    assert survivor["tags"] == ["qa", "security", "forms"] and survivor["repeats"] == 1
    assert bus.events == [("brain", {"op": "consolidate", "agentId": None, "count": 2, "removed": 1, "runId": "r1"})]
    hits = [h["id"] for h in await brain.search("form field server")]
    assert hits[0] == new["id"] and old["id"] not in hits  # the index forgot the old one
    assert [n["id"] for n in Brain(tmp_path / "brain.json").notes] == [other["id"], new["id"]]  # and the file


async def test_consolidate_keeps_what_is_only_similar_and_what_the_owner_wrote(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    _note(brain, title="Form checks", text=LESSON, days_ago=5, run_id="r0")
    _note(brain, title="Form checks", text=LESSON, kind="user", days_ago=4, run_id=None)  # the owner's own note
    _note(brain, title="Form checks", text=LESSON, kind="document", days_ago=3, run_id="r1")  # an owner's file
    _note(brain, title="Form checks", text=LESSON, kind="note", days_ago=2, run_id="r1")  # another kind
    _note(brain, title="Images", text="Compress every hero image under 200 KB before you ship the page", run_id="r1")
    assert await brain.consolidate(run_id="r1") == 0
    assert brain.count == 5


async def test_consolidate_threshold_is_strictly_above_the_config_value(tmp_path):
    from backend.brain import Brain
    from backend.embed import local_vectors
    from backend.search import cosine_top_k

    brain = Brain(tmp_path / "brain.json")
    a = _note(brain, title="Form checks", text=LESSON, days_ago=1, run_id="r0")
    b = _note(brain, title="Form checks", text=LESSON + " again", run_id="r1")
    va, vb = local_vectors([f"{a['title']}\n{a['text']}\n", f"{b['title']}\n{b['text']}\n"])
    cos = cosine_top_k(va, [vb], 1)[0][1]
    assert 0.88 < cos < 1.0, cos
    assert await brain.consolidate(run_id="r1", threshold=cos) == 0  # equal is not above
    assert await brain.consolidate(run_id="r1") == 1  # the shipped 0.88


async def test_consolidate_without_a_run_looks_at_every_note(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    _note(brain, title="Form checks", text=LESSON, days_ago=3, run_id="r0")
    _note(brain, title="Form checks", text=LESSON, days_ago=2, run_id="r1")
    _note(brain, title="Form checks", text=LESSON, days_ago=1, run_id="r2")
    assert await brain.consolidate(run_id="r9") == 0  # no note of that run: nothing to compare
    assert await brain.consolidate() == 2
    assert brain.count == 1 and brain.notes[0]["repeats"] == 2


async def test_consolidate_keeps_the_vectors_of_the_untouched_notes(tmp_path):
    """No embedding call for what did not change: with a provider model every
    vector is a paid call (spec 05); only the survivor, whose tags changed, is
    embedded again."""
    from backend.brain import Brain
    from backend.embed import local_vectors

    calls = []

    class CountingEmbedder:
        rag = {}

        async def embed(self, texts, model=None):
            calls.append(len(texts))
            return "local/ngram", local_vectors(texts)

    brain = Brain(tmp_path / "brain.json", embedder=CountingEmbedder())
    for i in range(4):
        _note(brain, title=f"Other {i}", text=f"Unrelated lesson number {i} about colours and fonts", run_id="r0", days_ago=5)
    _note(brain, title="Form checks", text=LESSON, days_ago=3, run_id="r0", tags=["a"])
    _note(brain, title="Form checks", text=LESSON, run_id="r1", tags=["b"])
    await brain.search("fonts")
    assert calls == [6, 1]  # the notes, then the query
    assert await brain.consolidate(run_id="r1") == 1
    await brain.search("fonts")
    assert calls == [6, 1, 1, 1]  # the survivor, then the query


def test_time_decay_spares_the_owner_and_halves_at_the_half_life(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    now = 1_800_000_000_000 / 1000
    lesson = {"kind": "lesson", "ts": int(now * 1000 - 30 * DAY_MS)}
    assert brain.decay(lesson, now) == 0.75  # floor 0.5 + 0.5 * 0.5 at 30 days
    assert brain.decay({**lesson, "ts": int(now * 1000)}, now) == 1.0
    assert abs(brain.decay({**lesson, "ts": int(now * 1000 - 3650 * DAY_MS)}, now) - 0.5) < 1e-9  # never below the floor
    for kind in ("user", "document"):
        assert brain.decay({**lesson, "kind": kind}, now) == 1.0
    assert brain.decay({"ts": lesson["ts"]}, now) == 0.75  # a note saved before "kind" existed is an agent note


async def test_a_recent_lesson_overtakes_an_older_better_match(tmp_path):
    """The decay multiplies the fused RRF score before the cut to k: the old
    lesson matches better (the words are in its title), the recent one wins."""
    from backend.brain import Brain
    from backend.embed import local_vectors

    class Embedder:  # rag.brain is read at every search, like the app's config
        rag = {}

        async def embed(self, texts, model=None):
            return "local/ngram", local_vectors(texts)

    embedder = Embedder()
    brain = Brain(tmp_path / "brain.json", embedder=embedder)
    brain.clock = lambda: 1_800_000_000
    old = _note(brain, title="Server validation of forms", text="Check the input on the server", days_ago=365)
    new = _note(brain, title="Checks", text="Repeat the form validation on the server side", days_ago=0)
    embedder.rag = {"brain": {"halfLifeDays": 0}}  # decay off
    assert [h["id"] for h in await brain.search("server validation forms", k=1)] == [old["id"]]
    embedder.rag = {}  # the shipped settings
    assert [h["id"] for h in await brain.search("server validation forms", k=1)] == [new["id"]]


def test_the_shipped_settings(tmp_path):
    import json

    from backend.app import ROOT

    rag = json.loads((ROOT / "config" / "default.json").read_text(encoding="utf-8"))["rag"]
    assert rag["brain"] == {"dedupeCosine": 0.88, "halfLifeDays": 30, "decayFloor": 0.5}


async def test_a_run_consolidates_its_own_notes_when_it_ends(demo_ctx, monkeypatch):
    import asyncio

    from backend.run import Run

    seen = []
    real = demo_ctx.brain.consolidate

    async def spy(**kw):
        seen.append((kw, sorted({n["kind"] for n in demo_ctx.brain.notes})))
        return await real(**kw)

    monkeypatch.setattr(demo_ctx.brain, "consolidate", spy)
    run = Run(goal="Una landing page per il bar con immagini", ctx=demo_ctx)
    await asyncio.wait_for(run.start(), timeout=120)
    assert run.data["status"] == "completed"
    assert len(seen) == 1 and seen[0][0] == {"run_id": run.data["id"]}
    assert "run" in seen[0][1]  # after the mission note: the whole run is in


async def test_a_failing_consolidation_never_fails_the_run(demo_ctx, monkeypatch):
    import asyncio

    from backend.run import Run

    async def boom(**kw):
        raise RuntimeError("embedding provider down")

    monkeypatch.setattr(demo_ctx.brain, "consolidate", boom)
    run = Run(goal="Un documento di ricerca", ctx=demo_ctx)
    await asyncio.wait_for(run.start(), timeout=120)
    assert run.data["status"] == "completed"


from test_run import demo_ctx  # noqa: E402, F401 -- the full demo context (tests/ is on sys.path)
