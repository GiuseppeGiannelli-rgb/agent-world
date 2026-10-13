"""Pure plan/subtask normalization, ported 1:1 from the top of
server/engine/run.js: maps model-given team names to ours, breaks
dependency cycles (Kahn's algorithm), drops unsafe paths."""

import re
import unicodedata

_COMBINING_RE = re.compile(r"[̀-ͯ]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def nz(*values):
    """Mirrors JS `??` chained across `values`: the first one that is not
    None/missing wins, even if falsy (0, '', [], {} all count as present).
    Python's `or` would wrongly skip those -- this does not."""
    for v in values:
        if v is not None:
            return v
    return None


def slugify(text, max: int = 40) -> str:
    base = str(text).lower()
    base = _COMBINING_RE.sub("", unicodedata.normalize("NFD", base))
    base = _NON_ALNUM_RE.sub("-", base).strip("-")[:max]
    return base or "progetto"


TEAM_SYNONYMS = {
    "research": ["research", "researcher", "analyst", "ricerca", "analysis"],
    "dev": ["dev", "builder", "engineer", "developer", "coder", "code", "sviluppo", "engineering", "programmer"],
    "content": ["content", "writer", "copywriter", "author", "contenuti", "editor", "copy", "writing"],
    "design": ["design", "designer", "ui", "ux"],
    "genai": ["genai", "generative", "media", "image", "images", "art", "artist", "audio", "voice", "video", "immagini", "creative"],
    "prompt": ["prompt", "prompts", "prompting", "prompt-engineering", "promptlab"],
}


def pick_team(team, teams: list[str]) -> str:
    r = str(team or "").lower().strip()
    if r in teams:
        return r
    for canon, words in TEAM_SYNONYMS.items():
        if r in words and canon in teams:
            return canon
    return "dev" if "dev" in teams else teams[0]


_DRIVE_RE = re.compile(r"^[a-z]:", re.IGNORECASE)


def safe_rel_path(p) -> str | None:
    s = str(p or "").strip().replace("\\", "/")
    s = re.sub(r"^\.?/+", "", s)
    if not s or ".." in s.split("/") or _DRIVE_RE.match(s):
        return None
    return s


def strings(v, max: int) -> list[str]:
    items = v if isinstance(v, list) else ([v] if v else [])
    return [str(i) for i in items if i][:max]


def _to_dag(items: list[dict], make_id) -> list[dict]:
    """Maps model-given ids to ours and removes dependency cycles: whatever
    is left in a cycle loses the dependencies that close it."""
    id_map = {str(it.get("id") if it.get("id") is not None else i + 1): make_id(i) for i, it in enumerate(items)}
    nodes = []
    for i, it in enumerate(items):
        this_id = make_id(i)
        deps = list(dict.fromkeys(d for d in (id_map.get(x) for x in strings(it.get("dependsOn"), 20)) if d and d != this_id))
        nodes.append({"it": it, "id": this_id, "deps": deps})
    indeg = {n["id"]: len(n["deps"]) for n in nodes}
    order = []
    placed = set()
    queue = [n for n in nodes if not n["deps"]]
    while queue:
        n = queue.pop(0)
        order.append(n)
        placed.add(id(n))
        for u in nodes:
            if n["id"] in u["deps"]:
                indeg[u["id"]] -= 1
                if indeg[u["id"]] == 0:
                    queue.append(u)
    for n in nodes:
        if id(n) not in placed:
            order_ids = {o["id"] for o in order}
            n["deps"] = [d for d in n["deps"] if d in order_ids]
            order.append(n)
    return order


def normalize_plan(raw: dict, cfg: dict) -> dict:
    teams = [id for id, t in cfg["teams"].items() if t.get("kind") == "work" and t.get("lead") is not None]
    items = (raw or {}).get("workstreams")
    items = items[: cfg["limits"]["maxWorkstreams"]] if isinstance(items, list) else []
    if not items:
        raise ValueError("The plan has no workstreams")
    nodes = _to_dag(items, lambda i: f"w{i + 1}")
    workstreams = []
    for n in nodes:
        it, id_, deps = n["it"], n["id"], n["deps"]
        workstreams.append(
            {
                "id": id_,
                "team": pick_team(nz(it.get("team"), it.get("role")), teams),
                "title": str(nz(it.get("title"), f"Workstream {id_}"))[:80],
                "objective": str(nz(it.get("objective"), it.get("description"), it.get("title"), ""))[:2000],
                "deliverables": list(dict.fromkeys(p for p in (safe_rel_path(d) for d in strings(nz(it.get("deliverables"), it.get("outputs")), 8)) if p)),
                "acceptance": strings(it.get("acceptance"), 6),
                "dependsOn": deps,
                "status": "queued",
                "leadId": None,
                "summary": "",
                "error": None,
                "startedAt": None,
                "finishedAt": None,
            }
        )
    return {"complexity": "complex" if raw.get("complexity") == "complex" else "simple", "summary": str(nz(raw.get("summary"), ""))[:600], "workstreams": workstreams}


def new_task(fields: dict) -> dict:
    return {
        "skills": [], "brief": "", "pitfalls": [], "status": "queued", "agentId": None, "attempts": 0,
        "revisions": 0, "escalated": False, "summary": "", "files": [], "verdicts": [], "history": [],
        "error": None, "startedAt": None, "finishedAt": None, **fields,
    }


def single_subtask(ws: dict) -> list[dict]:
    return [new_task({"id": f"{ws['id']}.1", "wsId": ws["id"], "team": ws["team"], "title": ws["title"], "description": ws["objective"], "acceptance": ws["acceptance"], "outputs": ws["deliverables"], "dependsOn": []})]


def normalize_subtasks(raw: dict, ws: dict, cfg: dict) -> list[dict]:
    items = (raw or {}).get("subtasks")
    items = items[: cfg["limits"]["maxSubtasks"]] if isinstance(items, list) else []
    if not items:
        return single_subtask(ws)
    nodes = _to_dag(items, lambda i: f"{ws['id']}.{i + 1}")
    tasks = []
    for n in nodes:
        it, id_, deps = n["it"], n["id"], n["deps"]
        tasks.append(
            new_task(
                {
                    "id": id_,
                    "wsId": ws["id"],
                    "team": ws["team"],
                    "title": str(nz(it.get("title"), f"Parte {id_}"))[:80],
                    "description": str(nz(it.get("description"), it.get("title"), ""))[:2000],
                    "acceptance": strings(it.get("acceptance"), 6),
                    "outputs": list(dict.fromkeys(p for p in (safe_rel_path(o) for o in strings(it.get("outputs"), 5)) if p)),
                    "dependsOn": deps,
                }
            )
        )
    # every deliverable must belong to somebody: orphans go to the last subtask
    covered = {o for t in tasks for o in t["outputs"]}
    orphans = [d for d in ws["deliverables"] if d not in covered]
    if orphans:
        tasks[-1]["outputs"].extend(orphans)
    return tasks
