"""Spec 11 T06: the structural extractor of the Reverse Engineering team.

Three pure functions, each with an exact twin in crates/aw_core (rule 2 of the
spec, D20):
- extract_skeleton(source, ext): the skeleton of a source file (Python,
  JavaScript/TypeScript, Rust, HTML, CSS): imports and exports, the signatures
  of classes, functions and methods without their bodies, the API routes it
  serves or calls, its state variables and the graph of its internal calls;
- inspect_artifact_metadata(data, name): what a built artifact says without
  running it (ELF, PE, Mach-O, WebAssembly, zip/jar/wheel, tar, gzip, PDF,
  images, SQLite, text bundles): format, sections, exported and imported
  symbols, readable strings, entropy;
- summarize_runtime_trace(text): the endpoints, payload schemas and sequence of
  states of an execution log, a JSON or JSON-lines trace, or a HAR file.

They are written as character scanners with ASCII-only rules (no ast, no
regex, no Unicode tables), so the Rust twin follows them line by line. The
startup probe (_load_native) uses aw_core only when it returns exactly what
this file returns on DECONSTRUCT_PROBES; otherwise this file does the work.
The render_* functions turn a result into the compact text an agent reads."""

import json
import math

MAX_LINES = 20000
CAPS = {"imports": 80, "exports": 80, "symbols": 300, "routes": 80, "state": 120, "calls": 300}
SIG_MAX = 160
VALUE_MAX = 60
WS = " \t\r\n\x0b\x0c"
_ALOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_AUPPER = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")

LANGUAGES = {
    "py": "python", "pyw": "python", "pyi": "python",
    "js": "javascript", "mjs": "javascript", "cjs": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript", "mts": "typescript", "cts": "typescript",
    "rs": "rust",
    "html": "html", "htm": "html", "xhtml": "html", "vue": "html", "svelte": "html",
    "css": "css", "scss": "css", "less": "css",
}


# ---------- small helpers (each one has a twin of the same name in Rust) ----------


def _strip(s: str) -> str:
    return s.strip(WS)


def _alower(s: str) -> str:
    return s.translate(_ALOWER)


def _aupper(s: str) -> str:
    return s.translate(_AUPPER)


def _collapse(s: str) -> str:
    """Runs of ASCII whitespace become one space; no space at the ends."""
    out: list[str] = []
    space = False
    for c in s:
        if c in WS:
            space = True
        else:
            if space and out:
                out.append(" ")
            space = False
            out.append(c)
    return "".join(out)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _tidy(s: str) -> str:
    """A collapsed signature without the blanks a multi-line header leaves in brackets."""
    return _collapse(s).replace("( ", "(").replace(" )", ")").replace(",)", ")")


def _no_end(s: str) -> str:
    """A statement or a value without its last ";" or ","."""
    s = _strip(s)
    return _strip(s[:-1]) if s.endswith(";") or s.endswith(",") else s


def _is_ident_start(c: str) -> bool:
    return "a" <= c <= "z" or "A" <= c <= "Z" or c == "_" or c == "$" or ord(c) >= 128


def _is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def _is_ident(c: str) -> bool:
    return _is_ident_start(c) or _is_digit(c)


def _read_ident(s: str, i: int) -> tuple[str, int]:
    j = i
    while j < len(s) and _is_ident(s[j]):
        j += 1
    return s[i:j], j


def _read_path(s: str, i: int) -> tuple[str, int]:
    """An identifier with dots and "::" in it (views.index, crate::api::list)."""
    j = i
    while j < len(s) and (_is_ident(s[j]) or s[j] == "." or (s[j] == ":" and j + 1 < len(s) and s[j + 1] == ":")):
        j += 2 if s[j] == ":" else 1
    return s[i:j], j


def _ident_before(s: str, end: int) -> str:
    k = end
    while k > 0 and _is_ident(s[k - 1]):
        k -= 1
    return s[k:end]


def _word_at(s: str, i: int, word: str) -> bool:
    """s holds `word` at i as a whole word."""
    if not s.startswith(word, i):
        return False
    after = i + len(word)
    return (after >= len(s) or not _is_ident(s[after])) and (i == 0 or not _is_ident(s[i - 1]))


