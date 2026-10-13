from backend.router import mock


def test_field_extracts_single_line():
    text = "GOAL: build a thing\nOTHER: x"
    assert mock.field(text, "GOAL") == "build a thing"
    assert mock.field(text, "MISSING") == ""


def test_block_stops_at_blank_line_or_end():
    text = "WORKSTREAMS:\nline one\nline two\n\nNEXT: y"
    assert mock.block(text, "WORKSTREAMS") == "line one\nline two"
    text2 = "FILES:\nonly line"
    assert mock.block(text2, "FILES") == "only line"
    assert mock.block(text2, "MISSING") == ""


def test_ceo_plan_simple_vs_complex():
    simple = mock.ceo_plan("scrivi un breve riassunto")
    assert simple["complexity"] == "simple"
    complex_ = mock.ceo_plan("crea un sito e-commerce completo per il lancio del brand")
    assert complex_["complexity"] == "complex"
    assert any(w["team"] == "prompt" for w in complex_["workstreams"])


def test_ceo_plan_web_goal_has_dev_workstream():
    plan = mock.ceo_plan("crea un sito web per una pizzeria")
    teams = [w["team"] for w in plan["workstreams"]]
    assert "dev" in teams
    assert "research" in teams


def test_lead_plan_multi_deliverable_splits_one_per_file():
    text = "WORKSTREAM ID: w1\nWORKSTREAM TEAM: dev\nWORKSTREAM: Build it\nDELIVERABLES: a.md, b.png"
    plan = mock.lead_plan(text)
    assert [s["outputs"][0] for s in plan["subtasks"]] == ["a.md", "b.png"]


def test_worker_turn_first_step_lists_files():
    brief = "GOAL: g\nTASK ID: w1.1\nTASK: do it\nOUTPUTS: out.md\nSKILLS: none"
    messages = [{"role": "system", "content": "[[role:worker:dev]]"}, {"role": "user", "content": brief}]
    step = mock.worker_turn(messages, "dev")
    assert step["tool"] == "list_files"


def test_answer_dispatches_worker_by_role_marker():
    messages = [{"role": "system", "content": "[[role:worker:dev]]"}, {"role": "user", "content": "GOAL: g\nTASK ID: t\nTASK: x\nOUTPUTS: a.md"}]
    out = mock.answer("other", messages, "dev")
    import json

    parsed = json.loads(out)
    assert "tool" in parsed


def test_answer_pong_without_role_marker():
    assert mock.answer("other", [{"role": "system", "content": "no marker here"}], "") == "pong"
