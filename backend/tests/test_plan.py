"""Mirrors scenario 8 of scripts/router-test.js: plan normalisation --
unknown teams mapped, cycles broken, unsafe paths dropped."""


def test_plan_and_subtask_normalisation():
    from backend.plan import normalize_plan, normalize_subtasks

    cfg = {
        "teams": {
            "research": {"kind": "work", "lead": {}},
            "dev": {"kind": "work", "lead": {}},
            "content": {"kind": "work", "lead": {}},
            "qa": {"kind": "service", "lead": {}},
        },
        "limits": {"maxWorkstreams": 8, "maxSubtasks": 5},
    }
    plan = normalize_plan(
        {
            "complexity": "complex",
            "summary": "s",
            "workstreams": [
                {"id": "a", "title": "A", "team": "developer", "deliverables": ["../evil.txt", "ok/file.md", "C:/x"], "dependsOn": ["b"]},
                {"id": "b", "title": "B", "team": "copywriter", "dependsOn": ["a"]},
                {"id": "c", "title": "C", "team": "qa", "dependsOn": ["a", "zzz"]},
            ],
        },
        cfg,
    )
    assert plan["complexity"] == "complex"
    assert plan["workstreams"][0]["team"] == "dev"
    assert plan["workstreams"][1]["team"] == "content"
    assert plan["workstreams"][2]["team"] == "dev", "service teams cannot own workstreams"
    assert plan["workstreams"][0]["deliverables"] == ["ok/file.md"]

    ids = {t["id"]: t for t in plan["workstreams"]}
    visiting = set()

    def acyclic(id):
        if id in visiting:
            return False
        visiting.add(id)
        ok = all(acyclic(d) for d in ids[id]["dependsOn"])
        visiting.discard(id)
        return ok

    assert all(acyclic(t["id"]) for t in plan["workstreams"])

    subs = normalize_subtasks(
        {"subtasks": [{"id": "x", "title": "X", "outputs": ["a.md"]}, {"id": "y", "title": "Y", "dependsOn": ["x"]}]},
        {"id": "w1", "team": "dev", "deliverables": ["a.md", "b.md"]},
        cfg,
    )
    assert [t["id"] for t in subs] == ["w1.1", "w1.2"]
    assert subs[1]["dependsOn"] == ["w1.1"]
    assert "b.md" in subs[1]["outputs"], "orphan deliverables go to the last subtask"


def test_normalize_plan_rejects_empty_workstreams():
    from backend.plan import normalize_plan

    import pytest

    with pytest.raises(ValueError):
        normalize_plan({"workstreams": []}, {"teams": {}, "limits": {"maxWorkstreams": 8}})


def test_slugify_strips_accents_and_punctuation():
    from backend.plan import slugify

    assert slugify("Pizzeria à Milano!") == "pizzeria-a-milano"
    assert slugify("") == "progetto"


def test_safe_rel_path_rejects_traversal_and_absolute():
    from backend.plan import safe_rel_path

    assert safe_rel_path("ok/file.md") == "ok/file.md"
    assert safe_rel_path("../evil.txt") is None
    assert safe_rel_path("C:/x") is None
    assert safe_rel_path("a\\b.md") == "a/b.md"
