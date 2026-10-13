import json


class Bus:
    def __init__(self):
        self.events = []

    def emit(self, type, payload):
        self.events.append((type, payload))


def test_add_search_list_count(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    note = brain.add(title="Pizza tips", text="Use a hot oven for Neapolitan pizza", tags=["pizza"], team="research")
    assert note["title"] == "Pizza tips"
    assert len(note["id"]) == 8
    assert brain.count == 1
    hits = brain.search("neapolitan pizza oven")
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


def test_emits_bus_events(tmp_path):
    from backend.brain import Brain

    bus = Bus()
    brain = Brain(tmp_path / "brain.json", bus)
    brain.add(title="A", text="x", agent_id="sara")
    assert bus.events[0] == ("brain", {"op": "remember", "agentId": "sara", "count": 1, "note": brain.list(1)[0]})
    brain.search("x", agent_id="sara")
    assert bus.events[1][1]["op"] == "recall"


def test_search_quiet_suppresses_event(tmp_path):
    from backend.brain import Brain

    bus = Bus()
    brain = Brain(tmp_path / "brain.json", bus)
    brain.add(title="A", text="x")
    bus.events.clear()
    brain.search("x", quiet=True)
    assert bus.events == []


def test_tags_as_comma_string(tmp_path):
    from backend.brain import Brain

    brain = Brain(tmp_path / "brain.json")
    note = brain.add(title="A", text="x", tags="a, b ,c")
    assert note["tags"] == ["a", "b", "c"]
