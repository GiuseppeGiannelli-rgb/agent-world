"""Spec 11 T06-T10: the Reverse Engineering engine and the dual-mode run.

T06: deconstructor.py and its Rust twin (extract_skeleton,
inspect_artifact_metadata, summarize_runtime_trace), the startup probe.
T07: the tools scan_target_tree, extract_code_skeleton, write_blueprint.
T08: the reverse team in the config, the dictionaries, the office, the skill.
T09: the CEO's intent (direct_build, reverse_only, deconstruct_and_build) and
the clean-room handover (Deconstruct -> Handover -> Build -> Parity QA).
T10: the demo simulator plays the three missions in the five languages."""

import ast
import gzip
import io
import json
import tarfile
import types
import zipfile
from pathlib import Path

import pytest

from backend import deconstructor as d

REPO = Path(__file__).resolve().parents[2]
PROBE: dict[str, str] = {}
for _ext, _src in d.DECONSTRUCT_PROBES["skeleton"]:
    PROBE.setdefault(_ext, _src)  # the first probe of each extension is the full sample


def sk(src: str, ext: str) -> dict:
    return d.extract_skeleton_py(src, ext)


def names(skel: dict, kind: str | None = None) -> list[str]:
    return [s["name"] for s in skel["symbols"] if kind is None or s["kind"] == kind]


def sym(skel: dict, name: str) -> dict:
    return next(s for s in skel["symbols"] if s["name"] == name)


def calls(skel: dict) -> set[tuple[str, str]]:
    return {(c["from"], c["to"]) for c in skel["calls"]}


def state(skel: dict) -> dict[str, str]:
    return {(f"{s['parent']}." if s["parent"] else "") + s["name"]: s["value"] for s in skel["state"]}


def routes(skel: dict) -> set[tuple]:
    return {(r["method"], r["path"], r["handler"], r["side"]) for r in skel["routes"]}


# ---------- T06: extract_skeleton ----------


def test_python_signatures_routes_state_and_calls_without_the_bodies():
    s = sk(PROBE["py"], "py")
    assert s["language"] == "python" and s["lines"] == PROBE["py"].count("\n") + 1 and not s["truncated"]
    assert s["imports"] == ["import os", "from fastapi import FastAPI, Depends"]
    assert [(x["kind"], x["name"], x["parent"], x["line"]) for x in s["symbols"]] == [
        ("class", "Store", "", 8),
        ("method", "__init__", "Store", 11),
        ("method", "add", "Store", 15),
        ("method", "save", "Store", 19),
        ("function", "write", "", 23),
        ("function", "get_todo", "", 31),
        ("function", "legacy", "", 36),
    ]
    assert sym(s, "get_todo")["signature"] == "async def get_todo(id: int, store: Store = Depends()) -> dict"
    assert "not_a_def" not in names(s)  # inside a docstring
    assert routes(s) == {("GET", "/api/todos/{id}", "get_todo", "server"), ("POST", "/legacy", "legacy", "server")}
    assert state(s) == {"APP_NAME": '"todo"', "app": "FastAPI()", "Store.limit": "50", "Store.self.path": "path", "Store.self.items": "[]"}
    assert calls(s) == {("Store.add", "Store.save"), ("Store.save", "write"), ("legacy", "write")}
    assert s["exports"] == ["Store", "write", "get_todo", "legacy"]
    text = d.render_skeleton(s, "todo.py")
    assert "self.items.append" not in text and "return len(items)" not in text  # no bodies
    assert "L11 def __init__(path)" in text and "CALLS: Store.add -> .save" in text


