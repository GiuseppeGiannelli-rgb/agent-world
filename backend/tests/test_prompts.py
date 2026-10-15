"""Contract tests for backend/prompts.py. The demo provider (router/mock.py)
parses these prompts by field name and [[role:...]] marker, so the tests
verify the text with mock.py's own parsers -- a prompt the mock cannot read
is a broken prompt, even if it looks fine to a human."""

from backend.router import mock

CFG = {
    "limits": {"maxWorkstreams": 8, "maxSubtasks": 5, "allowShell": False},
    "teams": {
        "research": {"label": "Ricerca", "title": "Researcher", "kind": "work", "combo": "fast", "maxSubAgents": 3, "brief": "Finds facts on the web.", "tools": ["web_search", "web_fetch"], "lead": {"id": "rino", "name": "Rino"}, "workers": [{"id": "sara", "name": "Sara"}]},
        "dev": {"label": "Sviluppo", "title": "Engineer", "kind": "work", "combo": "smart", "maxSubAgents": 3, "brief": "Writes working code.", "tools": ["run_command"], "lead": {"id": "leo", "name": "Leo"}, "workers": []},
        "qa": {"label": "Qualità e Sicurezza", "title": "QA", "kind": "service", "combo": "smart", "brief": "Reviews.", "tools": [], "lead": {"id": "bruno", "name": "Bruno"}, "workers": []},
        "skills": {"label": "Skill Hub", "title": "Librarian", "kind": "service", "combo": "fast", "brief": "Hands out skills.", "tools": [], "lead": None, "workers": []},
    },
}

WS = {"id": "w2", "team": "research", "title": "Ricerca e requisiti", "objective": "Capire il pubblico.", "deliverables": ["research/notes.md", "research/sources.md"], "acceptance": ["Pubblico chiaro", "3 riferimenti"], "dependsOn": []}
TASK = {"id": "w2.1", "wsId": "w2", "team": "research", "title": "Analisi del pubblico", "description": "Descrivi il pubblico.", "acceptance": ["Almeno 3 segmenti"], "outputs": ["notes/pubblico.md"], "dependsOn": [], "brief": "", "pitfalls": [], "skills": []}


def test_tool_docs_cover_exactly_the_node_set():
    from backend.prompts import TOOL_DOCS

    assert set(TOOL_DOCS) == {
        "list_files", "read_file", "write_file", "web_search", "web_fetch", "run_command",
        "generate_image", "generate_speech", "search_skills", "read_skill", "remember",
        "recall", "ask_lead", "ask_user", "finish",
    }


def test_tools_for_order_dedup_and_shell_filter():
    from backend.prompts import tools_for

    assert tools_for(CFG, "research") == [
        "list_files", "read_file", "write_file", "web_search", "web_fetch",
        "search_skills", "read_skill", "recall", "remember", "ask_lead", "ask_user", "finish",
    ]
    # run_command is dropped while allowShell is false, even if the team asks for it
    assert "run_command" not in tools_for(CFG, "dev")
    with_shell = {**CFG, "limits": {**CFG["limits"], "allowShell": True}}
    assert "run_command" in tools_for(with_shell, "dev")
    # unknown team: just the base tools
    assert tools_for(CFG, "nope") == ["list_files", "read_file", "write_file", "search_skills", "read_skill", "recall", "remember", "ask_lead", "ask_user", "finish"]


def test_work_teams_filters_service_and_leadless():
    from backend.prompts import work_teams

    assert work_teams(CFG) == ["research", "dev"]


def test_ceo_plan_prompt_is_readable_by_the_mock():
    from backend.prompts import ceo_plan_prompt

    msgs = ceo_plan_prompt(cfg=CFG, ceo={"name": "Ada"}, goal="Un sito per il mio bar", memory="- lezione vecchia")
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert msgs[0]["content"].startswith("[[role:planner]]")
    assert mock.block(msgs[1]["content"], "GOAL") == "Un sito per il mio bar"
    assert "- research (Ricerca;" in mock.block(msgs[1]["content"], "TEAMS")
    assert "lezione vecchia" in msgs[1]["content"]


def test_lead_plan_prompt_fields():
    from backend.prompts import lead_plan_prompt

    msgs = lead_plan_prompt(cfg=CFG, lead={"name": "Rino"}, team="research", goal="Un sito", ws=WS, upstream=["w1 done"])
    assert msgs[0]["content"].startswith("[[role:lead]]")
    user = msgs[1]["content"]
    assert mock.field(user, "WORKSTREAM ID") == "w2"
    assert mock.field(user, "WORKSTREAM TEAM") == "research"
    assert mock.field(user, "WORKSTREAM") == "Ricerca e requisiti"
    assert mock.csv(mock.field(user, "DELIVERABLES")) == ["research/notes.md", "research/sources.md"]


