"""Mirrors server/engine/tools.js: one shared folder per run, every path an
agent gives is resolved inside it, plus the shell command runner.

Filesystem work goes through asyncio.to_thread so a slow disk never blocks
the event loop (same principle as the bus, spec 04 B1-B2). Node sorts
directory entries with localeCompare; Python sorts by code points -- the
two orders differ only for non-ASCII names."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from backend.paths import inside

SKIP = {"node_modules", ".git", ".next", "dist", "__pycache__"}


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def resolve(self, p=".") -> Path:
        # N16: the same rule on every system (paths.py); a refusal is a ValueError
        return inside(self.root, p)

    def rel(self, full) -> str:
        return str(Path(full).relative_to(self.root)).replace(os.sep, "/")

    async def ensure(self) -> None:
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)

    def _list_sync(self, p: str, limit: int) -> list[dict]:
        start = self.resolve(p)
        out: list[dict] = []
        queue = [start]
        while queue and len(out) < limit:
            dir_ = queue.pop(0)
            try:
                entries = sorted(dir_.iterdir(), key=lambda e: e.name)
            except OSError:
                continue
            for e in entries:
                if e.name in SKIP:
                    continue
                if e.is_dir():
                    queue.append(e)
                else:
                    try:
                        size = e.stat().st_size
                    except OSError:
                        size = 0
                    out.append({"path": self.rel(e), "size": size})
                if len(out) >= limit:
                    break
        return out

    async def list(self, p: str = ".", limit: int = 300) -> list[dict]:
        return await asyncio.to_thread(self._list_sync, p, limit)

    async def list_text(self, p: str = ".") -> str:
        files = await self.list(p)
        return "\n".join(f"{f['path']} ({f['size']} B)" for f in files)

    async def read(self, p: str, max: int = 12000) -> str:
        text = await asyncio.to_thread(self.resolve(p).read_text, encoding="utf-8")
        return f"{text[:max]}\n… [truncated, {len(text) - max} more chars]" if len(text) > max else text

    async def write(self, p: str, content) -> dict:
        full = self.resolve(p)
        text = content if isinstance(content, str) else __import__("json").dumps(content, indent=2)

        def write():
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(text, encoding="utf-8")

        await asyncio.to_thread(write)
        return {"path": self.rel(full), "bytes": len(text.encode("utf-8"))}

    async def write_bytes(self, p: str, data: bytes) -> dict:
        full = self.resolve(p)

        def write():
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(data)

        await asyncio.to_thread(write)
        return {"path": self.rel(full), "bytes": len(data)}

    async def size(self, p: str) -> int:
        def stat():
            try:
                s = self.resolve(p).stat()
                return s.st_size if self.resolve(p).is_file() else -1
            except OSError:
                return -1

        return await asyncio.to_thread(stat)


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Spec 11 T02 (D6): a shell command is written by a model, and a page the model
# read can steer it. It runs without the server's secrets: a variable goes when
# one of the words of its name (split on "_") is one of these, or when the
# config names it as a key (keyEnv), whatever its form.
SECRET_WORDS = frozenset({"KEY", "KEYS", "APIKEY", "TOKEN", "TOKENS", "SECRET", "SECRETS", "PASSWORD", "PASSWD", "CREDENTIALS", "AUTH"})


def config_key_names(cfg: dict) -> set[str]:
    """Every variable the config names as a provider key (providers, media,
    the runtime-registered ones of local.json). Not baseUrlEnv: a URL is no key."""
    names: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "keyEnv" and isinstance(v, str) and v:
                    names.add(v)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(cfg)
    return names


def shell_env(names=(), base=None) -> dict[str, str]:
    """The environment of a shell command: `base` (the server's own by default)
    without its secrets. Names compare upper case, as Windows does."""
    drop = {n.upper() for n in names}
    out = {}
    for k, v in (os.environ if base is None else base).items():
        up = k.upper()
        if up in drop or SECRET_WORDS.intersection(up.split("_")):
            continue
        out[k] = v
    return out


def _kill_tree(proc) -> None:
    """Node kills the whole tree on Windows (taskkill /T): a shell command
    may have spawned children that would otherwise survive the timeout."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                ["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
        else:
            proc.kill()
    except (OSError, ProcessLookupError):
        pass


async def run_command(cmd: str, cwd, timeout_ms: int, stop_event: asyncio.Event | None = None, *, secrets=()) -> dict:
    """`secrets`: more variable names to keep out of the command (the run passes
    the config's keyEnv names); the secret words go in any case."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=_NO_WINDOW,
            env=shell_env(secrets),
        )
    except OSError as err:
        return {"code": -1, "output": str(err)}

    output = ""

    async def pump() -> None:
        nonlocal output
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            output += chunk.decode("utf-8", errors="replace")
            if len(output) > 20000:
                output = output[-20000:]

    pump_task = asyncio.ensure_future(pump())
    watcher = None
    if stop_event is not None:

        async def watch() -> None:
            await stop_event.wait()
            _kill_tree(proc)

        watcher = asyncio.ensure_future(watch())

    try:
        await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError:
        output += f"\n[killed after {timeout_ms} ms]"
        _kill_tree(proc)
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=10)
        except asyncio.TimeoutError:
            pass
    finally:
        if watcher is not None:
            watcher.cancel()
    try:
        await asyncio.wait_for(pump_task, timeout=10)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pump_task.cancel()
    return {"code": proc.returncode if proc.returncode is not None else -1, "output": output[-5000:]}


# ---------- spec 11 T07: the tools of the Reverse Engineering team ----------
# They read a target inside the run's folder (its copy in target/, the owner's
# files in attachments/) and never run it: deconstructor.py reads the text and
# the bytes. write_blueprint is the only way to write blueprint.json, so the
# document the clean-room build starts from is always valid.

SCAN_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode"}
SCAN_MAX_FILES = 5000
CODE_READ_MAX = 2_000_000
ARTIFACT_READ_MAX = 32_000_000
LANGUAGE_OF = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby",
    ".php": "PHP", ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cc": "C++", ".cs": "C#", ".swift": "Swift",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "CSS", ".less": "CSS", ".vue": "Vue", ".svelte": "Svelte",
    ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell", ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML",
    ".md": "Markdown", ".xml": "XML",
}
ARTIFACT_EXT = {".so", ".dll", ".exe", ".dylib", ".wasm", ".jar", ".whl", ".apk", ".class", ".pyc", ".zip", ".tar", ".gz", ".tgz", ".bin", ".o", ".a", ".lib", ".map"}
TRACE_EXT = {".har", ".log", ".jsonl", ".ndjson"}
ENTRY_NAMES = {"main.py", "app.py", "server.py", "manage.py", "wsgi.py", "asgi.py", "__main__.py", "index.js", "server.js", "app.js", "main.js", "index.ts", "main.ts", "server.ts", "index.html", "main.go", "Main.java", "Program.cs", "Dockerfile", "docker-compose.yml", "Procfile", "Makefile"}
SKELETON_EXT = {".py", ".pyw", ".pyi", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts", ".rs", ".html", ".htm", ".xhtml", ".vue", ".svelte", ".css", ".scss", ".less"}
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "composer.json", "Gemfile")


def _cargo_build(d: Path) -> bool:
    """A Rust build folder (cargo writes CACHEDIR.TAG in it): output, not source."""
    return d.name == "target" and (d / "CACHEDIR.TAG").exists()


def _manifest(path: Path, rel: str, out: dict) -> None:
    """The entry points and the dependencies a manifest declares."""
    import json as jsonlib
    import tomllib

    name = path.name
    try:
        if name == "package.json":
            pkg = jsonlib.loads(path.read_text(encoding="utf-8", errors="replace"))
            for key in ("main", "module", "browser"):
                if isinstance(pkg.get(key), str):
                    out["entries"].append(f"{rel}: {key} {pkg[key]}")
            bins = pkg.get("bin")
            for b in ([bins] if isinstance(bins, str) else list(bins.values()) if isinstance(bins, dict) else []):
                out["entries"].append(f"{rel}: bin {b}")
            for key in ("start", "dev", "serve"):
                cmd = (pkg.get("scripts") or {}).get(key)
                if isinstance(cmd, str):
                    out["entries"].append(f"{rel}: npm run {key} = {cmd}")
            for section in ("dependencies", "devDependencies"):
                for dep, ver in (pkg.get(section) or {}).items():
                    out["deps"].append(f"npm {dep} {ver}" + (" (dev)" if section == "devDependencies" else ""))
        elif name == "pyproject.toml":
            doc = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
            project = doc.get("project") or {}
            for script, target in (project.get("scripts") or {}).items():
                out["entries"].append(f"{rel}: script {script} = {target}")
            for dep in project.get("dependencies") or []:
                out["deps"].append(f"python {dep}")
            for dep in ((doc.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}:
                if dep != "python":
                    out["deps"].append(f"python {dep}")
        elif name == "requirements.txt":
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.split("#")[0].strip()
                if line and not line.startswith("-"):
                    out["deps"].append(f"python {line}")
        elif name == "Cargo.toml":
            doc = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
            for b in doc.get("bin") or []:
                out["entries"].append(f"{rel}: bin {b.get('name', '?')} = {b.get('path', 'src/main.rs')}")
            for dep, spec in (doc.get("dependencies") or {}).items():
                version = spec if isinstance(spec, str) else (spec or {}).get("version", "")
                out["deps"].append(f"rust {dep} {version}".rstrip())
    except (ValueError, OSError, AttributeError, TypeError) as err:
        out["notes"].append(f"{rel}: unreadable manifest ({str(err)[:80]})")


def scan_tree(ws: Workspace, p: str = ".", hidden=None) -> dict:
    """What the target is: files, languages, entry points, dependencies, size.
    `hidden(rel) -> bool` leaves paths out (the clean-room rule of spec 11 T09)."""
    root = ws.resolve(p)
    if not root.is_dir():
        raise ValueError(f"{p} is not a folder of this project")
    out = {"path": ws.rel(root) or ".", "files": [], "folders": 0, "bytes": 0, "languages": {}, "entries": [], "deps": [], "manifests": [], "skipped": {}, "notes": [], "truncated": False}
    queue = [root]
    while queue:
        d = queue.pop(0)
        try:
            entries = sorted(d.iterdir(), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            rel = ws.rel(e)
            if hidden is not None and hidden(rel + ("/" if e.is_dir() else "")):
                continue
            if e.is_dir():
                if e.name in SCAN_SKIP or _cargo_build(e):
                    out["skipped"][e.name] = out["skipped"].get(e.name, 0) + 1
                    continue
                out["folders"] += 1
                queue.append(e)
                continue
            if len(out["files"]) >= SCAN_MAX_FILES:
                out["truncated"] = True
                continue
            try:
                size = e.stat().st_size
            except OSError:
                size = 0
            out["files"].append({"path": rel, "size": size})
            out["bytes"] += size
            ext = e.suffix.lower()
            lang = LANGUAGE_OF.get(ext) or ("artifact" if ext in ARTIFACT_EXT else "trace" if ext in TRACE_EXT else None)
            if lang:
                n, b = out["languages"].get(lang, (0, 0))
                out["languages"][lang] = (n + 1, b + size)
            if e.name in MANIFESTS:
                out["manifests"].append(rel)
                _manifest(e, rel, out)
            if e.name in ENTRY_NAMES or rel.endswith("src/main.rs") or rel.endswith("src/lib.rs"):
                out["entries"].append(rel)
    return out


def render_scan(scan: dict) -> str:
    def kb(b: int) -> str:
        return f"{b / 1024:.1f} KB"

    files = scan["files"]
    lines = [f"TARGET {scan['path']}: {len(files)} files in {scan['folders']} folders, {kb(scan['bytes'])}" + (" (truncated)" if scan["truncated"] else "")]
    if scan["skipped"]:
        lines.append("SKIPPED: " + ", ".join(f"{k} x{v}" for k, v in sorted(scan["skipped"].items())))
    if scan["languages"]:
        langs = sorted(scan["languages"].items(), key=lambda kv: -kv[1][1])
        lines.append("LANGUAGES: " + "; ".join(f"{k} {n} files ({kb(b)})" for k, (n, b) in langs))
    if scan["manifests"]:
        lines.append("MANIFESTS: " + ", ".join(scan["manifests"]))
    if scan["entries"]:
        lines.append("ENTRY POINTS: " + "; ".join(dict.fromkeys(scan["entries"])))
    if scan["deps"]:
        deps = list(dict.fromkeys(scan["deps"]))
        lines.append("DEPENDENCIES: " + "; ".join(deps[:60]) + (f" ... +{len(deps) - 60}" if len(deps) > 60 else ""))
    if scan["notes"]:
        lines.append("NOTES: " + "; ".join(scan["notes"]))
    big = sorted(files, key=lambda f: -f["size"])[:5]
    if big:
        lines.append("LARGEST: " + "; ".join(f"{f['path']} ({kb(f['size'])})" for f in big))
    lines.append("FILES:")
    lines += [f"  {f['path']} ({f['size']} B)" for f in files[:150]]
    if len(files) > 150:
        lines.append(f"  ... {len(files) - 150} more (scan a subfolder to see them)")
    if not files:
        lines.append("  (empty: nothing to deconstruct here; the owner's files are in attachments/)")
    return "\n".join(lines)


async def scan_target_tree(ws: Workspace, p: str = ".", hidden=None) -> str:
    return render_scan(await asyncio.to_thread(scan_tree, ws, p or ".", hidden))


def _read_head(full: Path, limit: int) -> bytes:
    with open(full, "rb") as f:
        return f.read(limit)


async def extract_code_skeleton(ws: Workspace, p: str) -> str:
    """The structural X-ray of one file: the skeleton of source code, the
    metadata of a built artifact, the summary of a trace or a log."""
    from backend import deconstructor

    full = ws.resolve(p)
    if not full.is_file():
        raise ValueError(f"{p} is not a file of this project")
    rel = ws.rel(full)
    ext = full.suffix.lower()
    size = full.stat().st_size
    if ext in SKELETON_EXT:
        data = await asyncio.to_thread(_read_head, full, CODE_READ_MAX)
        text = data.decode("utf-8", errors="replace")
        skel = await asyncio.to_thread(deconstructor.extract_skeleton, text, ext)
        out = deconstructor.render_skeleton(skel, rel)
        cut = f", read the first {CODE_READ_MAX} bytes" if size > CODE_READ_MAX else ""
        return f"{out}\n({len(out)} chars instead of {len(text)}: {100 - 100 * len(out) // max(1, len(text))}% less to read{cut})"
    data = await asyncio.to_thread(_read_head, full, ARTIFACT_READ_MAX)
    if ext in TRACE_EXT or (ext == ".json" and ("trace" in full.name.lower() or "har" in full.name.lower())):
        text = data.decode("utf-8", errors="replace")
        return deconstructor.render_trace(await asyncio.to_thread(deconstructor.summarize_runtime_trace, text))
    meta = await asyncio.to_thread(deconstructor.inspect_artifact_metadata, data, full.name)
    out = deconstructor.render_artifact(meta)
    if meta["format"] in ("text", "json"):
        preview = data[:2400].decode("utf-8", errors="replace")
        out += f"\nFIRST LINES (no skeleton for {ext or 'this kind of file'}: read the rest with read_file):\n{preview}"
    return out


# ---------- write_blueprint ----------

BLUEPRINT = "blueprint.json"
BLUEPRINT_MD = "blueprint.md"
BLUEPRINT_MAX = 200_000
HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "WS", "ANY"}
_CODE_ENDS = ("{", "}", ";", "):", "=>")
_CODE_STARTS = ("def ", "function ", "class ", "import ", "const ", "fn ", "pub fn ", "#include")


def _looks_like_code(s: str) -> bool:
    """A string that is source copied from the target, not a description: four
    lines or more, half of them shaped like code. The blueprint is the
    clean-room boundary: it describes behaviour, it never carries code."""
    lines = [x.strip() for x in s.splitlines() if x.strip()]
    if len(lines) < 4:
        return False
    return sum(1 for x in lines if x.endswith(_CODE_ENDS) or x.startswith(_CODE_STARTS)) * 2 >= len(lines)


def _text(v, n: int = 600) -> str:
    return " ".join(str(v).split())[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _texts(v, cap: int, n: int = 400) -> list[str]:
    out = []
    for x in v if isinstance(v, list) else []:
        t = _text(x.get("text") or x.get("rule") or x.get("criterion") or x.get("description"), n) if isinstance(x, dict) else _text(x, n)
        if t:
            out.append(t)
    return out[:cap]


def validate_blueprint(raw) -> tuple[dict, list[str]]:
    """(the blueprint normalized, the problems that keep it from being saved)."""
    import json as jsonlib

    problems: list[str] = []
    if isinstance(raw, str):
        try:
            raw = jsonlib.loads(raw)
        except ValueError:
            return {}, ["data is not JSON: give the blueprint as an object"]
    if not isinstance(raw, dict):
        return {}, ["data must be an object with the blueprint's fields"]
    if len(jsonlib.dumps(raw, ensure_ascii=False)) > BLUEPRINT_MAX:
        problems.append(f"the blueprint is larger than {BLUEPRINT_MAX // 1000} KB: describe, do not copy")
    copied: list[str] = []

    def walk(v, where: str) -> None:
        if isinstance(v, str):
            if _looks_like_code(v):
                copied.append(where)
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{where}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{where}[{i}]")

    walk(raw, "data")
    if copied:
        problems.append("these fields hold source code copied from the target, which a clean-room blueprint never carries (describe the behaviour instead): " + ", ".join(copied[:6]))
    arch = raw.get("architecture") if isinstance(raw.get("architecture"), dict) else {}
    components = []
    for c in (arch.get("components") if isinstance(arch.get("components"), list) else [])[:40]:
        c = c if isinstance(c, dict) else {"name": c}
        if _text(c.get("name"), 120):
            components.append({"name": _text(c.get("name"), 120), "kind": _text(c.get("kind"), 60), "responsibility": _text(c.get("responsibility") or c.get("role") or c.get("description")), "files": _texts(c.get("files"), 20, 200)})
    models = []
    for m in (raw.get("dataModels") if isinstance(raw.get("dataModels"), list) else [])[:40]:
        if not isinstance(m, dict) or not _text(m.get("name"), 120):
            problems.append("every data model needs a name")
            continue
        fields = []
        for f in (m.get("fields") if isinstance(m.get("fields"), list) else [])[:60]:
            f = f if isinstance(f, dict) else {"name": f}
            if _text(f.get("name"), 120):
                fields.append({"name": _text(f.get("name"), 120), "type": _text(f.get("type"), 80) or "any", "required": f.get("required") is True, "notes": _text(f.get("notes"), 300)})
        models.append({"name": _text(m.get("name"), 120), "fields": fields, "notes": _text(m.get("notes"))})
    endpoints = []
    for e in (raw.get("endpoints") if isinstance(raw.get("endpoints"), list) else [])[:120]:
        if not isinstance(e, dict):
            problems.append("every endpoint is an object with method and path")
            continue
        method = _text(e.get("method"), 10).upper() or "GET"
        path = _text(e.get("path"), 300)
        if method not in HTTP_METHODS or not path.startswith("/"):
            problems.append(f"endpoint {method} {path or '(no path)'}: method must be one of {', '.join(sorted(HTTP_METHODS))} and path must start with /")
            continue
        shape = lambda v: v if isinstance(v, (dict, list, str)) else None  # noqa: E731
        endpoints.append({"method": method, "path": path, "purpose": _text(e.get("purpose") or e.get("description")), "request": shape(e.get("request")), "response": shape(e.get("response")), "auth": _text(e.get("auth"), 120)})
    ui = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
    bp = {
        "name": _text(raw.get("name"), 120) or "target",
        "summary": _text(raw.get("summary"), 2000),
        "architecture": {"style": _text(arch.get("style"), 200), "components": components, "stack": _texts(arch.get("stack"), 30, 120)},
        "dataModels": models,
        "endpoints": endpoints,
        "businessRules": _texts(raw.get("businessRules"), 80),
        "edgeCases": _texts(raw.get("edgeCases"), 80),
        "parityCriteria": _texts(raw.get("parityCriteria"), 60),
        "ui": {"screens": _texts(ui.get("screens"), 40), "flows": _texts(ui.get("flows"), 40)},
        "nonFunctional": _texts(raw.get("nonFunctional"), 40),
        "openQuestions": _texts(raw.get("openQuestions"), 40),
    }
    if not bp["summary"]:
        problems.append('"summary" is missing: say what the application does and for whom')
    if not components:
        problems.append('"architecture.components" is missing: list the parts of the application, each with a name and its responsibility')
    if len(bp["parityCriteria"]) < 2:
        problems.append('"parityCriteria" needs at least 2 checkable statements the rebuild must satisfy')
    if not (endpoints or models or bp["businessRules"]):
        problems.append('give at least one of "endpoints", "dataModels" or "businessRules"')
    return bp, problems


def blueprint_markdown(bp: dict, lang: str | None = None) -> str:
    """The neutral specification a clean-room team reads, from the blueprint,
    with its headings in the language of the run (i18n.BLUEPRINT_MD)."""
    from backend.i18n import BLUEPRINT_MD, DEFAULT, check

    h = BLUEPRINT_MD[check(lang) or DEFAULT]
    out = [f"# {h['title']} - {bp['name']}", "", bp["summary"], ""]
    arch = bp["architecture"]
    out += [f"## {h['architecture']}", ""]
    if arch["style"]:
        out += [f"{h['style']}: {arch['style']}", ""]
    if arch["stack"]:
        out += [f"{h['stack']}: {', '.join(arch['stack'])}", ""]
    for c in arch["components"]:
        out.append(f"- **{c['name']}**" + (f" ({c['kind']})" if c["kind"] else "") + (f": {c['responsibility']}" if c["responsibility"] else ""))
    out.append("")
    if bp["dataModels"]:
        out += [f"## {h['models']}", ""]
        for m in bp["dataModels"]:
            out += [f"### {m['name']}", ""] + ([m["notes"], ""] if m["notes"] else [])
            out += [f"| {h['field']} | {h['type']} | {h['required']} | {h['notes']} |", "|---|---|---|---|"]
            out += [f"| {f['name']} | {f['type']} | {h['yes'] if f['required'] else h['no']} | {f['notes']} |" for f in m["fields"]]
            out.append("")
    if bp["endpoints"]:
        out += [f"## {h['endpoints']}", "", f"| {h['method']} | {h['path']} | {h['purpose']} | {h['auth']} |", "|---|---|---|---|"]
        out += [f"| {e['method']} | `{e['path']}` | {e['purpose']} | {e['auth']} |" for e in bp["endpoints"]]
        out.append("")
    for key, title in (("businessRules", "rules"), ("edgeCases", "edges"), ("parityCriteria", "criteria"), ("nonFunctional", "nonfunctional"), ("openQuestions", "questions")):
        if bp[key]:
            out += [f"## {h[title]}", ""] + [f"{i}. {x}" for i, x in enumerate(bp[key], 1)] + [""]
    if bp["ui"]["screens"] or bp["ui"]["flows"]:
        out += [f"## {h['ui']}", ""] + [f"- {h['screen']}: {x}" for x in bp["ui"]["screens"]] + [f"- {h['flow']}: {x}" for x in bp["ui"]["flows"]] + [""]
    return "\n".join(out)


async def write_blueprint(ws: Workspace, data, lang: str | None = None) -> dict:
    """{"ok", "problems", "files", "blueprint"}: validated, then blueprint.json and blueprint.md."""
    import json as jsonlib

    bp, problems = validate_blueprint(data)
    if problems:
        return {"ok": False, "problems": problems, "files": [], "blueprint": bp}
    a = await ws.write(BLUEPRINT, jsonlib.dumps(bp, ensure_ascii=False, indent=2))
    b = await ws.write(BLUEPRINT_MD, blueprint_markdown(bp, lang))
    return {"ok": True, "problems": [], "files": [a, b], "blueprint": bp}


def read_blueprint(ws: Workspace) -> dict | None:
    """The saved blueprint, or None (missing, unreadable or invalid)."""
    import json as jsonlib

    try:
        raw = jsonlib.loads(ws.resolve(BLUEPRINT).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    bp, problems = validate_blueprint(raw)
    return None if problems else bp


def blueprint_problems(ws: Workspace) -> list[str]:
    """The machine check of a delivery that includes blueprint.json."""
    import json as jsonlib

    try:
        raw = jsonlib.loads(ws.resolve(BLUEPRINT).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return [f"{BLUEPRINT} cannot be read: {err}"]
    return validate_blueprint(raw)[1]


# ---------- spec 11 T09: the target, copied into the run's folder ----------

TARGET_DIR = "target"
TARGET_MAX_FILES = 3000
TARGET_MAX_BYTES = 50_000_000
# names that hold secrets: never copied, whatever folder they are in (D31)
SECRET_NAMES = (".env", ".npmrc", ".pypirc", ".netrc", ".git-credentials", "credentials", "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
SECRET_EXT = {".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".kdbx", ".gpg"}
DOT_KEEP = {".gitignore", ".editorconfig", ".babelrc", ".eslintrc", ".eslintrc.json", ".eslintrc.js", ".prettierrc", ".nvmrc", ".python-version", ".dockerignore"}


def _secret(name: str) -> bool:
    low = name.lower()
    return low.startswith(SECRET_NAMES) or Path(low).suffix in SECRET_EXT


def copy_target(src, dest) -> dict:
    """A read-only snapshot of the target folder in the run's own folder, so the
    agents read it with the run's path rules and never leave it. Not copied:
    links, hidden folders (.git, .ssh...), the hidden files that are no config,
    anything named like a secret, dependency and build folders; at most
    TARGET_MAX_FILES files and TARGET_MAX_BYTES bytes."""
    import shutil

    src, dest = Path(src).resolve(), Path(dest)
    out = {"name": src.name or str(src), "files": 0, "bytes": 0, "skipped": 0, "truncated": False}
    queue = [src]
    while queue:
        d = queue.pop(0)
        try:
            entries = sorted(d.iterdir(), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            if e.is_symlink():
                out["skipped"] += 1
                continue
            if e.is_dir():
                if e.name.startswith(".") or e.name in SCAN_SKIP or _cargo_build(e):
                    out["skipped"] += 1
                    continue
                queue.append(e)
                continue
            if (e.name.startswith(".") and e.name not in DOT_KEEP) or _secret(e.name):
                out["skipped"] += 1
                continue
            try:
                size = e.stat().st_size
            except OSError:
                continue
            if out["files"] >= TARGET_MAX_FILES or out["bytes"] + size > TARGET_MAX_BYTES:
                out["truncated"] = True
                out["skipped"] += 1
                continue
            to = dest / e.relative_to(src)
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(e, to)
            out["files"] += 1
            out["bytes"] += size
    return out
