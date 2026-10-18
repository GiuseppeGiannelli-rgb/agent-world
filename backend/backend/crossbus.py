"""Spec 10 §R3: the cross-agent context bus.

What a file says to the teammates working next to its author: facts_from_file()
reads a file the moment it is written, with no model, and gives the facts the
others must not get wrong:
- palette: hex colours and CSS custom properties ("--primary #c0392b");
- interface: CSS classes and ids, HTML ids and classes, JS and Python
  functions, classes and exported constants;
- copy: the headings of a text (Markdown, HTML);
- links: the files a page loads (src, href);
- keys: the top-level keys of a JSON file.

Run.publish_file() puts them in the run memory (BM25 + local vectors, spec 08)
tagged with workstream, task, team and agent. Run.cross_update() hands a worker
the [LIVE CROSS-AGENT UPDATE] when linked work moves (linked()).
"""

import json
import re

MAX_ITEMS = 24  # facts of one kind kept from one file
MAX_CHARS = 600

HEX_RE = re.compile(r"(?<![\w&])#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
CSS_VAR_RE = re.compile(r"(--[a-zA-Z][\w-]*)\s*:\s*([^;}{\n]+)")
CSS_BLOCK_RE = re.compile(r"([^{}]+)\{")
CSS_NAME_RE = re.compile(r"(?<![\w-])([.#][a-zA-Z][\w-]*)")
HTML_ATTR_RE = re.compile(r"""\b(id|class)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
LINK_RE = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"'#?:]+)["']""", re.IGNORECASE)
HTML_HEAD_RE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
JS_NAME_RE = re.compile(r"\b(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)|class\s+([A-Za-z_$][\w$]*)|export\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*))")
JS_EXPORT_CONST_RE = re.compile(r"\bexport\s+(?:const|let|var)\s+([A-Za-z_$][\w$]*)")
PY_NAME_RE = re.compile(r"(?m)^(?:async\s+)?def\s+([A-Za-z_]\w*)|^class\s+([A-Za-z_]\w*)")
MD_HEAD_RE = re.compile(r"(?m)^#{1,3}\s+(.+?)\s*#*\s*$")

CSS_EXT = {".css", ".scss", ".sass", ".less"}
HTML_EXT = {".html", ".htm", ".svg", ".vue", ".svelte"}
JS_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
PY_EXT = {".py"}
MD_EXT = {".md", ".markdown", ".txt", ".rst"}


def _ext(path: str) -> str:
    base = str(path).rsplit("/", 1)[-1]
    return "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""


def _uniq(items) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))[:MAX_ITEMS]


def _fact(path: str, label: str, items: list[str]) -> str:
    return f"{path} {label}: {', '.join(items)}"[:MAX_CHARS]


def _css_names(text: str) -> list[str]:
    names = []
    for m in CSS_BLOCK_RE.finditer(text):
        selector = m.group(1)
        if ":root" in selector or selector.strip().startswith("@"):
            continue
        names += [n for n in CSS_NAME_RE.findall(selector) if not HEX_RE.fullmatch(n)]
    return names


def facts_from_file(path: str, content) -> list[tuple[str, str]]:
    """[(kind, text)]: the facts of one file written by an agent, or []."""
    if not isinstance(content, str) or not content.strip():
        return []
    ext = _ext(path)
    out: list[tuple[str, str]] = []
    palette, interface, copy, links, keys = [], [], [], [], []
    if ext in CSS_EXT or ext in HTML_EXT:
        palette += [f"{name} {value.strip()}" for name, value in CSS_VAR_RE.findall(content)]
        listed = " ".join(palette)
        palette += [h for h in HEX_RE.findall(content) if h not in listed]
    if ext in CSS_EXT:
        interface += _css_names(content)
    if ext in HTML_EXT:
        for kind, value in HTML_ATTR_RE.findall(content):
            prefix = "#" if kind.lower() == "id" else "."
            interface += [prefix + v for v in value.split()]
        style = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", content, re.IGNORECASE | re.DOTALL))
        interface += _css_names(style)
        links += LINK_RE.findall(content)
        copy += [re.sub(r"\s+", " ", TAG_RE.sub("", h)).strip() for h in HTML_HEAD_RE.findall(content)]
    if ext in JS_EXT:
        for m in JS_NAME_RE.finditer(content):
            interface.append(next(g for g in m.groups() if g))
        interface += JS_EXPORT_CONST_RE.findall(content)
    if ext in PY_EXT:
        interface += [a or b for a, b in PY_NAME_RE.findall(content)]
    if ext in MD_EXT:
        copy += MD_HEAD_RE.findall(content)
    if ext == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                keys += [str(k) for k in data]
        except ValueError:
            pass
    for kind, label, items in (("palette", "palette", palette), ("interface", "interface", interface), ("copy", "headings", copy), ("links", "loads", links), ("keys", "keys", keys)):
        items = _uniq(items)
        if items:
            out.append((kind, _fact(path, label, items)))
    return out


def linked(task: dict, item: dict, ws_of) -> bool:
    """Whether a memory item comes from work linked to this task: the same
    workstream, a workstream it builds on or one that builds on it, or a task
    it depends on. The owner's files (no workstream) are in the brief already."""
    other_ws = item.get("wsId")
    if not other_ws or item.get("taskId") == task.get("id"):
        return False
    if other_ws == task.get("wsId") or item.get("taskId") in (task.get("dependsOn") or []):
        return True
    mine, theirs = ws_of(task.get("wsId")) or {}, ws_of(other_ws) or {}
    return other_ws in (mine.get("dependsOn") or []) or task.get("wsId") in (theirs.get("dependsOn") or [])


FACT_KINDS = ("palette", "interface", "copy", "links", "keys")
TRIGGER_KINDS = ("delivery", "verdict", "lesson")
