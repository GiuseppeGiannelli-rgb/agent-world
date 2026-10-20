"""Spec 11 T06-T10: the Reverse Engineering engine and the dual-mode run.

T06: deconstructor.py and its Rust twin (extract_skeleton,
inspect_artifact_metadata, summarize_runtime_trace), the startup probe.
T07: the tools scan_target_tree, extract_code_skeleton, write_blueprint.
T08: the reverse team in the config, the dictionaries, the office, the skill.
T09: the CEO's intent (direct_build, reverse_only, deconstruct_and_build) and
the clean-room handover (Deconstruct -> Handover -> Build -> Parity QA).
T10: the demo simulator plays the three missions in the five languages."""

import ast
import asyncio
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


# ---------- T07: the tools of the Reverse Engineering team ----------

from test_attachments import ctx  # noqa: E402,F401 -- the run fixture (FAST demo, no keys)
from test_runs import FakeRun, app_and_store, client  # noqa: E402,F401 -- the route fixtures

from backend import tools  # noqa: E402
from backend.tools import Workspace  # noqa: E402

BLUEPRINT_OK = {
    "name": "todo-board",
    "summary": "A small to-do board: a JSON API and a one-page front-end.",
    "architecture": {"style": "single page + JSON API", "components": [{"name": "API server", "kind": "service", "responsibility": "serves the to-dos", "files": ["target/server.js"]}, "Front-end"], "stack": ["JavaScript", "express"]},
    "dataModels": [{"name": "Todo", "fields": [{"name": "id", "type": "number", "required": True}, {"name": "title", "type": "string"}, "done"]}],
    "endpoints": [{"method": "get", "path": "/api/todos", "purpose": "list"}, {"method": "POST", "path": "/api/todos", "request": {"title": "string"}}],
    "businessRules": ["A title is required and at most 120 characters.", {"rule": "A new to-do is open."}],
    "edgeCases": ["An unknown id answers 404."],
    "parityCriteria": ["POST /api/todos with an empty title answers 400.", "GET /api/todos lists the to-dos in creation order."],
    "secret": "dropped: not a blueprint field",
}


def write_tree(root: Path, files: dict) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def test_scan_target_tree_maps_languages_entry_points_dependencies_and_sizes(tmp_path):
    write_tree(tmp_path, {
        "target/package.json": json.dumps({"main": "server.js", "bin": {"todo": "cli.js"}, "scripts": {"start": "node server.js"}, "dependencies": {"express": "^4.19.2"}, "devDependencies": {"jest": "29"}}),
        "target/server.js": "const x = 1;\n",
        "target/api/pyproject.toml": '[project]\ndependencies = ["fastapi>=0.110"]\n[project.scripts]\ntodo = "api.main:run"\n',
        "target/api/requirements.txt": "uvicorn==0.30  # server\n-e .\n",
        "target/api/main.py": "def run(): pass\n",
        "target/core/Cargo.toml": '[package]\nname = "core"\n[dependencies]\nserde = { version = "1" }\nregex = "1.10"\n[[bin]]\nname = "core"\npath = "src/main.rs"\n',
        "target/core/src/main.rs": "fn main() {}\n",
        "target/core/target/CACHEDIR.TAG": "cargo build output",
        "target/core/target/debug/big.bin": b"\x00" * 1000,
        "target/node_modules/express/index.js": "module.exports = 1;\n",
        "target/.git/HEAD": "ref: refs/heads/main\n",
        "target/dist/app.min.js": "!function(){}();\n",
        "target/logs/session.har": "{}",
    })
    scan = tools.scan_tree(Workspace(tmp_path), "target")
    paths = [f["path"] for f in scan["files"]]
    assert "target/node_modules/express/index.js" not in paths and "target/.git/HEAD" not in paths and "target/core/target/debug/big.bin" not in paths
    assert scan["skipped"] == {".git": 1, "node_modules": 1, "target": 1} and "target/dist/app.min.js" in paths
    assert {"JavaScript", "Python", "Rust", "TOML", "JSON", "trace"} <= set(scan["languages"])
    assert "target/package.json: main server.js" in scan["entries"] and "target/package.json: bin cli.js" in scan["entries"] and "target/package.json: npm run start = node server.js" in scan["entries"]
    assert "target/api/pyproject.toml: script todo = api.main:run" in scan["entries"] and "target/core/Cargo.toml: bin core = src/main.rs" in scan["entries"]
    assert {"target/server.js", "target/api/main.py", "target/core/src/main.rs"} <= set(scan["entries"])
    assert {"npm express ^4.19.2", "npm jest 29 (dev)", "python fastapi>=0.110", "python uvicorn==0.30", "rust serde 1", "rust regex 1.10"} <= set(scan["deps"])
    text = tools.render_scan(scan)
    assert text.startswith("TARGET target: 9 files in 5 folders") and "SKIPPED: .git x1, node_modules x1, target x1" in text and "DEPENDENCIES: " in text and "  target/server.js (13 B)" in text