def test_librarian_prompt_candidates_match_the_mock_regex():
    import re

    from backend.prompts import librarian_prompt

    candidates = [{"id": "skills/a", "name": "Alpha", "description": "Does things"}, {"id": "skills/b", "name": "Beta", "description": "Does more"}]
    msgs = librarian_prompt(librarian={"name": "Otto"}, goal="g", task=TASK, candidates=candidates, per_task=2)
    assert msgs[0]["content"].startswith("[[role:librarian]]")
    ids = [m.group(1) for m in re.finditer(r"^- id: (\S+) \|", msgs[1]["content"], re.MULTILINE)]
    assert ids == ["skills/a", "skills/b"]


def test_prompt_eng_prompt_fields():
    from backend.prompts import prompt_eng_prompt

    msgs = prompt_eng_prompt(pe={"name": "Pia"}, goal="g", task=TASK, team="Ricerca", skills=["Alpha"])
    assert msgs[0]["content"].startswith("[[role:prompteng]]")
    assert mock.field(msgs[1]["content"], "TASK") == "Analisi del pubblico"
    assert mock.field(msgs[1]["content"], "TASK ID") == "w2.1"


def test_tasker_system_marks_role_and_lists_tools():
    from backend.prompts import tasker_system

    sys = tasker_system(agent={"name": "Sara", "kind": "worker", "team": "research"}, team_cfg=CFG["teams"]["research"], lead={"name": "Rino"}, tools=["list_files", "finish"], skills_text="### Alpha\nbody")
    assert sys.startswith("[[role:tasker:research]]")
    assert "- list_files" in sys and "- finish" in sys
    assert "ASSIGNED SKILLS" in sys
    bare = tasker_system(agent={"name": "Sub 1", "kind": "sub", "team": "research"}, team_cfg=CFG["teams"]["research"], lead={"name": "Rino"}, tools=["finish"], skills_text="")
    assert "ASSIGNED SKILLS" not in bare
    assert "sub-agent spawned by Rino" in bare


def test_tasker_brief_fields_feed_the_mock_worker():
    from backend.prompts import tasker_brief

    task = {**TASK, "skills": [{"name": "Alpha"}], "brief": "Sii concreto", "pitfalls": ["Niente segnaposti"]}
    inputs = [{"id": "w1.1", "title": "Note", "agent": "Sara", "summary": "Fatto", "files": ["research/notes.md"]}]
    user = tasker_brief(goal="Un sito", ws=WS, task=task, inputs=inputs, files="research/notes.md (210 B)", memory="- usa le fonti")
    assert mock.field(user, "GOAL") == "Un sito"
    assert mock.field(user, "TASK ID") == "w2.1"
    assert mock.field(user, "TASK") == "Analisi del pubblico"
    assert mock.csv(mock.field(user, "OUTPUTS")) == ["notes/pubblico.md"]
    assert mock.csv(mock.field(user, "SKILLS")) == ["Alpha"]
    assert "  files: research/notes.md" in user  # the mock's `files:` line regex needs this exact shape
    assert "research/notes.md (210 B)" in user
    assert "BRIEF FROM THE PROMPT LAB" in user and "Niente segnaposti" in user


def test_judge_prompt_fields_and_security_toggle():
    from backend.prompts import judge_prompt

    msgs = judge_prompt(judge={"name": "Bruno"}, goal="g", task=TASK, attempt=2, summary="fatto", file_dump="=== a ===", checks="ok", security=True)
    assert msgs[0]["content"].startswith("[[role:judge]]")
    assert "Security review" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert mock.field(user, "TASK ID") == "w2.1"
    assert mock.field(user, "ATTEMPT") == "2"
    assert mock.field(user, "TEAM") == "research"
    safe = judge_prompt(judge={"name": "Bruno"}, goal="g", task=TASK, attempt=1, summary="", file_dump="", checks="", security=False)
    assert "Security review" not in safe[0]["content"]


def test_advisor_and_rescue_prompts():
    from backend.prompts import advisor_prompt, rescue_prompt

    adv = advisor_prompt(lead={"name": "Rino"}, team="Ricerca", goal="g", ws=WS, task=TASK, from_="Sara", question="Tono diretto?", progress="- w2.1 [working]")
    assert adv[0]["content"].startswith("[[role:advisor]]")
    assert "QUESTION FROM Sara" in adv[1]["content"]
    res = rescue_prompt(lead={"name": "Rino"}, goal="g", task=TASK, feedback="manca tutto")
    assert res[0]["content"].startswith("[[role:rescue]]")
    assert '"action": "retry" | "skip"' in res[0]["content"]


def test_synth_prompt_blocks_feed_the_mock_report():
    from backend.prompts import synth_prompt

    w = {**WS, "status": "done", "summary": "ok", "error": None}
    t = {**TASK, "status": "done", "escalated": False}
    msgs = synth_prompt(ceo={"name": "Ada"}, goal="Un sito", plan_summary="Piano", workstreams=[w], tasks=[t], files="index.html (100 B)")
    assert msgs[0]["content"].startswith("[[role:synth]]")
    assert "Un sito" in mock.field(msgs[1]["content"], "GOAL")
    assert "w2 [done] Ricerca e requisiti" in mock.block(msgs[1]["content"], "WORKSTREAMS")
    assert "index.html (100 B)" in mock.block(msgs[1]["content"], "PROJECT FILES")


