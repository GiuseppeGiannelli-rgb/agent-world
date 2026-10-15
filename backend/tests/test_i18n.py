"""Spec 06: the backend's own texts (run messages, speech bubbles, errors,
Brain titles) in every supported language, English first and by default.
The tables must stay in lockstep: a key missing from one language would
crash a run halfway."""

import re
import string

import pytest

from backend.app import ROOT

ALL = {"en", "it", "es", "fr", "de"}


def _fields(template: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def test_five_languages_english_first_and_default():
    from backend.i18n import DEFAULT, LANGUAGES

    assert set(LANGUAGES) == ALL
    assert next(iter(LANGUAGES)) == "en" and DEFAULT == "en"
    assert LANGUAGES == {"en": "English", "it": "Italian", "es": "Spanish", "fr": "French", "de": "German"}


def test_same_keys_and_placeholders_in_every_language():
    from backend.i18n import LANGUAGES, MESSAGES

    assert set(MESSAGES) == set(LANGUAGES)
    keys = set(MESSAGES["en"])
    assert keys, "the English table is empty"
    for lang, table in MESSAGES.items():
        assert set(table) == keys, f"{lang}: {sorted(set(table) ^ keys)}"
        for k in keys:
            assert _fields(table[k]) == _fields(MESSAGES["en"][k]), f"{lang}.{k}"


@pytest.mark.parametrize("lang", ["it", "es", "fr", "de"])
def test_every_table_is_really_translated(lang):
    from backend.i18n import MESSAGES

    # a copy of the English table would pass the key check: allow only the
    # few texts that are the same word in both languages ("Mission · {goal}")
    same = [k for k, v in MESSAGES[lang].items() if v == MESSAGES["en"][k]]
    assert len(same) <= 3, same


def test_tr_formats_and_defaults_to_english():
    from backend.i18n import MESSAGES, tr

    key = "resumed"
    assert tr("it", key) == MESSAGES["it"][key]
    assert tr("de", key) == MESSAGES["de"][key]
    assert tr(None, key) == MESSAGES["en"][key]  # no language chosen: the default, English
    assert "w3" in tr("fr", "ws_done", id="w3", title="Site")


@pytest.mark.parametrize("bad", ["xx", "EN", "", 3])
def test_tr_rejects_an_unknown_language(bad):
    from backend.i18n import tr

    with pytest.raises(ValueError):
        tr(bad, "resumed")


def test_english_table_has_no_italian_left():
    from backend.i18n import MESSAGES

    italian = re.compile(r"[àèéìòù]|\b(il|della|sono|non|per|con|che)\b", re.IGNORECASE)
    leftovers = {k: v for k, v in MESSAGES["en"].items() if italian.search(v)}
    assert not leftovers


def test_team_label_translates_known_teams_and_falls_back_to_config():
    from backend.i18n import team_label

    cfg = {"teams": {"research": {"label": "Ricerca"}, "custom": {"label": "Su misura"}}}
    assert team_label(cfg, "research", "en") == "Research"
    assert team_label(cfg, "research", "es") == "Investigación"
    assert team_label(cfg, "research", "fr") == "Recherche"
    assert team_label(cfg, "research", "de") == "Recherche"
    assert team_label(cfg, "research", "it") == "Ricerca"  # Italian: the config label (D3)
    assert team_label(cfg, "research", None) == "Research"  # the default language
    assert team_label(cfg, "custom", "de") == "Su misura"  # D3: config label as fallback
    assert team_label(cfg, "ghost", "en") == "ghost"


def test_every_language_names_every_team():
    from backend.i18n import LANGUAGES, TEAM_LABELS

    teams = set(TEAM_LABELS["en"])
    for lang in set(LANGUAGES) - {"it"}:
        assert set(TEAM_LABELS[lang]) == teams, lang


def test_frontend_and_backend_offer_the_same_languages():
    """The UI builds its selectors from LANGS in i18n.js; the backend refuses
    any code outside LANGUAGES. A language in only one of them would be a
    choice that fails with a 400, or one nobody can pick."""
    from backend.i18n import LANGUAGES

    js = (ROOT / "public" / "js" / "i18n.js").read_text(encoding="utf-8")
    m = re.search(r"export const LANGS = \{([^}]*)\}", js)
    assert m, "LANGS not found in i18n.js"
    codes = re.findall(r"(\w+):\s*'", m.group(1))
    assert codes == list(LANGUAGES)  # same codes, same order (English first)