def test_scan_target_tree_leaves_out_what_the_clean_room_hides(tmp_path):
    write_tree(tmp_path, {"target/server.js": "x", "index.html": "<p>", "reverse/map.md": "notes"})
    hidden = lambda rel: rel.startswith("target") or rel.startswith("reverse/map.md")  # noqa: E731
    scan = tools.scan_tree(Workspace(tmp_path), ".", hidden)
    assert [f["path"] for f in scan["files"]] == ["index.html"]
    with pytest.raises(ValueError):
        tools.scan_tree(Workspace(tmp_path), "index.html")


async def test_extract_code_skeleton_x_rays_code_artifacts_and_traces(tmp_path):
    write_tree(tmp_path, {
        "target/app.py": PROBE["py"],
        "target/logs/session.har": TRACES[1],
        "target/lib/libtodo.so": elf64(),
        "target/dist/app.jar": zipped({"META-INF/MANIFEST.MF": "x"}),
        "target/main.go": "package main\n\nfunc main() {}\n",
    })
    ws = Workspace(tmp_path)
    code = await tools.extract_code_skeleton(ws, "target/app.py")
    assert code.startswith("SKELETON target/app.py: python, 38 lines") and "ROUTES: GET /api/todos/{id} -> get_todo" in code and "% less to read)" in code
    assert "self.items.append" not in code
    assert (await tools.extract_code_skeleton(ws, "target/logs/session.har")).startswith("TRACE: har, 3 HTTP requests")
    assert (await tools.extract_code_skeleton(ws, "target/lib/libtodo.so")).startswith("ARTIFACT libtodo.so: elf, 512 bytes")
    assert "Java archive (jar), 1 entries" in await tools.extract_code_skeleton(ws, "target/dist/app.jar")
    go = await tools.extract_code_skeleton(ws, "target/main.go")
    assert go.startswith("ARTIFACT main.go: text") and "FIRST LINES (no skeleton for .go" in go and "func main()" in go
    for bad in ("target/missing.py", "../outside.py", "target"):
        with pytest.raises(ValueError):
            await tools.extract_code_skeleton(ws, bad)


@pytest.mark.parametrize(("lang", "heading"), [("en", "## Endpoints"), ("it", "## Endpoint"), ("de", "## Endpunkte")])
async def test_write_blueprint_saves_the_normalized_json_and_the_markdown_in_the_run_language(tmp_path, lang, heading):
    ws = Workspace(tmp_path)
    r = await tools.write_blueprint(ws, json.dumps(BLUEPRINT_OK), lang)
    assert r["ok"] and r["problems"] == [] and [f["path"] for f in r["files"]] == ["blueprint.json", "blueprint.md"]
    bp = json.loads((tmp_path / "blueprint.json").read_text(encoding="utf-8"))
    assert "secret" not in bp and bp["endpoints"][0]["method"] == "GET" and bp["endpoints"][1]["request"] == {"title": "string"}
    assert [c["name"] for c in bp["architecture"]["components"]] == ["API server", "Front-end"]
    assert bp["dataModels"][0]["fields"] == [{"name": "id", "type": "number", "required": True, "notes": ""}, {"name": "title", "type": "string", "required": False, "notes": ""}, {"name": "done", "type": "any", "required": False, "notes": ""}]
    assert bp["businessRules"] == ["A title is required and at most 120 characters.", "A new to-do is open."]
    md = (tmp_path / "blueprint.md").read_text(encoding="utf-8")
    assert md.startswith("# Blueprint - todo-board") and heading in md and "| GET | `/api/todos` | list |" in md
    assert tools.read_blueprint(ws) == bp and tools.blueprint_problems(ws) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"summary": ""}, '"summary" is missing'),
        ({"architecture": {}}, '"architecture.components" is missing'),
        ({"parityCriteria": ["only one"]}, '"parityCriteria" needs at least 2'),
        ({"endpoints": [], "dataModels": [], "businessRules": []}, "at least one of"),
        ({"endpoints": [{"method": "FETCH", "path": "api/todos"}]}, "endpoint FETCH api/todos"),
        ({"dataModels": [{"fields": []}]}, "every data model needs a name"),
        ({"edgeCases": ["app.get('/x', (req, res) => {\n  const t = db.find();\n  if (!t) return res.status(404).end();\n  res.json(t);\n});"]}, "source code copied from the target"),
    ],
)
async def test_write_blueprint_refuses_what_is_not_a_clean_room_blueprint(tmp_path, change, problem):
    r = await tools.write_blueprint(Workspace(tmp_path), {**BLUEPRINT_OK, **change})
    assert not r["ok"] and any(problem in p for p in r["problems"]) and not (tmp_path / "blueprint.json").exists()