def test_chat_prompt_maps_history_roles():
    from backend.prompts import chat_prompt

    msgs = chat_prompt(agent={"name": "Ada"}, who="the CEO", context="Nessuna missione.", history=[{"from": "user", "text": "ciao"}, {"from": "ada", "text": "salve"}], text="Come va?")
    assert msgs[0]["role"] == "system" and msgs[0]["content"].startswith("[[role:chat]]")
    assert [m["role"] for m in msgs[1:]] == ["user", "assistant", "user"]
    assert msgs[-1]["content"] == "Come va?"
    assert "You are Ada," in msgs[0]["content"]  # the mock's chat_reply reads the name from here


# ---------- spec 06: the language rule ----------

import pytest  # noqa: E402

LEGACY_RULE = "in the language the GOAL is written in"


def _systems(language):
    """The system prompt of every builder, for one language. tasker_system
    covers both workers and sub-agents, so both are listed."""
    from backend import prompts as p

    w = {**WS, "status": "done", "summary": "ok", "error": None}
    t = {**TASK, "status": "done", "escalated": False}
    kw = {} if language == "omit" else {"language": language}
    return {
        "ceo_plan": p.ceo_plan_prompt(cfg=CFG, ceo={"name": "Ada"}, goal="g", memory="", **kw)[0]["content"],
        "lead_plan": p.lead_plan_prompt(cfg=CFG, lead={"name": "Rino"}, team="research", goal="g", ws=WS, upstream=[], **kw)[0]["content"],
        "advisor": p.advisor_prompt(lead={"name": "Rino"}, team="Ricerca", goal="g", ws=WS, task=TASK, from_="Sara", question="?", progress="", **kw)[0]["content"],
        "rescue": p.rescue_prompt(lead={"name": "Rino"}, goal="g", task=TASK, feedback="f", **kw)[0]["content"],
        "librarian": p.librarian_prompt(librarian={"name": "Otto"}, goal="g", task=TASK, candidates=[], per_task=2, **kw)[0]["content"],
        "prompt_eng": p.prompt_eng_prompt(pe={"name": "Pia"}, goal="g", task=TASK, team="Ricerca", skills=[], **kw)[0]["content"],
        "tasker_worker": p.tasker_system(agent={"name": "Sara", "kind": "worker", "team": "research"}, team_cfg=CFG["teams"]["research"], lead={"name": "Rino"}, tools=["finish"], skills_text="", **kw),
        "tasker_sub": p.tasker_system(agent={"name": "Sub 1", "kind": "sub", "team": "research"}, team_cfg=CFG["teams"]["research"], lead={"name": "Rino"}, tools=["finish"], skills_text="", **kw),
        "judge": p.judge_prompt(judge={"name": "Bruno"}, goal="g", task=TASK, attempt=1, summary="", file_dump="", checks="", security=False, **kw)[0]["content"],
        "synth": p.synth_prompt(ceo={"name": "Ada"}, goal="g", plan_summary="", workstreams=[w], tasks=[t], files="", **kw)[0]["content"],
        "chat": p.chat_prompt(agent={"name": "Ada"}, who="the CEO", context="", history=[], text="ciao", **kw)[0]["content"],
    }


@pytest.mark.parametrize("language,name", [("it", "Italian"), ("en", "English")])
def test_every_builder_imposes_the_selected_language(language, name):
    from backend.prompts import language_rule

    rule = language_rule(language)
    assert name in rule
    for builder, system in _systems(language).items():
        assert rule in system, f"{builder} lacks the {name} rule"
        assert LEGACY_RULE not in system, f"{builder} still follows the GOAL language"
        assert "in the language they use" not in system, f"{builder} still follows the user's language"


def test_language_rule_keeps_the_machine_contract_in_english():
    from backend.prompts import language_rule

    rule = language_rule("it")
    # JSON keys, enum values and tool names must not be translated, or
    # run.py's validators and the demo provider stop understanding the reply
    assert "JSON keys" in rule and '"pass"' in rule and "tool names" in rule


@pytest.mark.parametrize("language", [None, "omit"])
def test_no_language_keeps_the_legacy_rule(language):
    systems = _systems(language)
    for builder, system in systems.items():
        if builder in ("librarian", "chat"):
            continue  # they never had the GOAL rule
        assert LEGACY_RULE in system, builder
    assert "in the language they use" in systems["chat"]


def test_unknown_language_is_rejected():
    from backend.prompts import language_rule

    with pytest.raises(ValueError):
        language_rule("fr")
    with pytest.raises(ValueError):
        _systems("xx")


def test_the_rule_does_not_break_the_role_marker():
    for builder, system in _systems("en").items():
        assert system.startswith("[[role:"), builder
