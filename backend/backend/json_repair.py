"""Ported 1:1 from server/engine/json.js: models wrap JSON in fences, add
prose around it, or put raw newlines inside strings. Take the first
balanced {...} object and repair what is cheap to repair."""

import ast
import json
import re

THINK_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
# Spec 08: keys without quotes, as small models write them ({tool: "read_file"})
BARE_KEY_RE = re.compile(r"([{,]\s*)([A-Za-z_][\w-]*)\s*:")


def _escape_control_chars_in_strings(src: str) -> str:
    out = []
    in_string = False
    escaped = False
    for ch in src:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            elif ch == "\n":
                out.append("\\n")
                continue
            elif ch == "\r":
                out.append("\\r")
                continue
            elif ch == "\t":
                out.append("\\t")
                continue
        elif ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _python_literal(src: str):
    """{'tool': 'x', 'ok': True}: a Python dict, as some models answer.
    literal_eval evaluates literals only, never code."""
    try:
        value = ast.literal_eval(src)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def _try_parse(src: str):
    attempts = [
        lambda s: s,
        lambda s: TRAILING_COMMA_RE.sub(r"\1", s),
        _escape_control_chars_in_strings,
        lambda s: TRAILING_COMMA_RE.sub(r"\1", _escape_control_chars_in_strings(s)),
        lambda s: TRAILING_COMMA_RE.sub(r"\1", BARE_KEY_RE.sub(r'\1"\2":', _escape_control_chars_in_strings(s))),
    ]
    for fix in attempts:
        try:
            value = json.loads(fix(src))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    return _python_literal(src)


def _close(src: str) -> str | None:
    """An object cut off at the end (max_tokens): closes its brackets, but only
    when the cut is not inside a string, or half a file would be written."""
    stack = []
    in_string = escaped = False
    for c in src:
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
        elif c in "{[":
            stack.append("}" if c == "{" else "]")
        elif c in "}]" and stack:
            stack.pop()
    if in_string or not stack:
        return None
    return src.rstrip().rstrip(",:") + "".join(reversed(stack))


def extract_json(text):
    if not isinstance(text, str):
        return None
    s = THINK_RE.sub("", text)
    from_ = s.find("{")
    while from_ >= 0:
        depth = 0
        in_string = False
        escaped = False
        for i in range(from_, len(s)):
            c = s[i]
            if in_string:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    in_string = False
                continue
            if c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    parsed = _try_parse(s[from_ : i + 1])
                    if parsed is not None:
                        return parsed
                    break
        if depth > 0:
            parsed = _try_parse(s[from_:])
            closed = _close(s[from_:]) if parsed is None else None
            if closed is not None:
                parsed = _try_parse(closed)
            if parsed is not None:
                return parsed
        from_ = s.find("{", from_ + 1)
    return None