async def test_write_blueprint_refuses_what_is_no_object(tmp_path):
    for raw, problem in (("{not json", "data is not JSON"), ([1, 2], "data must be an object")):
        r = await tools.write_blueprint(Workspace(tmp_path), raw)
        assert not r["ok"] and r["problems"][0].startswith(problem)


def test_copy_target_leaves_secrets_links_hidden_folders_and_builds_out(tmp_path, monkeypatch):
    src = tmp_path / "app"
    write_tree(src, {
        "server.js": "x", "public/index.html": "<p>", ".gitignore": "node_modules\n", ".env": "OPENAI_API_KEY=sk-x", ".env.local": "x",
        "deploy/id_rsa": "key", "certs/site.pem": "pem", "config/credentials.json": "{}", ".git/config": "x", ".ssh/known_hosts": "x",
        "node_modules/a/index.js": "x", "__pycache__/m.pyc": b"\x00", ".npmrc": "token",
    })
    info = tools.copy_target(src, tmp_path / "run" / "target")
    copied = sorted(str(p.relative_to(tmp_path / "run" / "target")).replace("\\", "/") for p in (tmp_path / "run" / "target").rglob("*") if p.is_file())
    assert copied == [".gitignore", "public/index.html", "server.js"]
    assert info["name"] == "app" and info["files"] == 3 and info["skipped"] == 10 and not info["truncated"]
    monkeypatch.setattr(tools, "TARGET_MAX_FILES", 2)
    capped = tools.copy_target(src, tmp_path / "capped")
    assert capped["files"] == 2 and capped["truncated"]


async def test_the_run_writes_the_blueprint_only_through_write_blueprint_and_checks_it(ctx):  # noqa: F811
    from backend.plan import new_task
    from backend.run import Run

    run = Run(goal="Reverse engineer the todo app", ctx=ctx, options={"language": "en"})
    await run.ws.ensure()
    task = new_task({"id": "w2.1", "wsId": "w2", "team": "reverse", "title": "Blueprint", "description": "d", "acceptance": [], "outputs": ["blueprint.json", "blueprint.md"], "dependsOn": []})
    agent = next(a for a in ctx.team.list() if a["team"] == "reverse" and a["kind"] == "worker")
    act = lambda tool, **args: {"thought": tool, "tool": tool, "args": args}  # noqa: E731
    refused = await run.exec_tool(task, agent, act("write_file", path="blueprint.json", content="{}"))
    assert refused.startswith("ERROR: blueprint.json and blueprint.md are written with write_blueprint")
    bad = await run.exec_tool(task, agent, act("write_blueprint", data={"summary": "x"}))
    assert bad.startswith("ERROR: blueprint.json not saved") and '"architecture.components" is missing' in bad
    ok = await run.exec_tool(task, agent, act("write_blueprint", **BLUEPRINT_OK))  # the fields beside the tool, without "data"
    assert ok.startswith("Saved blueprint.json and blueprint.md: 2 components, 1 data models, 2 endpoints")
    assert [p["path"] for t, p in ctx.events if t == "file"] == ["blueprint.json", "blueprint.md"]
    assert await run.machine_check(task) == []
    (run.ws.root / "blueprint.json").write_text('{"summary": "broken"}', encoding="utf-8")
    assert any(p.startswith("blueprint.json: ") for p in await run.machine_check(task))


# ---------- T08: the reverse team ----------