def _skip_spaces(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t":
        i += 1
    return i


def _literal(s: str, i: int):
    """The first string literal at or after i, as (content, index after it), or None."""
    while i < len(s) and s[i] not in "'\"`":
        i += 1
    if i >= len(s):
        return None
    q = s[i]
    j = i + 1
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == q:
            return s[i + 1 : j], j + 1
        j += 1
    return None


def _literal_here(s: str, i: int):
    """A string literal that starts at i after spaces only, or None."""
    j = _skip_spaces(s, i)
    if j >= len(s) or s[j] not in "'\"`":
        return None
    return _literal(s, j)


def _indent(line: str) -> int:
    n = 0
    for c in line:
        if c == " ":
            n += 1
        elif c == "\t":
            n += 4
        else:
            break
    return n


def _count(s: str, c: str) -> int:
    return s.count(c)


def _upto(s: str, stop: str) -> str:
    """s up to the first char of `stop` (excluded), or s."""
    for k, c in enumerate(s):
        if c in stop:
            return s[:k]
    return s


# ---------- comments and strings ----------


def _string_open(text: str, i: int, lang: str):
    """(length of the opener, closing delimiter, multiline, escapes) of a string
    literal that starts at i, or None."""
    n = len(text)
    c = text[i]
    if lang == "python":
        if text.startswith('"""', i) or text.startswith("'''", i):
            return 3, text[i : i + 3], True, True
        if c in "\"'":
            return 1, c, False, True
        return None
    if lang in ("javascript", "typescript"):
        if c in "\"'":
            return 1, c, False, True
        if c == "`":
            return 1, "`", True, True
        return None
    if lang == "css":
        return (1, c, False, True) if c in "\"'" else None
    if lang == "rust":
        if c == '"':
            return 1, '"', True, True
        if c in "rb" and (i == 0 or not _is_ident(text[i - 1])):
            j = i
            if text[j] == "b":
                j += 1
            raw = False
            if j < n and text[j] == "r":
                raw = True
                j += 1
            hashes = 0
            while raw and j < n and text[j] == "#":
                hashes += 1
                j += 1
            if j < n and text[j] == '"' and (raw or text[i] == "b"):
                return j + 1 - i, '"' + "#" * hashes, True, not raw
        return None
    return None


def _clean(text: str, lang: str) -> tuple[list[str], list[str]]:
    """Two views of every line: `code` (comments gone, every string literal
    replaced by "") and `kept` (comments gone, strings as written)."""
    hash_comments = lang == "python"
    slash_comments = lang in ("javascript", "typescript", "rust")
    block_comments = lang in ("javascript", "typescript", "rust", "css")
    code_lines: list[str] = []
    kept_lines: list[str] = []
    code: list[str] = []
    kept: list[str] = []
    n = len(text)
    i = 0
    state = 0  # 0 code, 1 block comment, 2 string
    delim, multiline, escapes = "", False, True
    while i < n:
        c = text[i]
        if c == "\n":
            code_lines.append("".join(code))
            kept_lines.append("".join(kept))
            code, kept = [], []
            if state == 2 and not multiline:
                state = 0
            i += 1
            continue
        if c == "\r":
            i += 1
            continue
        if state == 1:
            if c == "*" and i + 1 < n and text[i + 1] == "/":
                state = 0
                i += 2
            else:
                i += 1
            continue
        if state == 2:
            if escapes and c == "\\":
                kept.append(c)
                if i + 1 < n and text[i + 1] not in "\r\n":
                    kept.append(text[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if text.startswith(delim, i):
                kept.append(delim)
                state = 0
                i += len(delim)
                continue
            kept.append(c)
            i += 1
            continue
        if (hash_comments and c == "#") or (slash_comments and c == "/" and i + 1 < n and text[i + 1] == "/"):
            while i < n and text[i] != "\n":
                i += 1
            continue
        if block_comments and c == "/" and i + 1 < n and text[i + 1] == "*":
            state = 1
            i += 2
            continue
        opened = _string_open(text, i, lang)
        if opened is not None:
            length, delim, multiline, escapes = opened
            code.append('""')
            kept.append(text[i : i + length])
            state = 2
            i += length
            continue
        if lang == "rust" and c == "'":
            # 'x' and '\n' are char literals, a lone 'a is a lifetime
            if i + 2 < n and text[i + 1] not in "\\\n" and text[i + 2] == "'":
                code.append('""')
                kept.append(text[i : i + 3])
                i += 3
                continue
            if i + 1 < n and text[i + 1] == "\\":
                k = i + 3
                while k < n and k < i + 12 and text[k] not in "'\n":
                    k += 1
                if k < n and text[k] == "'":
                    code.append('""')
                    kept.append(text[i : k + 1])
                    i = k + 1
                    continue
        code.append(c)
        kept.append(c)
        i += 1
    code_lines.append("".join(code))
    kept_lines.append("".join(kept))
    return code_lines, kept_lines


# ---------- the result ----------


class _Out:
    def __init__(self, language: str, lines: int):
        self.language = language
        self.lines = lines
        self.imports: list[str] = []
        self.exports: list[str] = []
        self.symbols: list[dict] = []
        self.routes: list[dict] = []
        self.state: list[dict] = []
        self.calls: list[dict] = []
        self.truncated = False
        self.seen: set[str] = set()

    def _room(self, key: str) -> bool:
        if len(getattr(self, key)) >= CAPS[key]:
            self.truncated = True
            return False
        return True

    def add_import(self, text: str) -> None:
        text = _clip(_no_end(_collapse(text)), SIG_MAX)
        if text and "i\x00" + text not in self.seen and self._room("imports"):
            self.seen.add("i\x00" + text)
            self.imports.append(text)

    def add_export(self, name: str) -> None:
        name = _clip(_collapse(name), SIG_MAX)
        if name and "e\x00" + name not in self.seen and self._room("exports"):
            self.seen.add("e\x00" + name)
            self.exports.append(name)

    def symbol(self, kind: str, name: str, line: int, signature: str, parent: str) -> None:
        if name and self._room("symbols"):
            self.symbols.append({"kind": kind, "name": name, "line": line, "signature": _clip(_tidy(signature), SIG_MAX), "parent": parent})

    def route(self, method: str, path: str, handler: str, line: int, side: str) -> None:
        if self._room("routes"):
            self.routes.append({"method": method, "path": _clip(path, SIG_MAX), "handler": handler, "line": line, "side": side})

    def add_state(self, name: str, value: str, line: int, parent: str) -> None:
        key = "s\x00" + parent + "\x00" + name
        if name and key not in self.seen and self._room("state"):
            self.seen.add(key)
            self.state.append({"name": name, "line": line, "value": _clip(_no_end(_collapse(value)), VALUE_MAX), "parent": parent})

    def call(self, from_: str, to: str) -> None:
        key = "c\x00" + from_ + "\x00" + to
        if key not in self.seen and self._room("calls"):
            self.seen.add(key)
            self.calls.append({"from": from_, "to": to})

    def merge(self, other: "_Out", offset: int) -> None:
        for x in other.imports:
            self.add_import(x)
        for x in other.exports:
            self.add_export(x)
        for s in other.symbols:
            self.symbol(s["kind"], s["name"], s["line"] + offset, s["signature"], s["parent"])
        for r in other.routes:
            self.route(r["method"], r["path"], r["handler"], r["line"] + offset, r["side"])
        for s in other.state:
            self.add_state(s["name"], s["value"], s["line"] + offset, s["parent"])
        for c in other.calls:
            self.call(c["from"], c["to"])
        self.truncated = self.truncated or other.truncated

    def result(self) -> dict:
        return {"language": self.language, "lines": self.lines, "imports": self.imports, "exports": self.exports, "symbols": self.symbols, "routes": self.routes, "state": self.state, "calls": self.calls, "truncated": self.truncated}


def _scan_calls(s: str, self_word: str, rust: bool) -> list[tuple[str, str, str]]:
    """The calls a line makes: ("bare", name, ""), ("self", name, "") for
    self.name( / this.name( / Self::name(, ("type", Type, name) for Type::name(."""
    res: list[tuple[str, str, str]] = []
    j, n = 0, len(s)
    while j < n:
        if _is_ident_start(s[j]) and (j == 0 or not _is_ident(s[j - 1])):
            name, k = _read_ident(s, j)
            m = _skip_spaces(s, k)
            if m < n and s[m] == "(":
                if j >= 1 and s[j - 1] == ".":
                    if _ident_before(s, j - 1) == self_word:
                        res.append(("self", name, ""))
                elif rust and j >= 2 and s[j - 1] == ":" and s[j - 2] == ":":
                    recv = _ident_before(s, j - 2)
                    if recv == "Self":
                        res.append(("self", name, ""))
                    elif recv:
                        res.append(("type", recv, name))
                else:
                    res.append(("bare", name, ""))
            j = k
        else:
            j += 1
    return res


def _resolve(out: _Out, candidates: list, functions: set, classes: set, methods: set, sep: str) -> None:
    """Keeps the calls to what this file defines: a nested function first, then a
    top-level one, then a class (its constructor); self.x( and Type::x( to methods."""
    for caller, cls, form, a, b in candidates:
        to = ""
        if form == "self":
            if cls and cls + "\x00" + a in methods:
                to = cls + sep + a
        elif form == "type":
            if a + "\x00" + b in methods:
                to = a + sep + b
        elif caller + sep + a in functions:
            to = caller + sep + a
        elif a in functions:
            to = a
        elif a in classes:
            to = a
        if to:
            out.call(caller, to)


# ---------- Python ----------

PY_KEYWORDS = {
    "if", "elif", "else", "for", "while", "return", "with", "try", "except", "finally", "raise", "assert", "del", "pass", "break",
    "continue", "global", "nonlocal", "lambda", "yield", "await", "not", "and", "or", "in", "is", "import", "from", "class", "def",
    "async", "match", "case", "None", "True", "False", "print", "self",
}
PY_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "route", "api_route", "websocket"}


def _py_header(code: list[str], i: int) -> tuple[int, str]:
    """(last line, signature) of a def or class header: up to the first ":" outside brackets."""
    parts: list[str] = []
    depth = 0
    k = i
    while k < len(code) and k < i + 12:
        line = code[k]
        for idx, c in enumerate(line):
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
            elif c == ":" and depth <= 0:
                parts.append(line[:idx])
                return k, _collapse(" ".join(parts))
        parts.append(line)
        k += 1
    return i, _collapse(code[i])


def _py_assignment(s: str):
    """(name, index of its "=" or -1) of `name = ...` / `name: type = ...` / `name: type`, else None."""
    name, j = _read_ident(s, 0)
    if not name or name in PY_KEYWORDS or _is_digit(name[0]):
        return None
    j = _skip_spaces(s, j)
    if j < len(s) and s[j] == ":":
        k = s.find("=", j)
        if k < 0:
            return name, -1
        if k + 1 < len(s) and s[k + 1] == "=":
            return None
        return name, k
    if j < len(s) and s[j] == "=" and not (j + 1 < len(s) and s[j + 1] == "="):
        return name, j
    return None


def _bracket_end(code: list[str], i: int, limit: int) -> int:
    """The line where the brackets opened on line i close (i itself when balanced)."""
    depth = 0
    k = i
    while k < len(code) and k < i + limit:
        for c in code[k]:
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
        if depth <= 0:
            return k
        k += 1
    return min(k, len(code)) - 1 if k > i else i


def _py_route(d: str, handler: str, line: int, out: _Out) -> None:
    dotted, j = _read_path(d, 1)
    if "." not in dotted or j >= len(d) or d[j] != "(":
        return
    method = _alower(dotted[dotted.rfind(".") + 1 :])
    if method not in PY_ROUTE_METHODS:
        return
    lit = _literal_here(d, j + 1)
    if lit is None or not lit[0].startswith("/"):
        return
    if method in ("route", "api_route"):
        k = d.find("methods")
        m = _literal(d, k) if k >= 0 else None
        verb = _aupper(m[0]) if m else "GET"
    elif method == "websocket":
        verb = "WS"
    else:
        verb = _aupper(method)
    out.route(verb, lit[0], handler, line, "server")


def _python(code: list[str], kept: list[str], out: _Out) -> None:
    stack: list[tuple[int, str, str, str]] = []  # (indent, "class" | "def", name, qual)
    decorators: list[tuple[str, int]] = []
    candidates: list = []
    functions: set[str] = set()
    classes: set[str] = set()
    methods: set[str] = set()
    all_names: list[str] | None = None
    top_level: list[str] = []
    n = len(code)
    i = 0
    while i < n:
        s = _strip(code[i])
        if not s:
            i += 1
            continue
        ind = _indent(code[i])
        while stack and ind <= stack[-1][0]:
            stack.pop()
        if s[0] == "@":
            decorators.append((_strip(kept[i]), i + 1))
            i += 1
            continue
        t = _strip(s[5:]) if _word_at(s, 0, "async") else s
        if _word_at(t, 0, "def") or _word_at(t, 0, "class"):
            word = "def" if _word_at(t, 0, "def") else "class"
            name, _ = _read_ident(t, _skip_spaces(t, len(word)))
            end, sig = _py_header(code, i)
            parent = stack[-1][3] if stack else ""
            qual = parent + "." + name if parent else name
            if name and word == "class":
                out.symbol("class", name, i + 1, sig, parent)
                classes.add(qual)
                stack.append((ind, "class", name, qual))
            elif name:
                in_class = bool(stack) and stack[-1][1] == "class"
                out.symbol("method" if in_class else "function", name, i + 1, sig, parent)
                functions.add(qual)
                if in_class:
                    methods.add(parent + "\x00" + name)
                for d, dl in decorators:
                    _py_route(d, name, dl, out)
                stack.append((ind, "def", name, qual))
            if name and not parent:
                top_level.append(name)
            decorators = []
            i = end + 1
            continue
        decorators = []
        if _word_at(s, 0, "import") or (_word_at(s, 0, "from") and " import " in s):
            end = _bracket_end(code, i, 30)
            out.add_import(" ".join(_strip(kept[k]) for k in range(i, end + 1)))
            i = end + 1
            continue
        ks = _strip(kept[i])
        for fn in ("path(", "re_path(", "url("):
            if ks.startswith(fn):
                lit = _literal_here(ks, len(fn))
                if lit is not None:
                    rest = ks[lit[1] :]
                    comma = rest.find(",")
                    handler = _read_path(_strip(rest[comma + 1 :]), 0)[0] if comma >= 0 else ""
                    out.route("ANY", lit[0], handler, i + 1, "server")
                break
        top = stack[-1] if stack else None
        if top is None or top[1] == "class":
            a = _py_assignment(s)
            if a is not None:
                name, eq = a
                if name == "__all__" and top is None:
                    end = _bracket_end(code, i, 60)
                    text = " ".join(kept[k] for k in range(i, end + 1))
                    all_names = []
                    p = max(text.find("="), 0)
                    while True:
                        lit = _literal(text, p)
                        if lit is None:
                            break
                        all_names.append(lit[0])
                        p = lit[1]
                    i = end + 1
                    continue
                value = _strip(ks[eq + 1 :]) if eq >= 0 else ""
                out.add_state(name, value, i + 1, top[3] if top else "")
        fn_entry = next((e for e in reversed(stack) if e[1] == "def"), None)
        cls_entry = next((e for e in reversed(stack) if e[1] == "class"), None)
        if fn_entry is not None and cls_entry is not None and s.startswith("self."):
            name, j = _read_ident(s, 5)
            j = _skip_spaces(s, j)
            if name and j < len(s) and (s[j] == "=" and not (j + 1 < len(s) and s[j + 1] == "=") or s[j] == ":"):
                eq = s.find("=", j)
                value = _strip(ks[eq + 1 :]) if eq >= 0 and eq < len(ks) else ""
                out.add_state("self." + name, value, i + 1, cls_entry[3])
        if fn_entry is not None:
            for form, a, b in _scan_calls(s, "self", False):
                candidates.append((fn_entry[3], cls_entry[3] if cls_entry else "", form, a, b))
        i += 1
    if all_names is not None:
        for x in all_names:
            out.add_export(x)
    else:
        for x in top_level:
            if not x.startswith("_"):
                out.add_export(x)
    _resolve(out, candidates, functions, classes, methods, ".")


# ---------- JavaScript / TypeScript ----------

JS_MODIFIERS = ("export", "default", "async", "static", "public", "private", "protected", "readonly", "declare", "abstract", "override", "get", "set")
JS_ROUTE_METHODS = ("get", "post", "put", "patch", "delete", "all", "use", "head", "options")
JS_CLIENTS = ("axios", "http", "api", "client", "ky", "$http", "request")
HTTP_VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


def _js_mods(s: str) -> tuple[str, bool, bool]:
    """s without its leading modifiers, and whether it is exported / the default export.
    A modifier is a word followed by spaces and then a name, *, # or a bracket."""
    exported = default = False
    t = s
    changed = True
    while changed:
        changed = False
        for w in JS_MODIFIERS:
            if _word_at(t, 0, w):
                j = _skip_spaces(t, len(w))
                if j > len(w) and j < len(t) and t[j] not in "(=:<.,;)":
                    if w == "export":
                        exported = True
                    if w == "default":
                        default = True
                    t = t[j:]
                    changed = True
                    break
    return t, exported, default


def _arrow_or_function(v: str) -> bool:
    """A value that is a function: function (...), async (...) =>, x =>, (...) =>."""
    v = _strip(v)
    if _word_at(v, 0, "async"):
        v = _strip(v[5:])
    if _word_at(v, 0, "function"):
        return True
    if v.startswith("("):
        depth = 0
        for k, c in enumerate(v):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    rest = _strip(v[k + 1 :])
                    if rest.startswith(":"):  # a TypeScript return type
                        arrow = rest.find("=>")
                        return arrow >= 0
                    return rest.startswith("=>")
        return False
    name, k = _read_ident(v, 0)
    return bool(name) and _strip(v[k:]).startswith("=>")


def _js_signature(s: str) -> str:
    arrow = s.find("=>")
    if arrow >= 0:
        return s[: arrow + 2]
    brace = s.find("{")
    return s[:brace] if brace >= 0 else s


def _js_routes(ks: str, line: int, out: _Out) -> None:
    j, n = 0, len(ks)
    while j < n:
        if ks[j] == "." and j > 0:
            recv = _ident_before(ks, j)
            name, k = _read_ident(ks, j + 1)
            if recv and name and k < n and ks[k] == "(":
                low = _alower(name)
                lit = _literal_here(ks, k + 1)
                if low == "open" and lit is not None and _aupper(lit[0]) in HTTP_VERBS:
                    path = _literal_here(ks, _skip_spaces(ks, lit[1]) + 1) if _skip_spaces(ks, lit[1]) < n and ks[_skip_spaces(ks, lit[1])] == "," else None
                    if path is not None:
                        out.route(_aupper(lit[0]), path[0], "", line, "client")
                elif low in JS_ROUTE_METHODS and lit is not None and (lit[0].startswith("/") or lit[0].startswith("http")):
                    client = recv in JS_CLIENTS
                    if client or lit[0].startswith("/"):
                        handler = ""
                        if not client:
                            close = ks.rfind(")")
                            args = ks[lit[1] : close] if close > lit[1] else ks[lit[1] :]
                            last = _strip(args.split(",")[-1]) if "," in args else ""
                            path_name, e = _read_path(last, 0)
                            handler = path_name if path_name and e == len(last) else ""
                        out.route(_aupper(low), lit[0], handler, line, "client" if client else "server")
            j = k if name else j + 1
            continue
        if _word_at(ks, j, "fetch") and _skip_spaces(ks, j + 5) < n and ks[_skip_spaces(ks, j + 5)] == "(":
            lit = _literal_here(ks, _skip_spaces(ks, j + 5) + 1)
            if lit is not None and (lit[0].startswith("/") or lit[0].startswith("http")):
                k = ks.find("method", lit[1])
                m = _literal(ks, k) if k >= 0 else None
                out.route(_aupper(m[0]) if m else "GET", lit[0], "", line, "client")
            j += 5
            continue
        j += 1


def _javascript(code: list[str], kept: list[str], out: _Out) -> None:
    depth = 0
    conts: list[tuple[str, str, int]] = []  # (kind "class" | "interface", name, depth inside)
    fns: list[tuple[str, int]] = []  # (qual, depth inside)
    pending = None  # ("class" | "interface" | "fn", name) waiting for its "{"
    candidates: list = []
    functions: set[str] = set()
    classes: set[str] = set()
    methods: set[str] = set()
    skip_until = -1
    for i in range(len(code)):
        s = _strip(code[i])
        ks = _strip(kept[i])
        start = depth
        opens, closes = _count(code[i], "{"), _count(code[i], "}")
        if s and i > skip_until:
            if pending is not None and "{" in s:
                if pending[0] == "fn":
                    fns.append((pending[1], start + 1))
                else:
                    conts.append((pending[0], pending[1], start + 1))
                pending = None
            elif pending is not None and s.endswith(";"):
                pending = None
            cont = conts[-1] if conts else None
            in_body = cont is not None and start == cont[2]
            cls = next((c[1] for c in reversed(conts) if c[0] == "class"), "")
            caller = fns[-1][0] if fns else ""
            scan_from = 0  # the part of the line whose calls count (after a header's "{")
            new_caller = ""
            t, exported, default = _js_mods(s)
            if in_body and cont[0] == "interface":
                t = ""  # members of an interface or an enum are no methods
            if default:
                out.add_export("default")
            if t and _word_at(t, 0, "import") and _skip_spaces(t, 6) < len(t) and t[_skip_spaces(t, 6)] not in "(.":
                end = i
                if "{" in code[i] and "}" not in code[i]:
                    end = next((k for k in range(i + 1, min(len(code), i + 30)) if "}" in code[k]), i)
                out.add_import(" ".join(_strip(kept[k]) for k in range(i, end + 1)))
                skip_until = end
                t = ""
            if t and "require(" in s:
                out.add_import(ks)
            if t and exported and t.startswith("{"):
                inner = _upto(t[1:], "}")
                for part in inner.split(","):
                    part = _strip(part)
                    as_at = part.find(" as ")
                    name = _read_ident(_strip(part[as_at + 4 :]) if as_at >= 0 else part, 0)[0]
                    out.add_export(name)
                if " from " in s:
                    out.add_import(ks)
                t = ""
            if t and exported and t.startswith("*"):
                out.add_export("*")
                out.add_import(ks)
                t = ""
            if t and (t.startswith("module.exports") or t.startswith("exports.")):
                rest = t[len("module.exports") :] if t.startswith("module.exports") else t[len("exports") :]
                if rest.startswith("."):
                    out.add_export(_read_ident(rest, 1)[0])
                else:
                    eq = rest.find("=")
                    value = _strip(rest[eq + 1 :]) if eq >= 0 else ""
                    if value.startswith("{"):
                        for part in _upto(value[1:], "}").split(","):
                            out.add_export(_read_ident(_strip(part), 0)[0])
                    else:
                        out.add_export(_read_ident(value, 0)[0] or "module.exports")
                t = ""
            if t and _word_at(t, 0, "class"):
                name = _read_ident(t, _skip_spaces(t, 5))[0]
                if name:
                    out.symbol("class", name, i + 1, _upto(s, "{"), caller)
                    classes.add(name)
                    if exported:
                        out.add_export(name)
                    if "{" in s:
                        conts.append(("class", name, start + 1))
                    else:
                        pending = ("class", name)
                t = ""
            for word in ("interface", "enum", "type"):
                if t and _word_at(t, 0, word):
                    name, k = _read_ident(t, _skip_spaces(t, len(word)))
                    if name and (word != "type" or "=" in t[k:]):
                        out.symbol(word, name, i + 1, _upto(s, "{=" if word == "type" else "{"), "")
                        if exported:
                            out.add_export(name)
                        if "{" in s and _count(code[i], "{") > _count(code[i], "}"):
                            conts.append(("interface", name, start + 1))
                    t = ""
            if t and _word_at(t, 0, "function"):
                j = _skip_spaces(t, 8)
                if j < len(t) and t[j] == "*":
                    j = _skip_spaces(t, j + 1)
                name = _read_ident(t, j)[0]
                if name:
                    qual = caller + "." + name if caller else name
                    out.symbol("function", name, i + 1, _upto(s, "{"), caller)
                    functions.add(qual)
                    if exported:
                        out.add_export(name)
                    if "{" in s:
                        fns.append((qual, start + 1))
                        new_caller, scan_from = qual, s.find("{") + 1
                    elif not s.endswith(";"):
                        pending = ("fn", qual)
                t = "" if name else t
            for word in ("const", "let", "var"):
                if t and _word_at(t, 0, word):
                    v = _strip(t[len(word) :])
                    if v.startswith("["):
                        if "useState(" in s or "useReducer(" in s:
                            name = _read_ident(_strip(v[1:]), 0)[0]
                            u = ks.find("use")
                            out.add_state(name, ks[u:] if u >= 0 else "", i + 1, caller)
                    elif not v.startswith("{"):
                        name, k = _read_ident(v, 0)
                        e = k
                        while e < len(v) and not (v[e] == "=" and not (e + 1 < len(v) and v[e + 1] in "=>")):
                            e += 1
                        value = _strip(v[e + 1 :]) if e < len(v) else ""
                        if name and _arrow_or_function(value):
                            qual = caller + "." + name if caller else name
                            out.symbol("function", name, i + 1, _js_signature(s), caller)
                            functions.add(qual)
                            if exported:
                                out.add_export(name)
                            arrow = s.find("=>")
                            body = s[arrow + 2 :] if arrow >= 0 else s[s.find("{") + 1 :] if "{" in s else ""
                            if "{" in body:
                                fns.append((qual, start + 1))
                            new_caller, scan_from = qual, (arrow + 2 if arrow >= 0 else (s.find("{") + 1 if "{" in s else len(s)))
                        elif name and _word_at(value, 0, "class"):
                            out.symbol("class", name, i + 1, _upto(s, "{"), caller)
                            classes.add(name)
                            if "{" in s:
                                conts.append(("class", name, start + 1))
                        elif name and not value.startswith("require("):
                            if exported:
                                out.add_export(name)
                            if start == 0 and not fns:
                                kv = ks.find("=")
                                out.add_state(name, _strip(ks[kv + 1 :]) if kv >= 0 and e < len(v) else "", i + 1, "")
                    t = ""
            if t and in_body and cont[0] == "class":
                if t.startswith("*"):
                    t = _strip(t[1:])
                hash_ = t.startswith("#")
                name, k = _read_ident(t, 1 if hash_ else 0)
                name = ("#" + name) if hash_ and name else name
                k = _skip_spaces(t, k)
                if name and k < len(t) and t[k] in "(<" and name not in ("if", "for", "while", "switch", "catch", "return"):
                    qual = cont[1] + "." + name
                    out.symbol("method", name, i + 1, _upto(s, "{"), cont[1])
                    functions.add(qual)
                    methods.add(cont[1] + "\x00" + name)
                    if "{" in s:
                        fns.append((qual, start + 1))
                        new_caller, scan_from = qual, s.find("{") + 1
                    elif not s.endswith(";"):
                        pending = ("fn", qual)
                elif name and k < len(t) and t[k] == "=" and not (k + 1 < len(t) and t[k + 1] == "="):
                    value = _strip(t[k + 1 :])
                    if _arrow_or_function(value):
                        qual = cont[1] + "." + name
                        out.symbol("method", name, i + 1, _js_signature(s), cont[1])
                        functions.add(qual)
                        methods.add(cont[1] + "\x00" + name)
                        arrow = s.find("=>")
                        if "{" in s[arrow + 2 :]:
                            fns.append((qual, start + 1))
                        new_caller, scan_from = qual, arrow + 2
                    else:
                        kv = ks.find("=")
                        out.add_state(name, _strip(ks[kv + 1 :]) if kv >= 0 else "", i + 1, cont[1])
                elif name and (k >= len(t) or t[k] in ":;?!"):
                    kv = ks.find("=")
                    out.add_state(name, _strip(ks[kv + 1 :]) if kv >= 0 else "", i + 1, cont[1])
                t = ""
            if cls and fns and s.startswith("this."):
                name, j = _read_ident(s, 5)
                j = _skip_spaces(s, j)
                if name and j < len(s) and s[j] == "=" and not (j + 1 < len(s) and s[j + 1] == "="):
                    kv = ks.find("=")
                    out.add_state("this." + name, _strip(ks[kv + 1 :]) if kv >= 0 else "", i + 1, cls)
            _js_routes(ks, i + 1, out)
            who = new_caller or caller
            if who:
                for form, a, b in _scan_calls(s[scan_from:] if new_caller else s, "this", False):
                    candidates.append((who, cls, form, a, b))
        depth = max(0, start + opens - closes)
        while conts and conts[-1][2] > depth:
            conts.pop()
        while fns and fns[-1][1] > depth:
            fns.pop()
    _resolve(out, candidates, functions, classes, methods, ".")


# ---------- Rust ----------

RUST_ROUTE_ATTRS = ("get", "post", "put", "patch", "delete", "head", "options")
AXUM_METHODS = ("get", "post", "put", "patch", "delete", "head", "options", "any")


def _rust_mods(s: str) -> tuple[str, bool]:
    """s without visibility and qualifiers (pub, pub(crate), async, unsafe,
    extern "C", default; const before fn), and whether it was pub."""
    is_pub = False
    t = s
    changed = True
    while changed:
        changed = False
        if _word_at(t, 0, "pub"):
            is_pub = True
            j = _skip_spaces(t, 3)
            if j < len(t) and t[j] == "(":
                close = t.find(")", j)
                j = _skip_spaces(t, close + 1) if close >= 0 else len(t)
            t = t[j:]
            changed = True
            continue
        for w in ("async", "unsafe", "default"):
            if _word_at(t, 0, w) and _skip_spaces(t, len(w)) > len(w):
                t = t[_skip_spaces(t, len(w)) :]
                changed = True
                break
        if changed:
            continue
        if _word_at(t, 0, "extern") and not _word_at(t, _skip_spaces(t, 6), "crate"):
            j = _skip_spaces(t, 6)
            if t.startswith('""', j):
                j = _skip_spaces(t, j + 2)
            t = t[j:]
            changed = True
            continue
        if _word_at(t, 0, "const"):
            j = _skip_spaces(t, 5)
            if _word_at(t, j, "fn") or _word_at(t, j, "unsafe") or _word_at(t, j, "async") or _word_at(t, j, "extern"):
                t = t[j:]
                changed = True
    return t, is_pub


def _rust_header(code: list[str], i: int) -> tuple[int, str, bool]:
    """(last line, signature, has a body) of an item header: up to its "{" or ";"."""
    parts: list[str] = []
    k = i
    while k < len(code) and k < i + 12:
        line = code[k]
        for idx, c in enumerate(line):
            if c == "{" or c == ";":
                parts.append(line[:idx])
                return k, _collapse(" ".join(parts)), c == "{"
        parts.append(line)
        k += 1
    return i, _collapse(code[i]), False


def _rust_type_name(text: str) -> str:
    """The base name of a type path: crate::model::Todo<T> -> Todo."""
    t = _strip(text)
    while t.startswith("&") or t.startswith("dyn ") or t.startswith("mut "):
        t = _strip(t[1:] if t.startswith("&") else t[4:])
    path, _ = _read_path(t, 0)
    cut = path.rfind("::")
    return path[cut + 2 :] if cut >= 0 else path


def _rust(code: list[str], kept: list[str], out: _Out) -> None:
    depth = 0
    conts: list[tuple[str, str, int]] = []  # (kind: impl, trait, struct, enum, mod; name; depth inside)
    fns: list[tuple[str, int]] = []
    pending = None
    attrs: list[tuple[str, int]] = []
    candidates: list = []
    functions: set[str] = set()
    classes: set[str] = set()
    methods: set[str] = set()
    skip_until = -1
    for i in range(len(code)):
        s = _strip(code[i])
        ks = _strip(kept[i])
        start = depth
        opens, closes = _count(code[i], "{"), _count(code[i], "}")
        # a header that waits for its "{" gets it even on a line the header itself spans
        if s and pending is not None and "{" in s:
            if pending[0] == "fn":
                fns.append((pending[1], start + 1))
            else:
                conts.append((pending[0], pending[1], start + 1))
            pending = None
        elif s and pending is not None and s.endswith(";"):
            pending = None
        if s and i > skip_until and (s.startswith("#[") or s.startswith("#![")):
            attrs.append((ks, i + 1))
        elif s and i > skip_until:
            cont = conts[-1] if conts else None
            in_body = cont is not None and start == cont[2]
            top = cont is None
            caller = fns[-1][0] if fns else ""
            impl = next((c[1] for c in reversed(conts) if c[0] in ("impl", "trait")), "")
            module = next((c[1] for c in reversed(conts) if c[0] == "mod"), "")
            t, is_pub = _rust_mods(s)
            new_caller, scan_from = "", 0
            if _word_at(t, 0, "use") or _word_at(t, 0, "extern"):
                end = next((k for k in range(i, min(len(code), i + 20)) if ";" in code[k]), i)
                text = _collapse(" ".join(_strip(kept[k]) for k in range(i, end + 1)))
                text = _rust_mods(text)[0]
                if text.endswith(";"):
                    text = _strip(text[:-1])
                out.add_import(text)
                if is_pub and top:
                    out.add_export(text)
                skip_until = end
            elif _word_at(t, 0, "mod"):
                name = _read_ident(t, _skip_spaces(t, 3))[0]
                if "{" in s:
                    out.symbol("module", name, i + 1, _upto(s, "{"), module)
                    conts.append(("mod", name, start + 1))
                elif name:
                    out.add_import("mod " + name)
                if is_pub and top and name:
                    out.add_export(name)
            elif _word_at(t, 0, "fn"):
                name = _read_ident(t, _skip_spaces(t, 2))[0]
                end, sig, body = _rust_header(code, i)
                if name:
                    if in_body and cont[0] in ("impl", "trait"):
                        kind, parent = "method", cont[1]
                        qual = parent + "::" + name
                        methods.add(parent + "\x00" + name)
                    else:
                        kind, parent = "function", caller or module
                        qual = parent + "::" + name if parent else name
                    out.symbol(kind, name, i + 1, sig, parent)
                    functions.add(qual)
                    if is_pub and top:
                        out.add_export(name)
                    for a, al in attrs:
                        _rust_attr_route(a, name, al, out)
                    if body and end == i:
                        fns.append((qual, start + 1))
                        new_caller, scan_from = qual, s.find("{") + 1
                    elif body:
                        pending = ("fn", qual)
                skip_until = end if end > i else skip_until
            elif _word_at(t, 0, "impl"):
                j = _skip_spaces(t, 4)
                if j < len(t) and t[j] == "<":
                    level = 0
                    while j < len(t):
                        if t[j] == "<":
                            level += 1
                        elif t[j] == ">":
                            level -= 1
                            if level == 0:
                                j += 1
                                break
                        j += 1
                head = _upto(t[j:], "{")
                where = head.find(" where ")
                head = head[:where] if where >= 0 else head
                for_at = head.find(" for ")
                name = _rust_type_name(head[for_at + 5 :] if for_at >= 0 else head)
                if name:
                    out.symbol("impl", name, i + 1, _upto(s, "{"), module)
                    classes.add(name)
                    if "{" in s:
                        conts.append(("impl", name, start + 1))
                    else:
                        pending = ("impl", name)
            else:
                word = next((w for w in ("struct", "enum", "trait", "union", "type", "const", "static", "macro_rules!") if t.startswith(w) and (w.endswith("!") or _word_at(t, 0, w))), "")
                if word:
                    j = _skip_spaces(t, len(word))
                    if word == "static" and _word_at(t, j, "mut"):
                        j = _skip_spaces(t, j + 3)
                    name = _read_ident(t, j)[0]
                    if name and word in ("const", "static"):
                        eq = ks.find("=")
                        value = _strip(_upto(ks[eq + 1 :], ";")) if eq >= 0 else ""
                        if top or (cont is not None and cont[0] in ("mod", "impl") and in_body):
                            out.add_state(name, value, i + 1, "" if top else cont[1])
                        if is_pub and top:
                            out.add_export(name)
                    elif name:
                        kind = {"macro_rules!": "macro", "union": "struct"}.get(word, word)
                        out.symbol(kind, name, i + 1, _upto(s, "{;=" if word == "type" else "{;("), module)
                        if word in ("struct", "enum", "trait", "union"):
                            classes.add(name)
                            if "{" in s and _count(code[i], "{") > _count(code[i], "}"):
                                conts.append(("trait" if word == "trait" else word, name, start + 1))
                        if is_pub and top:
                            out.add_export(name)
                elif in_body and cont[0] in ("struct", "union"):
                    name, k = _read_ident(t, 0)
                    k = _skip_spaces(t, k)
                    if name and k < len(t) and t[k] == ":" and not t.startswith("::", k):
                        out.add_state(name, _strip(_upto(t[k + 1 :], ",")), i + 1, cont[1])
            if ".route(" in ks:
                _axum_routes(ks, i + 1, out)
            attrs = [] if not (s.startswith("#[") or s.startswith("#![")) else attrs
            who = new_caller or caller
            if who:
                for form, a, b in _scan_calls(s[scan_from:] if new_caller else s, "self", True):
                    candidates.append((who, impl, form, a, b))
        depth = max(0, start + opens - closes)
        while conts and conts[-1][2] > depth:
            conts.pop()
        while fns and fns[-1][1] > depth:
            fns.pop()
    _resolve(out, candidates, functions, classes, methods, "::")


def _rust_attr_route(a: str, handler: str, line: int, out: _Out) -> None:
    if not a.startswith("#["):
        return
    name, j = _read_ident(a, 2)
    low = _alower(name)
    if j >= len(a) or a[j] != "(":
        return
    lit = _literal_here(a, j + 1)
    if lit is None or not lit[0].startswith("/"):
        return
    if low in RUST_ROUTE_ATTRS:
        out.route(_aupper(low), lit[0], handler, line, "server")
    elif low == "route":
        k = a.find("method", lit[1])
        m = _literal(a, k) if k >= 0 else None
        out.route(_aupper(m[0]) if m else "ANY", lit[0], handler, line, "server")


def _axum_routes(ks: str, line: int, out: _Out) -> None:
    p = ks.find(".route(")
    while p >= 0:
        lit = _literal_here(ks, p + 7)
        if lit is None:
            break
        nxt = ks.find(".route(", lit[1])
        seg = ks[lit[1] : nxt] if nxt >= 0 else ks[lit[1] :]
        j = 0
        while j < len(seg):
            if _is_ident_start(seg[j]) and (j == 0 or not _is_ident(seg[j - 1])):
                word, k = _read_ident(seg, j)
                if word in AXUM_METHODS and k < len(seg) and seg[k] == "(":
                    handler = _read_path(seg, _skip_spaces(seg, k + 1))[0]
                    out.route(_aupper(word), lit[0], handler, line, "server")
                j = k
            else:
                j += 1
        p = nxt


# ---------- HTML and CSS ----------


def _tag(text: str, i: int) -> tuple[str, dict, int]:
    """(name, attributes, index after ">") of the tag that opens at i."""
    n = len(text)
    j = i + 1
    while j < n and (text[j].isascii() and text[j].isalnum() or text[j] == "-"):
        j += 1
    name = _alower(text[i + 1 : j])
    attrs: dict[str, str] = {}
    while j < n:
        while j < n and text[j] in WS:
            j += 1
        if j >= n:
            break
        if text[j] == ">":
            j += 1
            break
        if text[j] == "/":
            j += 1
            continue
        k = j
        while k < n and text[k] not in WS and text[k] not in "=>/\"'":
            k += 1
        if k == j:
            j += 1
            continue
        attr = _alower(text[j:k])
        j = k
        while j < n and text[j] in WS:
            j += 1
        value = ""
        if j < n and text[j] == "=":
            j += 1
            while j < n and text[j] in WS:
                j += 1
            if j < n and text[j] in "\"'":
                e = text.find(text[j], j + 1)
                e = n if e < 0 else e
                value = text[j + 1 : e]
                j = e + 1
            else:
                e = j
                while e < n and text[e] not in WS and text[e] != ">":
                    e += 1
                value = text[j:e]
                j = e
        if attr not in attrs:
            attrs[attr] = value
    return name, attrs, j


def _html(text: str, out: _Out) -> None:
    low = _alower(text)
    n = len(text)
    i = 0
    line = 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c == "<" and text.startswith("<!--", i):
            end = text.find("-->", i + 4)
            end = n if end < 0 else end + 3
            line += text.count("\n", i, end)
            i = end
            continue
        if c == "<" and i + 1 < n and text[i + 1].isascii() and text[i + 1].isalpha():
            tag, attrs, j = _tag(text, i)
            at = line
            line += text.count("\n", i, j)
            if attrs.get("id"):
                out.symbol("element", attrs["id"], at, f'<{tag} id="{attrs["id"]}">', "")
            if tag in ("input", "select", "textarea") and attrs.get("name"):
                out.add_state(attrs["name"], attrs.get("type") or tag, at, "")
            if tag == "link" and attrs.get("href"):
                out.add_import(attrs["href"])
            if tag == "form" and "action" in attrs:
                out.route(_aupper(attrs.get("method") or "GET"), attrs["action"], attrs.get("id") or attrs.get("name") or "", at, "client")
            if tag == "script" and attrs.get("src"):
                out.add_import(attrs["src"])
            if tag in ("script", "style", "title") and not attrs.get("src"):
                close = low.find("</" + tag, j)
                close = n if close < 0 else close
                body = text[j:close]
                if tag == "title":
                    out.symbol("title", _clip(_collapse(body), 80), at, "", "")
                elif tag == "style" or "json" not in _alower(attrs.get("type", "")):
                    sub = _extract(body, "css" if tag == "style" else "javascript")
                    out.merge(sub, line - 1)
                line += text.count("\n", j, close)
                i = close
                continue
            i = j
            continue
        i += 1


def _css(kept_text: str, out: _Out) -> None:
    buf: list[str] = []
    started = False
    buf_line = 1
    line = 1
    stack: list[str] = []
    i, n = 0, len(kept_text)
    while i < n:
        c = kept_text[i]
        if c in "\"'":
            e = kept_text.find(c, i + 1)
            e = n - 1 if e < 0 else e
            seg = kept_text[i : e + 1]
            if not started:
                started, buf_line = True, line
            line += seg.count("\n")
            buf.append(seg)
            i = e + 1
            continue
        if c == "{":
            pre = _collapse("".join(buf))
            if pre:
                out.symbol("at-rule" if pre.startswith("@") else "selector", _clip(pre, 120), buf_line, pre, stack[-1] if stack else "")
            stack.append(_clip(pre, 120))
            buf, started = [], False
            i += 1
            continue
        if c == ";" or c == "}":
            decl = _collapse("".join(buf))
            if decl.startswith("@import"):
                out.add_import(_strip(decl[7:]))
            elif decl.startswith("--") and ":" in decl:
                k = decl.find(":")
                out.add_state(_strip(decl[:k]), _strip(decl[k + 1 :]), buf_line, stack[-1] if stack else "")
            buf, started = [], False
            if c == "}" and stack:
                stack.pop()
            i += 1
            continue
        if c == "\n":
            line += 1
        elif not started and c not in WS:
            started, buf_line = True, line
        buf.append(c)
        i += 1


# ---------- extract_skeleton ----------


def _language(ext: str) -> str:
    e = _alower(_strip(str(ext or "")))
    dot = e.rfind(".")
    if dot >= 0:
        e = e[dot + 1 :]
    return LANGUAGES.get(e, "text")


def _extract(source: str, language: str) -> _Out:
    lines = source.split("\n")
    out = _Out(language, len(lines))
    text = source
    if len(lines) > MAX_LINES:
        text = "\n".join(lines[:MAX_LINES])
        out.truncated = True
    if language == "html":
        _html(text, out)
        return out
    if language == "text":
        return out
    code, kept = _clean(text, language)
    if language == "python":
        _python(code, kept, out)
    elif language in ("javascript", "typescript"):
        _javascript(code, kept, out)
    elif language == "rust":
        _rust(code, kept, out)
    elif language == "css":
        _css("\n".join(kept), out)
    return out


def extract_skeleton_py(source: str, ext: str) -> dict:
    return _extract(str(source), _language(ext)).result()


# ---------- inspect_artifact_metadata ----------

MAX_STRINGS = 40
MAX_SYMBOLS = 60
MAX_SECTIONS = 64
MAX_ENTRIES = 200


def _u(data: bytes, off: int, size: int, le: bool) -> int:
    """An unsigned integer of `size` bytes at off, or -1 past the end."""
    if off < 0 or off + size > len(data):
        return -1
    return int.from_bytes(data[off : off + size], "little" if le else "big")


def _cstr(data: bytes, off: int, limit: int = 256) -> str:
    """A NUL-terminated ASCII name at off ("" when off is outside); other bytes become "?"."""
    if off < 0 or off >= len(data):
        return ""
    out: list[str] = []
    k = off
    while k < len(data) and k < off + limit and data[k] != 0:
        b = data[k]
        out.append(chr(b) if 32 <= b < 127 else "?")
        k += 1
    return "".join(out)


def _entropy_milli(counts: list[int], total: int) -> int:
    if total <= 0:
        return 0
    h = 0.0
    for c in counts:
        if c > 0:
            p = c / total
            h -= p * math.log2(p)
    return math.floor(h * 1000 + 0.5)


def _entropy(data: bytes) -> float:
    counts = [0] * 256
    for b in range(256):
        counts[b] = data.count(bytes([b]))
    return _entropy_milli(counts, len(data)) / 1000


def _strings(data: bytes) -> tuple[list[str], int]:
    """Runs of at least 6 printable ASCII chars (and tabs): the first 40 distinct, and how many."""
    found: list[str] = []
    seen: set[str] = set()
    total = 0
    run: list[str] = []
    for b in data + b"\x00":
        if 32 <= b < 127 or b == 9:
            run.append(chr(b))
            continue
        if len(run) >= 6:
            total += 1
            s = _clip("".join(run), 80)
            if s not in seen and len(found) < MAX_STRINGS:
                seen.add(s)
                found.append(s)
        run = []
    return found, total


def _section(meta: dict, data: bytes, name: str, off: int, size: int) -> None:
    if len(meta["sections"]) >= MAX_SECTIONS:
        return
    lo = max(0, min(off, len(data)))
    hi = max(lo, min(off + max(size, 0), len(data)))
    big = 2**63 - 1  # the Rust twin writes an i64
    meta["sections"].append({"name": name, "offset": min(off, big), "size": min(size, big), "entropy": _entropy(data[lo:hi])})


def _add(items: list, value: str, cap: int = MAX_SYMBOLS) -> None:
    if value and value not in items and len(items) < cap:
        items.append(value)


ELF_MACHINES = {3: "x86", 0x3E: "x86-64", 0x28: "ARM", 0xB7: "AArch64", 0xF3: "RISC-V", 0x08: "MIPS", 0x14: "PowerPC", 0x15: "PowerPC64"}
ELF_TYPES = {1: "relocatable", 2: "executable", 3: "shared object", 4: "core"}


def _elf(data: bytes, meta: dict) -> None:
    bits = 64 if data[4:5] == b"\x02" else 32
    le = data[5:6] != b"\x02"
    etype, machine = _u(data, 16, 2, le), _u(data, 18, 2, le)
    meta["details"] = f"ELF {bits}-bit {'LSB' if le else 'MSB'}, {ELF_MACHINES.get(machine, f'machine {machine}')}, {ELF_TYPES.get(etype, f'type {etype}')}"
    w = 8 if bits == 64 else 4
    shoff = _u(data, 0x28 if bits == 64 else 0x20, w, le)
    shentsize = _u(data, 0x3A if bits == 64 else 0x2E, 2, le)
    shnum = _u(data, 0x3C if bits == 64 else 0x30, 2, le)
    shstrndx = _u(data, 0x3E if bits == 64 else 0x32, 2, le)
    if shoff <= 0 or shentsize <= 0 or shnum <= 0:
        return
    heads = []
    for k in range(min(shnum, 512)):
        h = shoff + k * shentsize
        name, stype = _u(data, h, 4, le), _u(data, h + 4, 4, le)
        off = _u(data, h + (24 if bits == 64 else 16), w, le)
        size = _u(data, h + (32 if bits == 64 else 20), w, le)
        link = _u(data, h + (40 if bits == 64 else 24), 4, le)
        if min(name, stype, off, size, link) < 0:
            break
        heads.append((name, stype, off, size, link))
    strtab = heads[shstrndx][2] if 0 <= shstrndx < len(heads) else -1
    for name, stype, off, size, link in heads:
        if stype == 0:
            continue
        _section(meta, data, _cstr(data, strtab + name) if strtab >= 0 else "", off, size)
    for name, stype, off, size, link in heads:
        if stype != 11 or not (0 <= link < len(heads)):  # SHT_DYNSYM, its strings in sh_link
            continue
        names = heads[link][2]
        ent = 24 if bits == 64 else 16
        for k in range(1, min(size // ent, 4096)):
            e = off + k * ent
            st_name = _u(data, e, 4, le)
            info = _u(data, e + (4 if bits == 64 else 12), 1, le)
            shndx = _u(data, e + (6 if bits == 64 else 14), 2, le)
            if min(st_name, info, shndx) < 0:
                break
            sym = _cstr(data, names + st_name)
            if not sym:
                continue
            if shndx == 0:
                _add(meta["imports"], sym)
            elif (info >> 4) in (1, 2) and (info & 0xF) in (1, 2):
                _add(meta["exports"], sym)


PE_MACHINES = {0x14C: "x86", 0x8664: "x64", 0xAA64: "ARM64", 0x1C0: "ARM", 0x1C4: "ARMv7"}


def _pe(data: bytes, meta: dict) -> bool:
    pe = _u(data, 0x3C, 4, True)
    if pe < 0 or data[pe : pe + 4] != b"PE\x00\x00":
        return False
    machine, nsec = _u(data, pe + 4, 2, True), _u(data, pe + 6, 2, True)
    optsize, chars = _u(data, pe + 20, 2, True), _u(data, pe + 22, 2, True)
    opt = pe + 24
    magic = _u(data, opt, 2, True)
    plus = magic == 0x20B
    meta["format"] = "pe"
    meta["details"] = f"PE32{'+' if plus else ''} {PE_MACHINES.get(machine, f'machine {machine}')} {'DLL' if chars >= 0 and chars & 0x2000 else 'executable'}"
    dirs = opt + (112 if plus else 96)
    secs = []
    for k in range(min(max(nsec, 0), MAX_SECTIONS)):
        h = opt + optsize + k * 40
        if h + 40 > len(data):
            break
        name = _cstr(data, h, 8)
        vsize, va, rsize, rptr = _u(data, h + 8, 4, True), _u(data, h + 12, 4, True), _u(data, h + 16, 4, True), _u(data, h + 20, 4, True)
        secs.append((va, max(vsize, rsize), rptr))
        _section(meta, data, name, rptr, rsize)

    def off_of(rva: int) -> int:
        for va, size, raw in secs:
            if va <= rva < va + size:
                return rva - va + raw
        return -1

    exp = off_of(_u(data, dirs, 4, True))
    if exp >= 0:
        count, names = _u(data, exp + 24, 4, True), off_of(_u(data, exp + 32, 4, True))
        for k in range(min(max(count, 0), MAX_SYMBOLS)):
            rva = _u(data, names + k * 4, 4, True) if names >= 0 else -1
            if rva < 0:
                break
            _add(meta["exports"], _cstr(data, off_of(rva)))
    imp = off_of(_u(data, dirs + 8, 4, True))
    if imp >= 0:
        for k in range(64):
            d = imp + k * 20
            first, name_rva, thunk = _u(data, d, 4, True), _u(data, d + 12, 4, True), _u(data, d + 16, 4, True)
            if first < 0 or name_rva <= 0 or thunk <= 0:
                break
            dll = _cstr(data, off_of(name_rva))
            table = off_of(first if first > 0 else thunk)
            w = 8 if plus else 4
            for m in range(512):
                entry = _u(data, table + m * w, w, True) if table >= 0 else -1
                if entry <= 0 or len(meta["imports"]) >= MAX_SYMBOLS:
                    break
                if entry >> (63 if plus else 31):
                    continue  # by ordinal
                at = off_of(entry & 0x7FFFFFFF)
                fn = _cstr(data, at + 2) if at >= 0 else ""
                if fn:
                    _add(meta["imports"], f"{dll}!{fn}")
    return True


def _macho(data: bytes, meta: dict) -> None:
    bits = 64 if data[:4] == b"\xcf\xfa\xed\xfe" else 32
    cpu, ncmds = _u(data, 4, 4, True), _u(data, 16, 4, True)
    meta["details"] = f"Mach-O {bits}-bit, cpu type {cpu}"
    off = 32 if bits == 64 else 28
    for _ in range(min(max(ncmds, 0), 256)):
        cmd, size = _u(data, off, 4, True), _u(data, off + 4, 4, True)
        if cmd < 0 or size <= 0:
            break
        if cmd in (0x1, 0x19):  # LC_SEGMENT, LC_SEGMENT_64
            name = _cstr(data, off + 8, 16)
            fileoff = _u(data, off + (40 if cmd == 0x19 else 32), 8 if cmd == 0x19 else 4, True)
            filesize = _u(data, off + (48 if cmd == 0x19 else 36), 8 if cmd == 0x19 else 4, True)
            _section(meta, data, name, fileoff, filesize)
        elif cmd in (0xC, 0x18, 0x8000001F):  # LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB
            _add(meta["imports"], _cstr(data, off + _u(data, off + 8, 4, True)))
        off += size


WASM_SECTIONS = ["custom", "type", "import", "function", "table", "memory", "global", "export", "start", "element", "code", "data", "datacount"]


def _leb(data: bytes, off: int) -> tuple[int, int]:
    """An unsigned LEB128 at off: (value, next offset), or (-1, off) when broken."""
    result, shift, k = 0, 0, off
    while k < len(data) and shift < 35:
        b = data[k]
        result |= (b & 0x7F) << shift
        k += 1
        if not b & 0x80:
            return result, k
        shift += 7
    return -1, off


def _wasm_name(data: bytes, off: int) -> tuple[str, int]:
    size, k = _leb(data, off)
    if size < 0 or k + size > len(data):
        return "", -1
    return "".join(chr(b) if 32 <= b < 127 else "?" for b in data[k : k + size]), k + size


def _wasm(data: bytes, meta: dict) -> None:
    meta["details"] = f"WebAssembly module, version {_u(data, 4, 4, True)}"
    off = 8
    while off < len(data) and len(meta["sections"]) < MAX_SECTIONS:
        sid = data[off]
        size, body = _leb(data, off + 1)
        if size < 0 or body + size > len(data):
            break
        name = WASM_SECTIONS[sid] if sid < len(WASM_SECTIONS) else f"section {sid}"
        if sid == 0:
            custom, _ = _wasm_name(data, body)
            name = f"custom:{custom}"
        _section(meta, data, name, body, size)
        if sid in (2, 7):
            count, k = _leb(data, body)
            for _ in range(min(max(count, 0), MAX_SYMBOLS)):
                if sid == 2:
                    module, k = _wasm_name(data, k)
                    if k < 0:
                        break
                    field, k = _wasm_name(data, k)
                    if k < 0 or k >= len(data):
                        break
                    kind = data[k]
                    k += 1
                    if kind == 0:
                        _, k = _leb(data, k)
                    elif kind == 1:
                        k += 1
                        flag = data[k] if k < len(data) else 0
                        _, k = _leb(data, k + 1)
                        if flag & 1:
                            _, k = _leb(data, k)
                    elif kind == 2:
                        flag = data[k] if k < len(data) else 0
                        _, k = _leb(data, k + 1)
                        if flag & 1:
                            _, k = _leb(data, k)
                    elif kind == 3:
                        k += 2
                    else:
                        break
                    _add(meta["imports"], f"{module}.{field}")
                else:
                    field, k = _wasm_name(data, k)
                    if k < 0 or k >= len(data):
                        break
                    _, k = _leb(data, k + 1)
                    _add(meta["exports"], field)
        off = body + size


def _zip(data: bytes, meta: dict) -> None:
    eocd = -1
    k = len(data) - 22
    while k >= max(0, len(data) - 65557):
        if data[k : k + 4] == b"PK\x05\x06":
            eocd = k
            break
        k -= 1
    total = _u(data, eocd + 10, 2, True) if eocd >= 0 else -1
    cd = _u(data, eocd + 16, 4, True) if eocd >= 0 else -1
    names: list[str] = []
    p = cd
    for _ in range(min(max(total, 0), 65535)):
        if p < 0 or data[p : p + 4] != b"PK\x01\x02":
            break
        size = _u(data, p + 24, 4, True)
        nlen, xlen, clen = _u(data, p + 28, 2, True), _u(data, p + 30, 2, True), _u(data, p + 32, 2, True)
        if min(size, nlen, xlen, clen) < 0:
            break
        raw = data[p + 46 : p + 46 + nlen]
        try:
            name = raw.decode("utf-8")
        except UnicodeDecodeError:
            name = "".join(chr(b) if b < 128 else "?" for b in raw)
        names.append(name)
        if len(meta["entries"]) < MAX_ENTRIES:
            meta["entries"].append({"name": name, "size": size})
        p += 46 + nlen + xlen + clen
    kind = "zip archive"
    if "META-INF/MANIFEST.MF" in names:
        kind = "Java archive (jar)"
    if "AndroidManifest.xml" in names:
        kind = "Android package (apk)"
    if any(n.endswith(".dist-info/WHEEL") for n in names):
        kind = "Python wheel"
    if "[Content_Types].xml" in names:
        kind = "Office Open XML document"
    meta["details"] = f"{kind}, {len(names)} entries"


def _tar(data: bytes, meta: dict) -> None:
    off = 0
    count = 0
    while off + 512 <= len(data) and count < 100000:
        name = _cstr(data, off, 100)
        if not name:
            break
        size_text = _cstr(data, off + 124, 12).strip(" \x00")
        size = 0
        for c in size_text:
            if "0" <= c <= "7":
                size = size * 8 + ord(c) - 48
            else:
                break
        if len(meta["entries"]) < MAX_ENTRIES:
            meta["entries"].append({"name": name, "size": size})
        count += 1
        off += 512 + (size + 511) // 512 * 512
    meta["details"] = f"tar archive, {count} entries"


def _text_notes(text: str, name: str, meta: dict) -> None:
    low = _alower(name)
    lines = text.split("\n")
    longest = max((len(x) for x in lines), default=0)
    if low.endswith(".js") or low.endswith(".mjs") or low.endswith(".cjs"):
        meta["format"] = "javascript"
    elif low.endswith(".json") or low.endswith(".map"):
        meta["format"] = "json"
    if "__webpack_require__" in text or "webpackChunk" in text:
        meta["notes"].append("webpack bundle")
    if "parcelRequire" in text:
        meta["notes"].append("parcel bundle")
    if longest > 1000 or (len(text) > 2000 and len(lines) <= 3):
        meta["notes"].append(f"minified (longest line {longest} chars)")
    for x in lines:
        k = x.find("sourceMappingURL=")
        if k >= 0:
            meta["notes"].append("source map: " + _clip(_strip(x[k + 17 :]), 120))
            break
    meta["details"] = f"text, {len(lines)} lines"


def inspect_artifact_metadata_py(data: bytes, name: str) -> dict:
    data = bytes(data)
    name = str(name or "")
    meta = {"name": name, "size": len(data), "format": "binary", "details": "", "sections": [], "exports": [], "imports": [], "entries": [], "strings": [], "stringCount": 0, "entropy": 0.0, "notes": []}
    meta["entropy"] = _entropy(data)
    head = data[:16]
    if not data:
        meta["format"] = "empty"
        meta["details"] = "empty file"
    elif head.startswith(b"\x7fELF"):
        meta["format"] = "elf"
        _elf(data, meta)
    elif head.startswith(b"MZ") and _pe(data, meta):
        pass
    elif head.startswith(b"MZ"):
        meta["format"] = "dos"
        meta["details"] = "MS-DOS executable"
    elif head[:4] in (b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
        meta["format"] = "macho"
        _macho(data, meta)
    elif head.startswith(b"\xca\xfe\xba\xbe") and 45 <= _u(data, 6, 2, False) < 100:
        meta["format"] = "java-class"
        meta["details"] = f"Java class file, version {_u(data, 6, 2, False)}.{_u(data, 4, 2, False)}"
    elif head.startswith(b"\xca\xfe\xba\xbe"):
        meta["format"] = "macho"
        meta["details"] = f"Mach-O universal binary, {_u(data, 4, 4, False)} architectures"
    elif head.startswith(b"\x00asm"):
        meta["format"] = "wasm"
        _wasm(data, meta)
    elif head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        meta["format"] = "zip"
        _zip(data, meta)
    elif head.startswith(b"\x1f\x8b"):
        meta["format"] = "gzip"
        flags = data[3] if len(data) > 3 else 0
        original = ""
        if flags & 8:
            k = 10
            if flags & 4:
                k += 2 + max(_u(data, 10, 2, True), 0)
            original = _cstr(data, k)
        meta["details"] = "gzip compressed" + (f", original name {original}" if original else "")
    elif data[257:262] == b"ustar":
        meta["format"] = "tar"
        _tar(data, meta)
    elif head.startswith(b"%PDF-"):
        meta["format"] = "pdf"
        meta["details"] = "PDF " + _cstr(data, 5, 8).split("\r")[0].split("\n")[0]
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        meta["format"] = "png"
        meta["details"] = f"PNG image, {_u(data, 16, 4, False)} x {_u(data, 20, 4, False)}"
    elif head.startswith(b"\xff\xd8\xff"):
        meta["format"] = "jpeg"
        meta["details"] = "JPEG image"
    elif head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        meta["format"] = "gif"
        meta["details"] = f"GIF image, {_u(data, 6, 2, True)} x {_u(data, 8, 2, True)}"
    elif head.startswith(b"SQLite format 3\x00"):
        meta["format"] = "sqlite"
        meta["details"] = f"SQLite 3 database, page size {_u(data, 16, 2, False)}"
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text is not None:
            control = sum(1 for c in text if ord(c) < 32 and c not in "\t\n\r\x0c")
            if control * 100 <= len(text):
                meta["format"] = "text"
                _text_notes(text, name, meta)
    meta["strings"], meta["stringCount"] = _strings(data)
    if meta["entropy"] > 7.2 and meta["format"] not in ("zip", "gzip", "png", "jpeg", "gif"):
        meta["notes"].append("high entropy: packed, compressed or encrypted")
    return meta


# ---------- summarize_runtime_trace ----------

MAX_ENDPOINTS = 60
MAX_STATES = 60
MAX_ERRORS = 20
SCHEMA_KEYS = 30
SCHEMA_DEPTH = 4
STATE_KEYS = ("state", "status", "event", "type", "name", "action", "phase", "step")


def _no_constant(name: str):
    raise ValueError(f"not JSON: {name}")


def _finite(text: str) -> float:
    v = float(text)
    if math.isinf(v):
        raise ValueError(f"number out of range: {text}")
    return v


def _finite_int(text: str) -> int:
    v = int(text)
    float(v)  # an integer past the largest double is out of range for serde_json too (OverflowError)
    return v


def _json(text: str):
    """JSON as the Rust twin (serde_json) reads it: no NaN, no Infinity, no
    number too large for a double."""
    try:
        v = json.loads(text, parse_constant=_no_constant, parse_float=_finite, parse_int=_finite_int)
        json.dumps(v, ensure_ascii=False).encode("utf-8")  # a lone surrogate (\ud800) is no JSON for serde_json
        return True, v
    except (ValueError, RecursionError, OverflowError):
        return False, None


def _schema(v, depth: int = 0):
    if isinstance(v, bool):
        return "boolean"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if depth >= SCHEMA_DEPTH:
        return "array" if isinstance(v, list) else "object"
    if isinstance(v, list):
        return [_schema(v[0], depth + 1)] if v else []
    return {k: _schema(v[k], depth + 1) for k in sorted(v)[:SCHEMA_KEYS]}


def _norm_path(url: str) -> tuple[str, str]:
    """(host, path template) of a URL: numbers, UUIDs and long hex ids become {id}."""
    host = ""
    rest = url
    k = rest.find("://")
    if k >= 0:
        rest = rest[k + 3 :]
        slash = rest.find("/")
        host = rest[:slash] if slash >= 0 else rest
        rest = rest[slash:] if slash >= 0 else "/"
    rest = _upto(rest, "?#")
    parts = []
    for seg in rest.split("/"):
        hexish = len(seg) >= 8 and all(("0" <= c <= "9") or ("a" <= _alower(c) <= "f") or c == "-" for c in seg) and any("0" <= c <= "9" for c in seg)
        parts.append("{id}" if (seg and all("0" <= c <= "9" for c in seg)) or hexish else seg)
    return host, "/".join(parts) or "/"


class _Trace:
    def __init__(self, fmt: str):
        self.out = {"format": fmt, "requests": 0, "endpoints": [], "states": [], "errors": [], "hosts": []}
        self.index: dict[str, dict] = {}

    def request(self, method: str, url: str, status: int, req_body, resp_body) -> None:
        host, path = _norm_path(url)
        method = _aupper(method or "GET")
        self.out["requests"] += 1
        if host:
            _add(self.out["hosts"], host, 20)
        key = method + " " + path
        ep = self.index.get(key)
        if ep is None and len(self.out["endpoints"]) < MAX_ENDPOINTS:
            ep = {"method": method, "path": path, "count": 0, "statuses": [], "requestSchema": None, "responseSchema": None}
            self.index[key] = ep
            self.out["endpoints"].append(ep)
        if ep is not None:
            ep["count"] += 1
            if status >= 0 and status not in ep["statuses"]:
                ep["statuses"] = sorted([*ep["statuses"], status])
            if ep["requestSchema"] is None and req_body is not None:
                ep["requestSchema"] = _schema(req_body)
            if ep["responseSchema"] is None and resp_body is not None:
                ep["responseSchema"] = _schema(resp_body)
        self.state(f"{key} → {status}" if status >= 0 else key)
        if status >= 400:
            self.error(f"{key} → {status}")

    def state(self, label: str) -> None:
        label = _clip(_collapse(label), 80)
        states = self.out["states"]
        if label and (not states or states[-1] != label) and len(states) < MAX_STATES:
            states.append(label)

    def error(self, text: str) -> None:
        text = _clip(_collapse(text), 120)
        if text and len(self.out["errors"]) < MAX_ERRORS:
            self.out["errors"].append(text)


def _body(text, mime) -> object:
    """A JSON body as data, or None (not JSON, empty, base64)."""
    if not isinstance(text, str) or not text or "json" not in _alower(mime if isinstance(mime, str) else ""):
        return None
    ok, v = _json(text)
    return v if ok else None


def _int(v) -> int:
    """An integer that fits an i64 (serde_json's as_i64), else -1."""
    return v if isinstance(v, int) and not isinstance(v, bool) and -(2**63) <= v < 2**63 else -1


def _first_str(e: dict, keys) -> str:
    for k in keys:
        v = e
        for part in k.split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if isinstance(v, str) and _strip(v):
            return _strip(v)
    return ""


def _event(tr: _Trace, e) -> None:
    if not isinstance(e, dict):
        return
    url = _first_str(e, ("url", "path", "route", "uri", "request.url"))
    status = _int(e.get("statusCode"))
    if status < 0:
        status = _int(e.get("status"))
    if status < 0 and isinstance(e.get("response"), dict):
        status = _int(e["response"].get("status"))
    if url and (url.startswith("/") or "://" in url):
        req = e.get("body", e.get("payload", e.get("data")))
        if req is None and isinstance(e.get("request"), dict):
            req = e["request"].get("body")
        resp = e["response"].get("body") if isinstance(e.get("response"), dict) else None
        tr.request(_first_str(e, ("method", "httpMethod", "request.method")) or "GET", url, status, req if isinstance(req, (dict, list)) else None, resp if isinstance(resp, (dict, list)) else None)
    elif isinstance(e.get("from"), str) and isinstance(e.get("to"), str):
        tr.state(f"{_strip(e['from'])} → {_strip(e['to'])}")
    else:
        tr.state(_first_str(e, STATE_KEYS))
    level = _alower(_first_str(e, ("level", "severity")))
    if level in ("error", "fatal", "critical") or e.get("error"):
        msg = _first_str(e, ("message", "msg", "error", "error.message"))
        tr.error(msg or _first_str(e, STATE_KEYS) or "error")


def _log_line(tr: _Trace, line: str) -> None:
    words = line.replace('"', " ").split(" ")
    for k, w in enumerate(words):
        if w in HTTP_VERBS and k + 1 < len(words) and (words[k + 1].startswith("/") or words[k + 1].startswith("http")):
            status = -1
            for x in words[k + 2 : k + 8]:
                if len(x) == 3 and all("0" <= c <= "9" for c in x) and 100 <= int(x) <= 599:
                    status = int(x)
                    break
            tr.request(w, words[k + 1], status, None, None)
            break
    else:
        low = _alower(line)
        arrow = line.find("->")
        width = 2
        if arrow < 0:
            arrow, width = line.find("→"), 1
        if arrow > 0:
            a = _strip(line[:arrow]).split(" ")[-1]
            b = _strip(line[arrow + width :]).split(" ")[0] if _strip(line[arrow + width :]) else ""
            if a and b:
                tr.state(f"{a} → {b}")
        else:
            for word in ("state", "status"):
                k = low.find(word)
                if k >= 0 and (k == 0 or not _is_ident(low[k - 1])):
                    j = _skip_spaces(line, k + len(word))
                    if j < len(line) and line[j] in "=:":
                        j = _skip_spaces(line, j + 1)
                        e = j
                        while e < len(line) and (_is_ident(line[e]) or line[e] in "-."):
                            e += 1
                        token = line[j:e]
                        if token and not all("0" <= c <= "9" for c in token):
                            tr.state(token)
                            break
    low = _alower(line)
    if "error" in low or "exception" in low or "fatal" in low or "traceback" in low:
        tr.error(line)


def summarize_runtime_trace_py(text: str) -> dict:
    text = str(text or "")
    if text.startswith("﻿"):
        text = text[1:]
    if not _strip(text):
        return _Trace("empty").out
    ok, doc = _json(text)
    if ok and isinstance(doc, dict) and isinstance(doc.get("log"), dict) and isinstance(doc["log"].get("entries"), list):
        tr = _Trace("har")
        for e in doc["log"]["entries"]:
            if not isinstance(e, dict):
                continue
            req = e.get("request") if isinstance(e.get("request"), dict) else {}
            resp = e.get("response") if isinstance(e.get("response"), dict) else {}
            post = req.get("postData") if isinstance(req.get("postData"), dict) else {}
            content = resp.get("content") if isinstance(resp.get("content"), dict) else {}
            if not isinstance(req.get("url"), str):
                continue
            resp_body = None if content.get("encoding") == "base64" else _body(content.get("text"), content.get("mimeType"))
            tr.request(req.get("method") if isinstance(req.get("method"), str) else "GET", req["url"], _int(resp.get("status")), _body(post.get("text"), post.get("mimeType")), resp_body)
        return tr.out
    if ok and (isinstance(doc, list) or isinstance(doc, dict)):
        events = doc
        fmt = "json-events"
        if isinstance(doc, dict) and isinstance(doc.get("traceEvents"), list):
            events, fmt = doc["traceEvents"], "chrome-trace"
        elif isinstance(doc, dict):
            events = [doc]
        tr = _Trace(fmt)
        for e in events:
            _event(tr, e)
        return tr.out
    lines = [_strip(x) for x in text.split("\n")]
    lines = [x for x in lines if x]
    parsed = []
    for x in lines:
        if x.startswith("{"):
            ok, v = _json(x)
            if ok and isinstance(v, dict):
                parsed.append(v)
    if parsed and len(parsed) * 2 >= len(lines):
        tr = _Trace("jsonl")
        for e in parsed:
            _event(tr, e)
        return tr.out
    tr = _Trace("text-log")
    for x in lines:
        _log_line(tr, x)
    return tr.out


# ---------- the native twin (aw_core) and the startup probe ----------

DECONSTRUCT_PROBES = {
    "skeleton": [
        (
            "py",
            'import os\nfrom fastapi import FastAPI, Depends\n\nAPP_NAME = "todo"\napp = FastAPI()\n\n\nclass Store:\n    limit: int = 50\n\n'
            "    def __init__(self, path):\n        self.path = path\n        self.items = []\n\n    def add(self, item):\n        self.items.append(item)\n        self.save()\n\n"
            '    def save(self):\n        write(self.path, self.items)  # flush\n\n\ndef write(path, items):\n    """Writes.\n    def not_a_def(): pass\n    """\n    return len(items)\n\n\n'
            '@app.get("/api/todos/{id}")\nasync def get_todo(id: int, store: Store = Depends()) -> dict:\n    return store.items[id]\n\n\n@app.route("/legacy", methods=["POST"])\ndef legacy():\n    return write("x", [])\n',
        ),
        (
            "ts",
            "import express from 'express';\nimport { a,\n  b } from \"./util\";\nconst db = require('./db');\n\nexport const PORT = 3000;\nlet count = 0;\n\n"
            "export class TodoService extends Base {\n  private items: Todo[] = [];\n  #secret = 'x';\n  constructor(store) {\n    super();\n    this.store = store;\n  }\n  async list(filter: string): Promise<Todo[]> {\n    return this.load(filter);\n  }\n  load(f) { return helper(f); }\n}\n\n"
            "function helper(x) {\n  // helper('/nope')\n  return `t ${x}`;\n}\n\nexport const handler = async (req, res) => {\n  const [todos, setTodos] = useState([]);\n  const r = await fetch('/api/todos', { method: 'POST' });\n  return helper(r);\n};\n\n"
            "app.get('/api/todos', auth, listTodos);\nrouter.post(\"/api/todos/:id\", (req, res) => res.send(1));\ninterface Todo {\n  id: number;\n  done(): boolean;\n}\nexport { helper as help, count };\nmodule.exports = { helper, PORT };\n",
        ),
        (
            "rs",
            "use std::collections::HashMap;\nuse crate::{model::Todo,\n    db};\n\npub const MAX: usize = 10;\nstatic NAME: &str = \"todo\";\n\n#[derive(Debug)]\npub struct Store {\n    pub items: Vec<Todo>,\n    name: String,\n}\n\n"
            "impl Store {\n    pub fn new() -> Self {\n        Self::with(MAX)\n    }\n    fn with(n: usize) -> Self {\n        let s = 'x'; let r = r#\"raw \" str\"#;\n        Store { items: Vec::with_capacity(n), name: helper(s) }\n    }\n    pub async fn add<'a>(&mut self, t: &'a Todo) {\n        self.items.push(t.clone());\n        self.save();\n    }\n    fn save(&self) {}\n}\n\n"
            '#[get("/todos/{id}")]\nasync fn get_todo(id: u32) -> String {\n    helper(\'a\')\n}\n\nfn helper(c: char) -> String {\n    // helper()\n    c.to_string()\n}\n\npub trait Repo {\n    fn find(&self, id: u32) -> Option<Todo>;\n}\n\n'
            'pub fn app() -> Router {\n    Router::new().route("/api/todos", get(list_todos).post(create_todo))\n}\nmacro_rules! log { () => {} }\n',
        ),
        (
            "html",
            '<!doctype html>\n<html>\n<head>\n  <title>Todo  app</title>\n  <link rel="stylesheet" href="css/style.css">\n  <style>\n    :root { --accent: #e7a83b; }\n    .hero h1 { color: var(--accent); }\n  </style>\n</head>\n<body>\n  <!-- <div id="hidden"></div> -->\n'
            '  <main id="app">\n    <form id="add" action="/api/todos" method="post">\n      <input name="title" type="text">\n      <select name=priority></select>\n    </form>\n  </main>\n  <script src="js/app.js"></script>\n  <script>\n    function boot() { render(); }\n    function render() {\n      fetch("/api/todos").then(r => r.json());\n    }\n  </script>\n</body>\n</html>\n',
        ),
        (
            "css",
            '@import url("base.css");\n/* .commented { } */\n:root {\n  --bg: #fbf7f1;\n  --font: "Segoe UI", system-ui;\n}\nbody, html { margin: 0 }\n@media (max-width: 760px) {\n  .hero { display: grid; --gap: 8px }\n}\n@keyframes fade { from { opacity: 0 } to { opacity: 1 } }\n',
        ),
        ("txt", "just\ntext"),
        ("py", "def f(\n    a,\n    b=1,\n) -> int:\n    return g(a)\ndef g(x): return x\nclass K: pass\n"),
        ("js", "const s = 'unterminated\nfunction ok() { return 1 }\nok();\n"),
    ],
    "artifact": [],  # filled below, once the builders exist
    "trace": [
        "",
        '{"log": {"entries": [{"request": {"method": "GET", "url": "https://api.example.com/api/todos/12?x=1"}, "response": {"status": 200, "content": {"mimeType": "application/json", "text": "{\\"id\\": 12, \\"title\\": \\"a\\", \\"tags\\": [\\"x\\"], \\"done\\": false}"}}},'
        ' {"request": {"method": "POST", "url": "https://api.example.com/api/todos", "postData": {"mimeType": "application/json", "text": "{\\"title\\": \\"b\\", \\"meta\\": {\\"n\\": 1.5, \\"z\\": null}}"}}, "response": {"status": 201, "content": {"mimeType": "application/json", "text": ""}}},'
        ' {"request": {"method": "DELETE", "url": "https://api.example.com/api/todos/3f2a9c1e7b"}, "response": {"status": 404, "content": {}}}]}}',
        '[{"event": "boot"}, {"state": "idle"}, {"from": "idle", "to": "loading"}, {"method": "post", "path": "/login", "statusCode": 302, "body": {"user": "u", "remember": true}}, {"level": "error", "message": "token expired"}, {"status": 500, "url": "/api/x"}]',
        '{"type": "start"}\n{"type": "fetch", "url": "/api/items", "response": {"status": 200, "body": [{"id": 1}]}}\nnot json\n{"type": "done", "error": true}\n',
        '127.0.0.1 - - [10/Oct/2026:13:55:36] "GET /api/todos HTTP/1.1" 200 512\n127.0.0.1 - - "POST /api/todos/42 HTTP/1.1" 500 12\nINFO state=ready\nworker: idle -> busy\nERROR Traceback (most recent call last)\nstatus: 200\n',
        '{"traceEvents": [{"name": "Navigate", "ph": "X"}, {"name": "Navigate"}, {"name": "Paint"}]}',
        "[1, 2",
        "NaN",
    ],
}


def _probe_artifacts() -> list[tuple[bytes, str]]:
    elf = bytearray(256)
    elf[0:4] = b"\x7fELF"
    elf[4], elf[5] = 2, 1
    elf[16:18] = (3).to_bytes(2, "little")
    elf[18:20] = (0x3E).to_bytes(2, "little")
    elf[0x28:0x30] = (64).to_bytes(8, "little")
    elf[0x3A:0x3C] = (64).to_bytes(2, "little")
    elf[0x3C:0x3E] = (2).to_bytes(2, "little")
    elf[0x3E:0x40] = (1).to_bytes(2, "little")
    sh1 = 64 + 64  # the second header: .shstrtab
    elf[sh1 : sh1 + 4] = (1).to_bytes(4, "little")
    elf[sh1 + 4 : sh1 + 8] = (3).to_bytes(4, "little")
    elf[sh1 + 24 : sh1 + 32] = (200).to_bytes(8, "little")
    elf[sh1 + 32 : sh1 + 40] = (11).to_bytes(8, "little")
    elf[200:211] = b"\x00.shstrtab\x00"
    wasm = b"\x00asm\x01\x00\x00\x00" + bytes([2, 11, 1, 3]) + b"env" + bytes([3]) + b"log" + bytes([0, 0]) + bytes([7, 8, 1, 4]) + b"main" + bytes([0, 1])
    return [
        (b"", "empty.bin"),
        (bytes(elf), "libtodo.so"),
        (wasm, "app.wasm"),
        (b"PK\x05\x06" + bytes(18), "empty.zip"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x02\x00\x00\x00\x01\x00", "hero.png"),
        ("console.log('hello world');\n//# sourceMappingURL=app.js.map\n".encode(), "app.js"),
        (bytes(range(256)) * 4, "random.bin"),
        ("città ünïcode strings here".encode() + b"\xff\xfe", "mixed.dat"),
    ]


DECONSTRUCT_PROBES["artifact"] = _probe_artifacts()


def _native_matches(mod) -> bool:
    """aw_core's three functions return what this file returns on every probe."""
    try:
        for ext, src in DECONSTRUCT_PROBES["skeleton"]:
            if json.loads(mod.extract_skeleton_json(src, ext)) != extract_skeleton_py(src, ext):
                return False
        for data, name in DECONSTRUCT_PROBES["artifact"]:
            if json.loads(mod.inspect_artifact_json(data, name)) != inspect_artifact_metadata_py(data, name):
                return False
        for text in DECONSTRUCT_PROBES["trace"]:
            if json.loads(mod.summarize_trace_json(text)) != summarize_runtime_trace_py(text):
                return False
    except Exception:  # noqa: BLE001 -- a broken native module is no module
        return False
    return True


def _load_native():
    try:
        import aw_core  # type: ignore[import-not-found]
    except ImportError:
        return None
    if not all(hasattr(aw_core, f) for f in ("extract_skeleton_json", "inspect_artifact_json", "summarize_trace_json")):
        return None
    return aw_core if _native_matches(aw_core) else None


NATIVE = _load_native()  # None: aw_core missing, older, or off-contract
ENGINE = "rust" if NATIVE is not None else "python"


def extract_skeleton(source: str, ext: str) -> dict:
    if NATIVE is not None:
        try:
            return json.loads(NATIVE.extract_skeleton_json(source, ext))
        except Exception:  # noqa: BLE001 -- e.g. a lone surrogate the native side cannot take
            pass
    return extract_skeleton_py(source, ext)


def inspect_artifact_metadata(data: bytes, name: str) -> dict:
    if NATIVE is not None:
        try:
            return json.loads(NATIVE.inspect_artifact_json(bytes(data), name))
        except Exception:  # noqa: BLE001
            pass
    return inspect_artifact_metadata_py(data, name)


def summarize_runtime_trace(text: str) -> dict:
    if NATIVE is not None:
        try:
            return json.loads(NATIVE.summarize_trace_json(text))
        except Exception:  # noqa: BLE001
            pass
    return summarize_runtime_trace_py(text)


# ---------- what an agent reads ----------


def _owner(name: str) -> str:
    """Run.chat -> "Run.", Store::add -> "Store::", plain -> ""."""
    k = max(name.rfind("."), name.rfind("::") + 1)
    return name[: k + 1] if k > 0 else ""


def render_skeleton(sk: dict, path: str = "") -> str:
    """The skeleton as an agent reads it. Inside a call graph ".x" is a method
    of the caller's own class; a Python method's signature drops its "self"."""
    head = f"SKELETON {path or '(source)'}: {sk['language']}, {sk['lines']} lines" + (", truncated" if sk["truncated"] else "")
    out = [head]
    if sk["imports"]:
        out.append("IMPORTS: " + "; ".join(sk["imports"]))
    if sk["exports"]:
        out.append("EXPORTS: " + ", ".join(sk["exports"]))
    for s in sk["symbols"]:
        sig = s["signature"] or f"{s['kind']} {s['name']}"
        if sk["language"] == "python" and s["kind"] == "method":
            sig = sig.replace("(self, ", "(").replace("(self)", "()").replace("(cls, ", "(").replace("(cls)", "()")
        out.append(("  " if s["parent"] else "") + f"L{s['line']} {sig}")
    if sk["routes"]:
        out.append("ROUTES: " + "; ".join(f"{r['method']} {r['path']}" + (f" -> {r['handler']}" if r["handler"] else "") + (" (calls out)" if r["side"] == "client" else "") for r in sk["routes"]))
    if sk["state"]:
        out.append("STATE: " + "; ".join((f"{s['parent']}." if s["parent"] else "") + s["name"] + (f" = {s['value']}" if s["value"] else "") for s in sk["state"]))
    if sk["calls"]:
        by: dict[str, list[str]] = {}
        for c in sk["calls"]:
            own = _owner(c["from"])
            by.setdefault(c["from"], []).append("." + c["to"][len(own) :] if own and c["to"].startswith(own) else c["to"])
        out.append("CALLS: " + "; ".join(f"{k} -> {', '.join(v)}" for k, v in by.items()))
    return "\n".join(out)


def render_artifact(meta: dict) -> str:
    out = [f"ARTIFACT {meta['name']}: {meta['format']}, {meta['size']} bytes, entropy {meta['entropy']:.3f} bits/byte" + (f" — {meta['details']}" if meta["details"] else "")]
    if meta["sections"]:
        out.append("SECTIONS: " + "; ".join(f"{s['name'] or '?'} @{s['offset']} {s['size']} B (H {s['entropy']:.2f})" for s in meta["sections"]))
    if meta["entries"]:
        more = f" … ({len(meta['entries'])} shown)" if len(meta["entries"]) >= MAX_ENTRIES else ""
        out.append("ENTRIES: " + "; ".join(f"{e['name']} ({e['size']} B)" for e in meta["entries"][:80]) + more)
    if meta["exports"]:
        out.append("EXPORTS: " + ", ".join(meta["exports"]))
    if meta["imports"]:
        out.append("IMPORTS: " + ", ".join(meta["imports"]))
    if meta["strings"]:
        out.append(f"STRINGS ({meta['stringCount']} found, first {len(meta['strings'])}): " + " | ".join(meta["strings"]))
    if meta["notes"]:
        out.append("NOTES: " + "; ".join(meta["notes"]))
    return "\n".join(out)


def render_trace(tr: dict) -> str:
    out = [f"TRACE: {tr['format']}, {tr['requests']} HTTP requests" + (f", hosts {', '.join(tr['hosts'])}" if tr["hosts"] else "")]
    for e in tr["endpoints"]:
        line = f"  {e['method']} {e['path']} ×{e['count']}" + (f" -> {', '.join(str(s) for s in e['statuses'])}" if e["statuses"] else "")
        if e["requestSchema"] is not None:
            line += f" | request {json.dumps(e['requestSchema'], ensure_ascii=False)}"
        if e["responseSchema"] is not None:
            line += f" | response {json.dumps(e['responseSchema'], ensure_ascii=False)}"
        out.append(line)
    if tr["states"]:
        out.append("STATES: " + " ⇒ ".join(tr["states"]))
    if tr["errors"]:
        out.append("ERRORS: " + " | ".join(tr["errors"]))
    return "\n".join(out)
