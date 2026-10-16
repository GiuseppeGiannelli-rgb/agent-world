"""N14: the demo provider speaks the run's language. It reads the language
rule every system prompt carries (prompts.language_rule, spec 06), so no
prompt sent to a real model changes; with no language chosen it answers in
English, the project's default (D2). Its texts live in router/mock_texts.py,
one table per language with the shape of the English one (D3)."""

import json
import re
import string

import pytest

from backend.i18n import DEFAULT, LANGUAGES
from backend.prompts import LEGACY_LANGUAGE, language_rule
from backend.router import mock

ALL = list(LANGUAGES)


def _texts():
    from backend.router.mock_texts import MOCK_TEXTS

    return MOCK_TEXTS


def _fields(s: str) -> list[str]:
    return sorted(f for _, f, _, _ in string.Formatter().parse(s) if f)


def _shape(v):
    """The structure a translation must keep: keys, list lengths, placeholders."""
    if isinstance(v, dict):
        return {k: _shape(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_shape(x) for x in v]
    return _fields(v)


def _leaves(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _leaves(x)
    elif isinstance(v, list):
        for x in v:
            yield from _leaves(x)
    else:
        yield v


def _msgs(marker: str, lang: str | None, user: str = "") -> list[dict]:
    rule = language_rule(lang) if lang else LEGACY_LANGUAGE
    return [{"role": "system", "content": f"[[role:{marker}]]\nYou are Test, the tester.\n{rule}"}, {"role": "user", "content": user}]


# ---------- the tables ----------


def test_one_table_per_language_with_the_english_shape():
    t = _texts()
    assert list(t) == ALL
    english = _shape(t["en"])
    for lang in ALL:
        assert _shape(t[lang]) == english, lang


@pytest.mark.parametrize("lang", [x for x in ALL if x != "en"])
def test_every_table_is_really_translated(lang):
    t = _texts()
    en, other = list(_leaves(t["en"])), list(_leaves(t[lang]))
    same = [a for a, b in zip(en, other) if a == b]
    assert len(same) <= 0.15 * len(en), same


# ---------- the language of the run ----------


@pytest.mark.parametrize("lang", ALL)
def test_language_of_reads_the_rule(lang):
    assert mock.language_of(_msgs("planner", lang)[0]["content"]) == lang


def test_with_no_language_chosen_the_mock_speaks_english():
    assert mock.language_of(_msgs("planner", None)[0]["content"]) is None
    plan = json.loads(mock.answer("planner", _msgs("planner", None, "GOAL:\nA research document"), ""))
    assert plan["summary"] == _texts()[DEFAULT]["plan_simple"]


# ---------- the same mission in every language ----------

# the same two goals, written in each language (each one is web/complex/visual/voice
# or document/complex/visual/voice only through its own words)
GOALS = {
    "web": {
        "en": "The complete launch website for a bakery, with images and a voice-over",
        "it": "Il sito completo per il lancio di una panetteria, con immagini e una voce narrante",
        "es": "El sitio web completo para el lanzamiento de una panadería, con imágenes y una voz en off",
        "fr": "Le site web complet pour le lancement d'une boulangerie, avec des images et une voix off",
        "de": "Die komplette Website zum Start einer Bäckerei, mit Bildern und einer Sprecherstimme",
    },
    "simple-web": {
        "en": "A website for my bakery, with images",
        "it": "Un sito per la mia panetteria, con immagini",
        "es": "Un sitio web para mi panadería, con imágenes",
        "fr": "Un site web pour ma boulangerie, avec des images",
        "de": "Eine Webseite für meine Bäckerei, mit Bildern",
    },
    # short (under 80 characters): complex only through the word "complete"
    "complete-web": {
        "en": "A complete web page for my bakery",
        "it": "Una pagina web completa per la mia panetteria",
        "es": "Una página web completa para mi panadería",
        "fr": "Une page web complète pour ma boulangerie",
        "de": "Eine komplette Webseite für meine Bäckerei",
    },
    "document": {
        "en": "A complete study on composting, with cover images and a voice-over",
        "it": "Uno studio completo sul compostaggio, con immagini di copertina e una voce narrante",
        "es": "Un estudio completo sobre el compostaje, con imágenes de portada y una voz en off",
        "fr": "Une étude complète sur le compostage, avec des images de couverture et une voix off",
        "de": "Eine vollständige Studie über Kompostierung, mit Titelbildern und einer Sprecherstimme",
    },
}


def _plan_shape(plan):
    return (plan["complexity"], tuple((w["team"], tuple(w["deliverables"]), tuple(w["dependsOn"])) for w in plan["workstreams"]))


@pytest.mark.parametrize("kind", list(GOALS))
def test_the_same_goal_makes_the_same_plan_in_every_language(kind):
    shapes = {lang: _plan_shape(mock.ceo_plan(goal, lang)) for lang, goal in GOALS[kind].items()}
    assert len(set(shapes.values())) == 1, shapes
    teams = [t for t, *_ in shapes["en"][1]]
    if kind == "web":
        assert shapes["en"][0] == "complex" and "dev" in teams and "prompt" in teams and teams.count("genai") == 2
    elif kind == "simple-web":
        assert shapes["en"][0] == "simple" and "dev" in teams and teams.count("genai") == 1 and "prompt" not in teams
    elif kind == "complete-web":
        assert all(len(g) <= 80 for g in GOALS[kind].values())
        assert shapes["en"][0] == "complex" and "dev" in teams and "prompt" in teams
    else:
        assert "dev" not in teams and teams.count("genai") == 2


@pytest.mark.parametrize("lang", ALL)
def test_the_plan_is_written_in_the_run_language(lang):
    t = _texts()[lang]
    plan = json.loads(mock.answer("planner", _msgs("planner", lang, f"GOAL:\n{GOALS['web'][lang]}"), ""))
    assert plan["summary"] == t["plan_complex"]
    assert [w["title"] for w in plan["workstreams"]][:3] == [t["ws"]["web_research"]["title"], t["ws"]["web_design"]["title"], t["ws"]["web_content"]["title"]]


# ---------- every role ----------


@pytest.mark.parametrize("lang", ALL)
def test_every_role_answers_in_the_run_language(lang):
    t = _texts()[lang]
    # lead: a single deliverable becomes angles plus a final integration
    lead = json.loads(mock.answer("lead", _msgs("lead", lang, "WORKSTREAM ID: w1\nWORKSTREAM TEAM: research\nWORKSTREAM: X\nDELIVERABLES: research/notes.md"), "research"))
    assert [s["title"] for s in lead["subtasks"]] == [*t["angles"]["research"], t["final_title"]]
    # worker: its first thought, then the markdown it writes
    brief = "GOAL: g\nTASK ID: w1.1\nTASK: Notes\nOUTPUTS: notes/a.md\nSKILLS: none\nPROJECT FILES:\n(empty folder)"
    worker = _msgs("tasker:research", lang, brief)
    first = json.loads(mock.answer("tasker", worker, "research"))
    assert first["thought"] == t["thoughts"]["list"]
    steps = [json.loads(mock.answer("tasker", worker + [{"role": "assistant", "content": "{}"}] * k, "research")) for k in range(8)]
    written = next(s["args"]["content"] for s in steps if s["tool"] == "write_file")
    assert f"## {t['md']['key_points']}" in written
    assert steps[-1]["tool"] == "finish" and steps[-1]["thought"] == t["thoughts"]["finish"]
    # QA: a revision on attempt 1 for this task (fixed by the hash)
    verdicts = [json.loads(mock.answer("judge", _msgs("judge", lang, f"GOAL: g\nTASK ID: w{i}.1\nATTEMPT: 1\nTEAM: dev"), "")) for i in range(1, 12)]
    revise = [v for v in verdicts if v["verdict"] == "revise"]
    assert revise and all(v["feedback"] == t["judge"]["feedback"] for v in revise)
    # the final report, the chat, the prompt lab, the lead's help
    report = mock.answer("synth", _msgs("synth", lang, "GOAL: g\nWORKSTREAMS:\n- w1\n\nPROJECT FILES:\nindex.html (10 B)"), "")
    assert report.startswith(f"# {t['report']['title']}\n")
    assert mock.answer("chat", _msgs("chat", lang, "?"), "") in (t["chat"]["question"].format(name="Test"), t["chat"]["ack"].format(name="Test"))
    assert json.loads(mock.answer("prompteng", _msgs("prompteng", lang, "TASK: T"), ""))["pitfalls"] == t["prompteng"]["pitfalls"]
    assert mock.answer("advisor", _msgs("advisor", lang), "") == t["advisor"]
    assert json.loads(mock.answer("rescue", _msgs("rescue", lang), ""))["guidance"] == t["rescue"]
    assert json.loads(mock.answer("librarian", _msgs("librarian", lang, "CANDIDATES:\n- id: a | A: x"), ""))["picks"][0]["why"] == t["librarian_why"]


@pytest.mark.parametrize("lang", ALL)
def test_the_page_it_builds_declares_and_speaks_the_language(lang):
    t = _texts()[lang]
    page = mock.html("Una pagina", [], lang)
    assert f'<html lang="{lang}">' in page
    assert t["page"]["services"] in page and t["page"]["footer"] in page


def test_the_english_table_has_no_italian_left():
    # Italian-only words ("per" is English too: "one prompt per image")
    italian = re.compile(r"[àèìòù]|\b(il|della|sono|non|con|che|gli|una)\b", re.IGNORECASE)
    assert [s for s in _leaves(_texts()["en"]) if italian.search(s)] == []