def test_python_follows_the_real_ast_on_the_backend_sources():
    """Every class and def of real files, at its line, against Python's own parser."""
    for rel in ("backend/backend/run.py", "backend/backend/tasker.py", "backend/backend/router/index.py", "backend/backend/deconstructor.py", "backend/backend/brain.py"):
        src = (REPO / rel).read_text(encoding="utf-8")
        want = sorted((n.name, n.lineno) for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        got = sorted((x["name"], x["line"]) for x in sk(src, "py")["symbols"])
        assert got == want, rel


def test_typescript_classes_interfaces_exports_routes_and_react_state():
    s = sk(PROBE["ts"], "ts")
    assert s["language"] == "typescript"
    assert s["imports"] == ["import express from 'express'", 'import { a, b } from "./util"', "const db = require('./db')"]
    assert set(s["exports"]) == {"PORT", "TodoService", "handler", "help", "count", "helper"}
    assert [(x["kind"], x["name"], x["parent"]) for x in s["symbols"]] == [
        ("class", "TodoService", ""),
        ("method", "constructor", "TodoService"),
        ("method", "list", "TodoService"),
        ("method", "load", "TodoService"),
        ("function", "helper", ""),
        ("function", "handler", ""),
        ("interface", "Todo", ""),
    ]  # done() inside the interface is no method
    assert sym(s, "list")["signature"] == "async list(filter: string): Promise<Todo[]>"
    assert routes(s) == {("POST", "/api/todos", "", "client"), ("GET", "/api/todos", "listTodos", "server"), ("POST", "/api/todos/:id", "", "server")}
    st = state(s)
    assert st["PORT"] == "3000" and st["count"] == "0" and st["TodoService.items"] == "[]" and st["TodoService.#secret"] == "'x'"
    assert st["TodoService.this.store"] == "store" and st["handler.todos"] == "useState([])"
    assert calls(s) == {("TodoService.list", "TodoService.load"), ("TodoService.load", "helper"), ("handler", "helper")}
    assert "helper('/nope')" not in json.dumps(s)  # a comment is no call and no route


def test_rust_impls_traits_fields_attributes_and_axum_routes():
    s = sk(PROBE["rs"], "rs")
    assert s["imports"] == ["use std::collections::HashMap", "use crate::{model::Todo, db}"]
    assert set(s["exports"]) == {"MAX", "Store", "Repo", "app"}
    assert [(x["kind"], x["name"], x["parent"]) for x in s["symbols"]] == [
        ("struct", "Store", ""),
        ("impl", "Store", ""),
        ("method", "new", "Store"),
        ("method", "with", "Store"),
        ("method", "add", "Store"),
        ("method", "save", "Store"),
        ("function", "get_todo", ""),
        ("function", "helper", ""),
        ("trait", "Repo", ""),
        ("method", "find", "Repo"),
        ("function", "app", ""),
        ("macro", "log", ""),
    ]
    assert sym(s, "add")["signature"] == "pub async fn add<'a>(&mut self, t: &'a Todo)"  # a lifetime is no char literal
    assert routes(s) == {("GET", "/todos/{id}", "get_todo", "server"), ("GET", "/api/todos", "list_todos", "server"), ("POST", "/api/todos", "create_todo", "server")}
    assert state(s) == {"MAX": "10", "NAME": '"todo"', "Store.items": "Vec<Todo>", "Store.name": "String"}
    assert calls(s) == {("Store::new", "Store::with"), ("Store::with", "helper"), ("Store::add", "Store::save"), ("get_todo", "helper")}


def test_a_rust_header_on_many_lines_still_owns_its_body():
    src = "impl Repo for Db {\n    pub fn find(\n        &self,\n        id: u32,\n    ) -> Option<Todo>\n    where Self: Sized\n    {\n        self.load(id)\n    }\n    fn load(&self, id: u32) -> Option<Todo> { None }\n}\n"
    s = sk(src, "rs")
    assert sym(s, "find")["signature"] == "pub fn find(&self, id: u32) -> Option<Todo> where Self: Sized"
    assert calls(s) == {("Db::find", "Db::load")}


def test_html_pages_with_their_scripts_styles_forms_and_fields():
    s = sk(PROBE["html"], "html")
    assert s["imports"] == ["css/style.css", "js/app.js"]
    kinds = [(x["kind"], x["name"], x["line"]) for x in s["symbols"]]
    assert kinds == [("title", "Todo app", 4), ("selector", ":root", 7), ("selector", ".hero h1", 8), ("element", "app", 13), ("element", "add", 14), ("function", "boot", 21), ("function", "render", 22)]
    assert "hidden" not in json.dumps(s)  # inside an HTML comment
    assert routes(s) == {("POST", "/api/todos", "add", "client"), ("GET", "/api/todos", "", "client")}
    assert state(s) == {":root.--accent": "#e7a83b", "title": "text", "priority": "select"}
    assert calls(s) == {("boot", "render")}


def test_css_selectors_at_rules_variables_and_imports():
    s = sk(PROBE["css"], "css")
    assert s["imports"] == ['url("base.css")']
    assert [(x["kind"], x["name"], x["parent"]) for x in s["symbols"]] == [
        ("selector", ":root", ""),
        ("selector", "body, html", ""),
        ("at-rule", "@media (max-width: 760px)", ""),
        ("selector", ".hero", "@media (max-width: 760px)"),
        ("at-rule", "@keyframes fade", ""),
        ("selector", "from", "@keyframes fade"),
        ("selector", "to", "@keyframes fade"),
    ]
    assert state(s) == {":root.--bg": "#fbf7f1", ":root.--font": '"Segoe UI", system-ui', ".hero.--gap": "8px"}
    assert ".commented" not in json.dumps(s)


@pytest.mark.parametrize(("ext", "language"), [("PY", "python"), (".tsx", "typescript"), ("src/main.rs", "rust"), ("page.HTM", "html"), ("x.scss", "css"), ("mjs", "javascript"), ("go", "text"), ("", "text")])
def test_the_language_follows_the_extension(ext, language):
    assert sk("x", ext)["language"] == language


def test_strings_that_look_like_code_and_odd_headers():
    s = sk(PROBE["py"].replace("APP_NAME", "URL").replace('"todo"', '"def not_me(): pass  # x"'), "py")
    assert "not_me" not in names(s) and state(s)["URL"] == '"def not_me(): pass # x"'
    multi = sk("def f(\n    a,\n    b=1,\n) -> int:\n    return g(a)\ndef g(x): return x\nclass K: pass\n", "py")
    assert [(x["name"], x["line"], x["signature"]) for x in multi["symbols"]] == [("f", 1, "def f(a, b=1) -> int"), ("g", 6, "def g(x)"), ("K", 7, "class K")]
    assert calls(multi) == {("f", "g")}
    js = sk("const s = 'unterminated\nfunction ok() { return 1 }\nok();\n", "js")
    assert names(js) == ["ok"]  # a broken string ends with its line


def test_the_limits_keep_the_skeleton_small_and_say_so():
    many = "\n".join(f"def f{i}(x):\n    return x" for i in range(400))
    s = sk(many, "py")
    assert len(s["symbols"]) == d.CAPS["symbols"] and s["truncated"] and len(s["exports"]) == d.CAPS["exports"]
    long = "x = 1\n" * (d.MAX_LINES + 5)
    t = sk(long, "py")
    assert t["lines"] == d.MAX_LINES + 6 and t["truncated"]


def test_the_skeleton_is_about_a_tenth_of_the_real_files():
    """Measured on the repository's own code: the skeleton an agent reads is
    ~10% of the file read_file would give (read_file also stops at 12000 chars)."""
    total_src = total_sk = 0
    for rel in ("backend/backend/run.py", "backend/backend/tasker.py", "backend/backend/router/index.py", "public/js/main.js", "public/js/world/world.js", "public/js/world/office.js", "crates/aw_core/src/lib.rs", "scripts/browser-test.js"):
        src = (REPO / rel).read_text(encoding="utf-8")
        text = d.render_skeleton(sk(src, Path(rel).suffix), rel)
        assert len(text) < 0.16 * len(src), rel
        total_src += len(src)
        total_sk += len(text)
    assert total_sk < 0.115 * total_src


# ---------- T06: inspect_artifact_metadata ----------


def elf64() -> bytes:
    data = bytearray(0x200)
    data[0:4], data[4], data[5] = b"\x7fELF", 2, 1
    data[16:18], data[18:20] = (3).to_bytes(2, "little"), (0xB7).to_bytes(2, "little")
    data[0x28:0x30] = (0x100).to_bytes(8, "little")
    data[0x3A:0x3C], data[0x3C:0x3E], data[0x3E:0x40] = (64).to_bytes(2, "little"), (4).to_bytes(2, "little"), (3).to_bytes(2, "little")
    shstr = b"\x00.dynsym\x00.dynstr\x00.shstrtab\x00"
    dynstr = b"\x00todo_add\x00puts\x00"
    data[0x40 : 0x40 + len(shstr)] = shstr
    data[0x80 : 0x80 + len(dynstr)] = dynstr
    for k, (name, info, shndx) in enumerate([(0, 0, 0), (1, 0x12, 5), (10, 0x12, 0)]):
        e = 0xA0 + k * 24
        data[e : e + 4] = name.to_bytes(4, "little")
        data[e + 4] = info
        data[e + 6 : e + 8] = shndx.to_bytes(2, "little")
    for k, (name, stype, off, size, link) in enumerate([(0, 0, 0, 0, 0), (1, 11, 0xA0, 72, 2), (9, 3, 0x80, len(dynstr), 0), (17, 3, 0x40, len(shstr), 0)]):
        h = 0x100 + k * 64
        data[h : h + 4], data[h + 4 : h + 8] = name.to_bytes(4, "little"), stype.to_bytes(4, "little")
        data[h + 24 : h + 32], data[h + 32 : h + 40], data[h + 40 : h + 44] = off.to_bytes(8, "little"), size.to_bytes(8, "little"), link.to_bytes(4, "little")
    return bytes(data)


def pe64() -> bytes:
    data = bytearray(0x400)
    put = lambda off, value, size: data.__setitem__(slice(off, off + size), value.to_bytes(size, "little"))  # noqa: E731
    data[0:2] = b"MZ"
    put(0x3C, 0x40, 4)
    pe, opt = 0x40, 0x58
    data[pe : pe + 4] = b"PE\x00\x00"
    put(pe + 4, 0x8664, 2)
    put(pe + 6, 1, 2)
    put(pe + 20, 240, 2)
    put(pe + 22, 0x2022, 2)
    put(opt, 0x20B, 2)
    put(opt + 112, 0x1000, 4)  # the export directory
    put(opt + 120, 0x1100, 4)  # the import directory
    sec = opt + 240
    data[sec : sec + 8] = b".rdata\x00\x00"
    put(sec + 8, 0x200, 4)
    put(sec + 12, 0x1000, 4)
    put(sec + 16, 0x200, 4)
    put(sec + 20, 0x200, 4)
    off = lambda rva: rva - 0x1000 + 0x200  # noqa: E731
    put(off(0x1000) + 24, 2, 4)
    put(off(0x1000) + 32, 0x1040, 4)
    put(off(0x1040), 0x1060, 4)
    put(off(0x1044), 0x1070, 4)
    data[off(0x1060) : off(0x1060) + 9] = b"todo_add\x00"
    data[off(0x1070) : off(0x1070) + 9] = b"todo_del\x00"
    put(off(0x1100), 0x1140, 4)
    put(off(0x1100) + 12, 0x1180, 4)
    put(off(0x1100) + 16, 0x1140, 4)
    put(off(0x1140), 0x11A0, 8)
    data[off(0x1180) : off(0x1180) + 13] = b"KERNEL32.dll\x00"
    data[off(0x11A0) + 2 : off(0x11A0) + 14] = b"ExitProcess\x00"
    return bytes(data)


def zipped(names_: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n, content in names_.items():
            z.writestr(n, content)
    return buf.getvalue()


def test_elf_sections_and_dynamic_symbols():
    m = d.inspect_artifact_metadata_py(elf64(), "libtodo.so")
    assert m["format"] == "elf" and m["details"] == "ELF 64-bit LSB, AArch64, shared object"
    assert [s["name"] for s in m["sections"]] == [".dynsym", ".dynstr", ".shstrtab"]
    assert m["exports"] == ["todo_add"] and m["imports"] == ["puts"]


def test_pe_exports_and_imports_by_dll():
    m = d.inspect_artifact_metadata_py(pe64(), "todo.dll")
    assert m["format"] == "pe" and m["details"] == "PE32+ x64 DLL"
    assert [(s["name"], s["offset"], s["size"]) for s in m["sections"]] == [(".rdata", 0x200, 0x200)]
    assert m["exports"] == ["todo_add", "todo_del"] and m["imports"] == ["KERNEL32.dll!ExitProcess"]


def test_wasm_imports_exports_and_sections():
    data = dict(d.DECONSTRUCT_PROBES["artifact"])
    wasm = next(b for b, n in d.DECONSTRUCT_PROBES["artifact"] if n == "app.wasm")
    m = d.inspect_artifact_metadata_py(wasm, "app.wasm")
    assert data and m["format"] == "wasm" and m["details"] == "WebAssembly module, version 1"
    assert [s["name"] for s in m["sections"]] == ["import", "export"] and m["imports"] == ["env.log"] and m["exports"] == ["main"]


def test_archives_list_their_entries_and_their_kind():
    jar = d.inspect_artifact_metadata_py(zipped({"META-INF/MANIFEST.MF": "Manifest-Version: 1.0", "app/Main.class": b"\xca\xfe\xba\xbe"}), "app.jar")
    assert jar["format"] == "zip" and jar["details"] == "Java archive (jar), 2 entries" and [e["name"] for e in jar["entries"]] == ["META-INF/MANIFEST.MF", "app/Main.class"]
    whl = d.inspect_artifact_metadata_py(zipped({"todo/__init__.py": "", "todo-1.0.dist-info/WHEEL": "Wheel-Version: 1.0"}), "todo.whl")
    assert whl["details"] == "Python wheel, 2 entries"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        info = tarfile.TarInfo("package/package.json")
        info.size = 2
        t.addfile(info, io.BytesIO(b"{}"))
    tar = d.inspect_artifact_metadata_py(buf.getvalue(), "todo.tar")
    assert tar["format"] == "tar" and tar["entries"] == [{"name": "package/package.json", "size": 2}]
    gz = d.inspect_artifact_metadata_py(gzip.compress(b"x" * 100, mtime=0), "x.gz")
    assert gz["format"] == "gzip" and "high entropy" not in " ".join(gz["notes"])


def test_bundles_entropy_and_strings():
    bundle = ("(()=>{var __webpack_require__={};" + "a" * 1500 + "})();\n//# sourceMappingURL=main.js.map\n").encode()
    m = d.inspect_artifact_metadata_py(bundle, "main.js")
    assert m["format"] == "javascript" and "webpack bundle" in m["notes"] and "source map: main.js.map" in m["notes"]
    assert any(n.startswith("minified") for n in m["notes"])
    assert d.inspect_artifact_metadata_py(bytes(64), "zeros.bin")["entropy"] == 0.0
    noise = d.inspect_artifact_metadata_py(bytes(range(256)) * 8, "noise.bin")
    assert noise["entropy"] == 8.0 and "high entropy: packed, compressed or encrypted" in noise["notes"]
    m = d.inspect_artifact_metadata_py(b"\x00\x01secret_api_endpoint=/v2/orders\x00\xffshort\x00another readable string", "blob.bin")
    assert m["format"] == "binary" and m["strings"] == ["secret_api_endpoint=/v2/orders", "another readable string"] and m["stringCount"] == 2
    assert d.inspect_artifact_metadata_py(b"", "empty")["format"] == "empty"


def test_truncated_or_lying_headers_never_raise():
    for blob in (b"\x7fELF\x02\x01" + b"\xff" * 80, b"MZ" + b"\xff" * 100, b"\x00asm\x01\x00\x00\x00\x02\xff\xff\xff\xff\x0f", b"PK\x03\x04" + b"\x00" * 10, b"\xca\xfe\xba\xbe\x00\x00\x00\x34", b"\xcf\xfa\xed\xfe" + b"\xff" * 40):
        m = d.inspect_artifact_metadata_py(blob, "broken")
        assert m["size"] == len(blob)
    assert d.render_artifact(d.inspect_artifact_metadata_py(pe64(), "todo.dll")).startswith("ARTIFACT todo.dll: pe, 1024 bytes")


# ---------- T06: summarize_runtime_trace ----------

TRACES = d.DECONSTRUCT_PROBES["trace"]


def test_a_har_file_becomes_endpoints_schemas_and_a_sequence():
    t = d.summarize_runtime_trace_py(TRACES[1])
    assert t["format"] == "har" and t["requests"] == 3 and t["hosts"] == ["api.example.com"]
    assert [(e["method"], e["path"], e["statuses"]) for e in t["endpoints"]] == [("GET", "/api/todos/{id}", [200]), ("POST", "/api/todos", [201]), ("DELETE", "/api/todos/{id}", [404])]
    assert t["endpoints"][0]["responseSchema"] == {"done": "boolean", "id": "number", "tags": ["string"], "title": "string"}
    assert t["endpoints"][1]["requestSchema"] == {"meta": {"n": "number", "z": "null"}, "title": "string"} and t["endpoints"][1]["responseSchema"] is None
    assert t["states"] == ["GET /api/todos/{id} → 200", "POST /api/todos → 201", "DELETE /api/todos/{id} → 404"]
    assert t["errors"] == ["DELETE /api/todos/{id} → 404"]


def test_json_events_jsonl_chrome_traces_and_text_logs():
    ev = d.summarize_runtime_trace_py(TRACES[2])
    assert ev["format"] == "json-events" and ev["states"] == ["boot", "idle", "idle → loading", "POST /login → 302", "GET /api/x → 500"]
    assert ev["endpoints"][0]["requestSchema"] == {"remember": "boolean", "user": "string"} and ev["errors"] == ["token expired", "GET /api/x → 500"]
    jl = d.summarize_runtime_trace_py(TRACES[3])
    assert jl["format"] == "jsonl" and jl["states"] == ["start", "GET /api/items → 200", "done"] and jl["endpoints"][0]["responseSchema"] == [{"id": "number"}]
    log = d.summarize_runtime_trace_py(TRACES[4])
    assert log["format"] == "text-log" and [(e["method"], e["path"], e["statuses"]) for e in log["endpoints"]] == [("GET", "/api/todos", [200]), ("POST", "/api/todos/{id}", [500])]
    assert log["states"] == ["GET /api/todos → 200", "POST /api/todos/{id} → 500", "ready", "idle → busy"]  # "status: 200" is no state
    assert log["errors"] == ["POST /api/todos/{id} → 500", "ERROR Traceback (most recent call last)"]
    chrome = d.summarize_runtime_trace_py(TRACES[5])
    assert chrome["format"] == "chrome-trace" and chrome["states"] == ["Navigate", "Paint"]


@pytest.mark.parametrize("text", ["", "   \n", "[1, 2", "NaN", '{"a": Infinity}', '{"big": 1e400}', '{"s": "\\ud800"}', "1" * 400])
def test_what_is_not_json_for_serde_is_not_json_here_either(text):
    t = d.summarize_runtime_trace_py(text)
    assert t["format"] in ("empty", "text-log") and t["requests"] == 0


# ---------- T06: the native twin and its probe ----------


def test_the_probes_cover_every_language_format_and_trace_kind():
    exts = {d._language(e) for e, _ in d.DECONSTRUCT_PROBES["skeleton"]}
    assert exts == {"python", "typescript", "rust", "html", "css", "text", "javascript"}
    formats = {d.inspect_artifact_metadata_py(b, n)["format"] for b, n in d.DECONSTRUCT_PROBES["artifact"]}
    assert {"empty", "elf", "wasm", "zip", "png", "javascript", "binary"} <= formats
    kinds = {d.summarize_runtime_trace_py(t)["format"] for t in TRACES}
    assert kinds == {"empty", "har", "json-events", "jsonl", "text-log", "chrome-trace"}


class FakeNative:
    """aw_core as the probe sees it: the Python results as JSON, one of them changed on demand."""

    def __init__(self, wrong: str = ""):
        self.wrong = wrong

    def _out(self, kind: str, value: dict) -> str:
        if kind == self.wrong:
            value = {**value, "truncated" if kind == "skeleton" else "format": "changed"}
        return json.dumps(value)

    def extract_skeleton_json(self, source, ext):
        return self._out("skeleton", d.extract_skeleton_py(source, ext))

    def inspect_artifact_json(self, data, name):
        return self._out("artifact", d.inspect_artifact_metadata_py(data, name))

    def summarize_trace_json(self, text):
        return self._out("trace", d.summarize_runtime_trace_py(text))


def test_the_startup_probe_takes_only_a_twin_that_matches_on_every_probe(monkeypatch):
    assert d._native_matches(FakeNative())
    for wrong in ("skeleton", "artifact", "trace"):
        assert not d._native_matches(FakeNative(wrong)), wrong
    monkeypatch.setitem(__import__("sys").modules, "aw_core", types.SimpleNamespace(tokenize=lambda s: []))
    assert d._load_native() is None  # an aw_core built before T06


def test_the_public_functions_fall_back_to_python_when_the_native_call_fails(monkeypatch):
    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("native crash")

    monkeypatch.setattr(d, "NATIVE", Broken())
    assert d.extract_skeleton("def f(): pass", "py") == d.extract_skeleton_py("def f(): pass", "py")
    assert d.inspect_artifact_metadata(b"abc", "x") == d.inspect_artifact_metadata_py(b"abc", "x")
    assert d.summarize_runtime_trace("GET /x 200") == d.summarize_runtime_trace_py("GET /x 200")


def test_the_rust_twin_is_wired_into_the_module():
    lib = (REPO / "crates/aw_core/src/lib.rs").read_text(encoding="utf-8")
    twin = (REPO / "crates/aw_core/src/deconstruct.rs").read_text(encoding="utf-8")
    for fn in ("extract_skeleton_json", "inspect_artifact_json", "summarize_trace_json"):
        assert f"pub fn {fn}(" in twin and f"wrap_pyfunction!({fn}, m)" in lib
    assert "serde_json" in (REPO / "crates/aw_core/Cargo.toml").read_text(encoding="utf-8")


def _native():
    try:
        import aw_core as mod  # type: ignore[import-not-found]
    except ImportError:
        return None
    return mod if hasattr(mod, "extract_skeleton_json") else None


@pytest.mark.skipif(_native() is None, reason="aw_core with the T06 twin is not compiled on this machine")
def test_the_compiled_twin_matches_python_exactly():
    mod = _native()
    for ext, src in d.DECONSTRUCT_PROBES["skeleton"]:
        assert json.loads(mod.extract_skeleton_json(src, ext)) == d.extract_skeleton_py(src, ext), ext
    for rel in ("backend/backend/run.py", "public/js/main.js", "crates/aw_core/src/lib.rs", "public/index.html", "public/css/app.css"):
        src = (REPO / rel).read_text(encoding="utf-8")
        assert json.loads(mod.extract_skeleton_json(src, Path(rel).suffix)) == d.extract_skeleton_py(src, Path(rel).suffix), rel
    for blob, name in [*d.DECONSTRUCT_PROBES["artifact"], (elf64(), "x.so"), (pe64(), "x.dll"), (zipped({"a.txt": "1"}), "a.zip")]:
        assert json.loads(mod.inspect_artifact_json(blob, name)) == d.inspect_artifact_metadata_py(blob, name), name
    for text in TRACES:
        assert json.loads(mod.summarize_trace_json(text)) == d.summarize_runtime_trace_py(text)
    assert d.ENGINE == "rust"