def test_the_reverse_team_in_the_config_and_out_of_the_build_plans():
    from backend.plan import normalize_plan
    from backend.prompts import TOOL_DOCS, tools_for, work_teams

    cfg = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    team = cfg["teams"]["reverse"]
    assert team["lead"] == {"id": "kira", "name": "Kira"} and team["workers"] == [{"id": "zero", "name": "Zero"}] and team["combo"] == "code" and team["reverse"] is True
    assert team["tools"] == ["scan_target_tree", "extract_code_skeleton", "write_blueprint"] and all(t in TOOL_DOCS for t in team["tools"])
    assert {"scan_target_tree", "extract_code_skeleton", "write_blueprint", "read_file", "finish"} <= set(tools_for({**cfg, "limits": {**cfg["limits"], "allowShell": False}}, "reverse"))
    assert "reverse" not in work_teams(cfg)  # the CEO never plans a build with it
    plan = normalize_plan({"workstreams": [{"team": "reverse", "title": "t"}]}, cfg)
    assert plan["workstreams"][0]["team"] == "dev"
    assert normalize_plan({"workstreams": [{"team": "anything", "title": "t"}]}, cfg, teams=["reverse"])["workstreams"][0]["team"] == "reverse"


def test_the_reverse_team_speaks_every_language():
    from backend.i18n import TEAM_LABELS, team_label

    cfg = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    assert {lang: team_label(cfg, "reverse", lang) for lang in ("en", "it", "es", "fr", "de")} == {"en": "Reverse Engineering", "it": "Reverse Engineering", "es": "Ingeniería inversa", "fr": "Rétro-ingénierie", "de": "Reverse Engineering"}
    assert all("reverse" in TEAM_LABELS[lang] for lang in ("en", "es", "fr", "de"))
    ui = (REPO / "public" / "js" / "i18n.js").read_text(encoding="utf-8")
    assert ui.count("'team.reverse'") == 4  # Italian takes the config's label
    for key in ("tool.scan_target_tree", "tool.extract_code_skeleton", "tool.write_blueprint", "intent.reverse_only", "intent.deconstruct_and_build", "phase.handover", "phase.parity", "kind.parity"):
        assert ui.count(f"'{key}'") == 5, key


def test_the_office_has_a_zone_for_every_team_and_a_prop_for_the_reverse_team():
    import re as re_

    cfg = json.loads((REPO / "config" / "default.json").read_text(encoding="utf-8"))
    office = (REPO / "public" / "js" / "world" / "office.js").read_text(encoding="utf-8")
    zones = re_.search(r"const ZONES = \[(.*?)\];", office, re_.S).group(1)
    assert len(re_.findall(r"\{ x: -?[\d.]+, z: -?[\d.]+ \}", zones)) == len(cfg["teams"]) == 9
    assert list(cfg["teams"])[-1] == "reverse" and cfg["teams"]["reverse"]["prop"] == "scanner" and "case 'scanner':" in office


