def test_extract_json_repairs_trailing_commas():
    from backend.json_repair import extract_json

    assert extract_json('{"a": [1,2,],}') == {"a": [1, 2]}


def test_extract_json_strips_think_blocks():
    from backend.json_repair import extract_json

    assert extract_json('<think>scratch</think>```json\n{"ok": true}\n```') == {"ok": True}


def test_extract_json_escapes_raw_newlines_in_strings():
    from backend.json_repair import extract_json

    text = 'Sure! {"thought":"x","tool":"write_file","args":{"path":"a.md","content":"line1\nline2"}} done'
    assert extract_json(text) == {"thought": "x", "tool": "write_file", "args": {"path": "a.md", "content": "line1\nline2"}}


def test_extract_json_returns_none_without_object():
    from backend.json_repair import extract_json

    assert extract_json("no json here") is None
    assert extract_json(None) is None
