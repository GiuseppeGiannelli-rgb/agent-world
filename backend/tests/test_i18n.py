"""Spec 06: the backend's own texts (run messages, speech bubbles, errors,
Brain titles) in Italian and English. The two tables must stay in lockstep:
a key missing from one language would crash a run halfway."""

import re
import string

import pytest


def _fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def test_same_keys_and_placeholders_in_every_language():
    from backend.i18n import LANGUAGES, MESSAGES

    assert set(MESSAGES) == set(LANGUAGES) == {"it", "en"}
    keys = set(MESSAGES["it"])
    assert keys, "the Italian table is empty"
    for lang, table in MESSAGES.items():
        assert set(table) == keys, f"{lang}: {sorted(set(table) ^ keys)}"
        for k in keys:
            assert _fields(table[k]) == _fields(MESSAGES["it"][k]), f"{lang}.{k}"


def test_tr_formats_and_defaults_to_italian():
    from backend.i18n import MESSAGES, tr

    key = "resumed"
    assert tr("en", key) == MESSAGES["en"][key]
    assert tr(None, key) == MESSAGES["it"][key]  # D2: no language -> the old Italian texts
    assert "w3" in tr("en", "ws_done", id="w3", title="Sito")


def test_tr_rejects_an_unknown_language():
    from backend.i18n import tr

    with pytest.raises(ValueError):
        tr("fr", "resumed")


def test_english_table_has_no_italian_left():
    from backend.i18n import MESSAGES

    italian = re.compile(r"[àèéìòù]|\b(il|della|sono|non|per|con|che)\b", re.IGNORECASE)
    leftovers = {k: v for k, v in MESSAGES["en"].items() if italian.search(v)}
    assert not leftovers


def test_team_label_translates_known_teams_and_falls_back_to_config():
    from backend.i18n import team_label

    cfg = {"teams": {"research": {"label": "Ricerca"}, "custom": {"label": "Su misura"}}}
    assert team_label(cfg, "research", "en") == "Research"
    assert team_label(cfg, "research", "it") == "Ricerca"
    assert team_label(cfg, "research", None) == "Ricerca"
    assert team_label(cfg, "custom", "en") == "Su misura"  # D3: config label as fallback
    assert team_label(cfg, "ghost", "en") == "ghost"