def test_the_architecture_deconstruction_skill():
    text = (REPO / "skills" / "architecture-deconstruction" / "SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert "name: architecture-deconstruction" in head and "description: Deconstruct an existing application" in head
    assert all(t in text for t in ("scan_target_tree", "extract_code_skeleton", "write_blueprint", "parityCriteria"))


# ---------- T09: the intent and the clean-room handover ----------

from backend import intent as intents  # noqa: E402


@pytest.mark.parametrize(
    ("goal", "has_target", "want"),
    [
        ("Reverse engineer the existing app and write its blueprint", False, "reverse_only"),
        ("Analizza il codice e dimmi come funziona", False, "reverse_only"),
        ("Decodifica l'app esistente e ricostruiscila da zero in clean-room", False, "deconstruct_and_build"),
        ("Reconstruye la aplicación existente", False, "deconstruct_and_build"),
        ("Déconstruis l'application existante et reconstruis-la", False, "deconstruct_and_build"),
        ("Baue die bestehende Anwendung neu", False, "deconstruct_and_build"),
        ("Rewrite this in Rust", True, "deconstruct_and_build"),
        ("Tell me what is in there", True, "reverse_only"),
        ("Rewrite my landing page copy", False, "direct_build"),
        ("A simple document about coffee", False, "direct_build"),
    ],
)
def test_the_intent_rule_in_the_five_languages(goal, has_target, want):
    assert intents.guess(goal, has_target) == want


def test_the_goals_of_before_never_ask_the_ceo():
    """The examples of the UI and the goals of the demo tests: no cue, so no call."""
    ui = (REPO / "public" / "js" / "i18n.js").read_text(encoding="utf-8")
    import re as re_

    examples = [e for block in re_.findall(r"examples: \[(.*?)\]", ui, re_.S) for e in re_.findall(r"'([^']{10,})'", block)]
    assert len(examples) >= 15
    goals = [*examples, "A simple document about coffee", "Un documento di analisi per il bar", "Il sito della pizzeria", "Una landing page per il mio studio di yoga"]
    assert [g for g in goals if intents.cue(g, False)] == []


async def test_a_plain_goal_is_direct_build_without_a_call_and_a_cue_asks_the_ceo(ctx):  # noqa: F811
    from backend.run import Run

    plain = Run(goal="A landing page for my yoga studio", ctx=ctx, options={"language": "en"})
    calls = []
    real = plain.chat

    async def spy(**kw):
        calls.append(kw["messages"][0]["content"].split("\n")[0])
        return await real(**kw)

    plain.chat = spy
    await plain.classify()
    assert plain.data["intent"] == "direct_build" and plain.data["phase"] is None and calls == []
    cue = Run(goal="Reverse engineer the existing app", ctx=ctx, options={"language": "en"})
    real2 = cue.chat

    async def spy2(**kw):
        calls.append(kw["messages"][0]["content"].split("\n")[0])
        return await real2(**kw)

    cue.chat = spy2
    await cue.ws.ensure()
    await cue.classify()
    assert calls == ["[[role:intent]]"] and cue.data["intent"] == "reverse_only" and cue.data["phase"] == "deconstruct"
    assert cue.data["target"]["source"] == "demo" and (cue.ws.root / "target" / "server.js").is_file()


async def test_the_owner_sets_the_intent_and_the_target(ctx, tmp_path):  # noqa: F811
    from backend.run import Run

    src = tmp_path / "my-app"
    write_tree(src, {"main.py": "def main(): pass\n", ".env": "SECRET=1"})
    run = Run(goal="Make it better", ctx=ctx, options={"language": "it", "intent": "reverse_only", "target": str(src)})
    await run.ws.ensure()
    await run.prepare_target()
    await run.classify()
    assert run.data["target"] == {"name": "my-app", "files": 1, "bytes": 17, "skipped": 1, "source": "folder"}
    assert (run.ws.root / "target" / "main.py").is_file() and not (run.ws.root / "target" / ".env").exists()
    assert run.data["intent"] == "reverse_only" and run.data["phase"] == "deconstruct"
    texts = [m["text"] for m in run.data["messages"]]
    from backend.i18n import tr

    assert tr("it", "intent_forced", kind=tr("it", "intent_reverse_only")) in texts and any(t.startswith('Bersaglio "my-app" copiato in target/: 1 file') for t in texts)


async def test_post_api_runs_takes_the_intent_and_a_target_folder(client, tmp_path):  # noqa: F811
    from backend.i18n import http_error

    async with client as c:
        bad = await c.post("/api/runs", json={"goal": "Un sito per il bar", "intent": "clone"})
        assert bad.status_code == 400 and bad.json()["error"] == http_error("en", "intent_unsupported", value=repr("clone"), choices="direct_build, reverse_only, deconstruct_and_build")
        missing = await c.post("/api/runs", json={"goal": "Un sito per il bar", "target": str(tmp_path / "nope")})
        assert missing.status_code == 400 and missing.json()["error"] == http_error("en", "target_not_found", value=repr(str(tmp_path / "nope")))
        assert FakeRun.instances == []
        ok = await c.post("/api/runs", json={"goal": "Analizza la mia app", "intent": "deconstruct_and_build", "target": str(tmp_path)})
        assert ok.status_code == 201
        assert FakeRun.instances[0].options["intent"] == "deconstruct_and_build" and FakeRun.instances[0].options["target"] == str(tmp_path.resolve())


def clean_room_run(ctx, phase: str = "build"):  # noqa: F811
    from backend.plan import new_task
    from backend.run import Run

    run = Run(goal="Decodifica l'app esistente e ricostruiscila", ctx=ctx, options={"language": "it", "intent": "deconstruct_and_build"})
    run.data["phase"] = phase
    write_tree(run.ws.root, {"target/server.js": "app.get('/x')", "reverse/map.md": "notes", "blueprint.md": "# Blueprint", "attachments/old.py": "x", "attachments/photo.jpg": b"\xff\xd8\xff", "index.html": "<p>"})
    run.data["attachments"] = [{"id": "a1", "path": "attachments/old.py"}, {"id": "a2", "path": "attachments/photo.jpg"}]
    rev = new_task({"id": "w1.1", "wsId": "w1", "team": "reverse", "title": "Map", "description": "d", "acceptance": [], "outputs": ["reverse/map.md"], "dependsOn": [], "status": "done", "files": ["reverse/map.md"]})
    dev = new_task({"id": "w3.1", "wsId": "w3", "team": "dev", "title": "App", "description": "d", "acceptance": [], "outputs": ["index.html"], "dependsOn": []})
    run.data["tasks"] = [rev, dev]
    return run, rev, dev


async def test_the_clean_room_hides_the_original_from_the_builders(ctx):  # noqa: F811
    run, rev, dev = clean_room_run(ctx)
    agent = next(a for a in ctx.team.list() if a["team"] == "dev" and a["kind"] == "worker")
    act = lambda tool, **args: {"thought": tool, "tool": tool, "args": args}  # noqa: E731
    for path in ("target/server.js", "target", "reverse/map.md", "attachments/old.py", "old.py"):
        out = await run.exec_tool(dev, agent, act("read_file", path=path))
        assert out.startswith(f"ERROR: {path} belongs to the original application"), path
    assert await run.exec_tool(dev, agent, act("read_file", path="blueprint.md")) == "# Blueprint"
    assert await run.exec_tool(dev, agent, act("read_file", path="index.html")) == "<p>"  # a bare name is no attachment unless one exists
    assert (await run.exec_tool(dev, agent, act("write_file", path="target/server.js", content="x"))).startswith("ERROR: target/server.js belongs")
    listing = await run.exec_tool(dev, agent, act("list_files", path="."))
    assert "target/" not in listing and "reverse/map.md" not in listing and "attachments/old.py" not in listing
    assert "attachments/photo.jpg" in listing and "blueprint.md" in listing and "index.html" in listing
    assert (await run.project_files(dev)).split("\n") == [line for line in listing.split("\n")]
    assert (await run.exec_tool(rev, agent, act("read_file", path="target/server.js"))) == "app.get('/x')"  # the reverse team reads it
    early, _, dev2 = clean_room_run(ctx, phase="deconstruct")
    assert early.hidden_for(dev2) is None  # before the handover nothing is hidden: there are no builders yet


async def test_the_handover_needs_a_blueprint_the_qa_approved(ctx):  # noqa: F811
    from backend.i18n import tr

    run, rev, _ = clean_room_run(ctx, phase="deconstruct")
    assert await run.handover() is False and run.data["phase"] == "failed"
    assert run.data["messages"][-1]["text"] == tr("it", "handover_failed")
    await tools.write_blueprint(run.ws, BLUEPRINT_OK, "it")
    rev["outputs"] = rev["files"] = ["blueprint.json"]
    rev["status"] = "review"  # written but not approved yet
    run.data["phase"] = "deconstruct"
    assert await run.handover() is False


async def test_the_parity_qa_sends_a_failing_task_back_once_then_gives_its_verdict(ctx, monkeypatch):  # noqa: F811
    from backend.i18n import tr

    run, rev, dev = clean_room_run(ctx)
    await tools.write_blueprint(run.ws, BLUEPRINT_OK, "it")
    run.data["workstreams"] = [{"id": "w3", "team": "dev", "title": "App", "objective": "o", "deliverables": ["index.html"], "acceptance": [], "dependsOn": [], "status": "done", "cleanRoom": True}]
    dev.update(status="done", files=["index.html"])
    answers = iter([
        {"verdict": "revise", "criteria": [{"criterion": "c1", "ok": False, "note": "400 missing"}, {"criterion": "c2", "ok": True}], "fix": [{"taskId": "w3.1", "instruction": "Answer 400 to an empty title."}, {"taskId": "nope", "instruction": "x"}]},
        {"verdict": "pass", "criteria": [{"ok": True}, {"ok": True}], "fix": []},
    ])
    prompts = []

    async def chat_json(opts, validate=None, tries=2):
        prompts.append(opts["messages"][0]["content"].split("\n")[0])
        return next(answers)

    rounds = []

    async def schedule():
        rounds.append((dev["status"], dev.get("parityFix")))
        dev["status"] = "done"

    monkeypatch.setattr(run, "chat_json", chat_json)
    monkeypatch.setattr(run, "schedule", schedule)
    await run.parity_review()
    assert prompts == ["[[role:parity]]", "[[role:parity]]"]
    assert rounds == [("queued", "Answer 400 to an empty title.")]  # sent back with the QA's words, as a revision
    assert run.data["parity"]["verdict"] == "pass" and run.data["parity"]["round"] == 2 and run.data["parity"]["met"] == 2 and run.data["phase"] == "done"
    texts = [m["text"] for m in run.data["messages"]]
    assert tr("it", "parity_revise", ok=1, n=2, ids="w3.1") in texts and tr("it", "parity_final", ok=2, n=2) in texts
    assert (run.ws.root / "PARITY.md").read_text(encoding="utf-8").startswith(f"# {tr('it', 'parity_title')}")


async def test_a_resumed_clean_room_run_goes_on_from_its_phase(ctx, monkeypatch):  # noqa: F811
    run, _, _ = clean_room_run(ctx, phase="build")
    seen = []

    async def handover():
        seen.append("handover")
        return True

    async def parity_review(round_=1):
        seen.append("parity")

    monkeypatch.setattr(run, "handover", handover)
    monkeypatch.setattr(run, "parity_review", parity_review)
    await run.clean_room()
    assert seen == ["parity"]


# ---------- T10: the demo simulator plays the three missions ----------

from backend.router import mock  # noqa: E402


def test_the_simulator_answers_the_new_roles():
    from backend.tools import validate_blueprint

    assert mock.intent_answer("GOAL:\nRebuild the existing app in Go\n\nTARGET:\n- (no folder given)", "en")["intent"] == "deconstruct_and_build"
    assert mock.intent_answer("GOAL:\nTell me about it\n\nTARGET:\n- target/: a copy of \"x\", 3 files", "en")["intent"] == "reverse_only"
    assert mock.intent_answer("GOAL:\nTell me about it\n\nTARGET:\n- (no folder given)\n\nOWNER FILES (x):\n- attachments/app.zip (zip)", "en")["intent"] == "reverse_only"
    assert [w["team"] for w in mock.reverse_plan("x", "fr")["workstreams"]] == ["reverse", "reverse"]
    plan = mock.rebuild_plan("GOAL: x\n\nBLUEPRINT:\n## Endpoint\n\n| GET | `/api/todos` | list | |\n", "it")
    assert [(w["team"], w["deliverables"]) for w in plan["workstreams"]] == [("design", ["css/style.css"]), ("content", ["content/copy.md"]), ("dev", ["index.html", "js/app.js", "server.js"])]
    assert "server.js" not in mock.rebuild_plan("GOAL: x\n\nBLUEPRINT:\n# no endpoints\n", "en")["workstreams"][2]["deliverables"]
    briefs = mock.handover_briefs("WORKSTREAMS:\n- w3 | team design | Look | files: css/style.css | o\n- w4 | team dev | App | files: index.html, server.js | o\n", "en")["briefs"]
    assert [b["id"] for b in briefs] == ["w3", "w4"] and "index.html, server.js" in briefs[1]["brief"]
    parity = mock.parity_answer("PARITY CRITERIA:\n1. first\n2. second\n\nTASKS:\n- w3.1", "de")
    assert parity["verdict"] == "pass" and [c["criterion"] for c in parity["criteria"]] == ["first", "second"]
    js = mock.server_js([("GET", "/api/todos"), ("DELETE", "/api/todos/{id}")], "en")
    assert "['DELETE', '/api/todos/{id}']" in js and "no original code was read" in js
    messages = [{"role": "system", "content": ""}, {"role": "user", "content": "brief"}, {"role": "user", "content": "RESULT of extract_code_skeleton:\nSKELETON target/server.js: javascript, 5 lines\nROUTES: GET /api/todos -> listTodos; PATCH /api/todos/:id; GET /api/me (calls out)"},
                {"role": "user", "content": "RESULT of extract_code_skeleton:\nTRACE: har, 1 HTTP requests\n  GET /api/todos ×1 -> 200 | response [{\"done\": \"boolean\", \"id\": \"number\"}]"}]
    bp = mock.demo_blueprint(messages, "en")
    assert validate_blueprint(bp)[1] == []
    assert [(e["method"], e["path"]) for e in bp["endpoints"]] == [("GET", "/api/todos"), ("PATCH", "/api/todos/{id}")]
    assert bp["dataModels"] == [{"name": "Todo", "fields": [{"name": "done", "type": "boolean", "required": True}, {"name": "id", "type": "number", "required": True}]}]


@pytest.mark.parametrize("lang", ["en", "it", "es", "fr", "de"])
async def test_a_demo_reverse_only_mission_delivers_the_blueprint_of_the_sample(ctx, lang):  # noqa: F811
    from backend.run import Run
    from backend.tools import read_blueprint

    goals = {"en": "Reverse engineer the existing app and write its blueprint", "it": "Analizza il codice dell'app esistente e scrivi il suo blueprint", "es": "Analiza el código de la aplicación existente", "fr": "Analyse le code de l'application existante", "de": "Analysiere den Code der bestehenden Anwendung"}
    run = Run(goal=goals[lang], ctx=ctx, options={"language": lang})
    await asyncio.wait_for(run.start(), timeout=120)
    d = run.data
    assert d["status"] == "completed" and d["intent"] == "reverse_only" and d["phase"] == "done" and d["target"]["source"] == "demo"
    assert {w["team"] for w in d["workstreams"]} == {"reverse"} and all(t["status"] == "done" for t in d["tasks"])
    bp = read_blueprint(run.ws)
    assert bp is not None and ("GET", "/api/todos") in [(e["method"], e["path"]) for e in bp["endpoints"]] and "Todo" in [m["name"] for m in bp["dataModels"]]
    assert (run.ws.root / "REPORT.md").is_file() and not (run.ws.root / "index.html").exists()
    assert any(t["status"] == "done" and "blueprint.json" in t["files"] for t in d["tasks"])


async def test_a_demo_deconstruct_and_build_mission_goes_through_the_four_phases(ctx):  # noqa: F811
    from backend.i18n import tr
    from backend.run import Run

    phases = []
    real = ctx.bus.emit

    def emit(t, p=None):
        if t == "run" and isinstance(p, dict) and (not phases or phases[-1] != p.get("phase")):
            phases.append(p.get("phase"))
        return real(t, p)

    ctx.bus.emit = emit
    run = Run(goal="Decodifica l'app esistente e ricostruiscila da zero in clean-room", ctx=ctx, options={"language": "it"})
    await asyncio.wait_for(run.start(), timeout=180)
    d = run.data
    assert d["status"] == "completed" and d["intent"] == "deconstruct_and_build"
    assert [p for p in phases if p] == ["deconstruct", "handover", "build", "parity", "done"]
    assert [(w["id"], w["team"], bool(w.get("cleanRoom"))) for w in d["workstreams"]] == [("w1", "reverse", False), ("w2", "reverse", False), ("w3", "design", True), ("w4", "content", True), ("w5", "dev", True)]
    builders = [t for t in d["tasks"] if t["team"] != "reverse"]
    assert builders and all("/api/todos" in t["blueprint"] and t["brief"] for t in builders)  # Pia's brief and the contract
    assert d["blueprint"]["endpoints"] == 4 and d["parity"]["verdict"] == "pass" and d["parity"]["met"] == d["parity"]["total"] == 6
    server = (run.ws.root / "server.js").read_text(encoding="utf-8")
    assert "['PATCH', '/api/todos/{id}']" in server and "nessun codice originale" in server
    kinds = {m["kind"] for m in d["messages"]}
    assert {"intent", "handover", "parity"} <= kinds
    texts = [m["text"] for m in d["messages"]]
    assert tr("it", "parity_pass", ok=6, n=6) in texts and tr("it", "target_demo") in texts
    assert (run.ws.root / "PARITY.md").is_file() and (run.ws.root / "blueprint.md").read_text(encoding="utf-8").count("## Endpoint") == 1


async def test_a_demo_direct_build_mission_is_the_flow_of_before(ctx):  # noqa: F811
    from backend.run import Run

    run = Run(goal="A simple document about coffee", ctx=ctx, options={"language": "en"})
    await asyncio.wait_for(run.start(), timeout=120)
    d = run.data
    assert d["status"] in ("completed", "completed_with_failures") and d["intent"] == "direct_build" and d["phase"] is None and d["target"] is None
    assert "reverse" not in {w["team"] for w in d["workstreams"]} and not (run.ws.root / "target").exists()
    assert not [m for m in d["messages"] if m["kind"] in ("intent", "handover", "parity")]
