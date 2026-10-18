"""Spec 10 §R2: every subtask hires its own model.

analyze() reads one subtask -- title, description, acceptance, expected files,
the Prompt Lab brief, the skills Otto gave it, its team and that team's
tools, its dependencies, revisions and escalation -- with no model and no
network. It gives a category (coding, creative, research, reasoning or
general), a complexity from 0 to 1 and a level (simple, medium, complex),
and how much each specialty counts for it.

rank() orders the ready models of the router's catalog for that reading:
- fit: the weighted specialties of the model (profiler.specialties);
- size: a complex task wants 32B or more (better 70B+), a medium one 14B or
  more; a simple one takes any size, and a giant is wasted on it;
- cost: a simple task prefers free and local models and shuns the premium
  ones, so the paid quota is kept for the work that needs it; a complex task
  does not look at the cost;
- health: the success rate of this session; a target cooling down goes
  last; a benched provider, a dead model or one without a key is out;
- the JSON of the actions: a model unreliable at it goes down.

hire() keeps the first router.hiring.chain candidates (6) as the subtask's
chain; the Tasker calls with it, and the router tries the team's combo and
the cascade after it (D3). promote() records the replacement when the hired
model failed and another candidate answered, and ranks the chain again with
the health of now. Without ready models (demo) nobody is hired (D5)."""

import re
from datetime import datetime, timezone

DEFAULT_CHAIN = 6
LEVELS = ((0.4, "simple"), (0.65, "medium"), (1.01, "complex"))
MIN_SIZE = {"simple": 0, "medium": 14, "complex": 32}
WANT_SIZE = {"simple": 0, "medium": 24, "complex": 70}
COST = {
    "simple": {"free": 0.25, "local": 0.25, "low": -0.05, "high": -0.35},
    "medium": {"free": 0.08, "local": 0.05, "low": 0.0, "high": -0.1},
    "complex": {"free": 0.0, "local": -0.05, "low": 0.0, "high": 0.05},
}
TOOL_FLOOR = 0.45
# how much each specialty counts, by category (toolUse always: the worker answers with JSON actions)
NEEDS = {
    "coding": {"coding": 0.5, "toolUse": 0.25, "reasoning": 0.15, "speed": 0.1},
    "creative": {"creative": 0.55, "toolUse": 0.2, "speed": 0.15, "reasoning": 0.1},
    "research": {"research": 0.5, "reasoning": 0.2, "toolUse": 0.2, "speed": 0.1},
    "reasoning": {"reasoning": 0.55, "toolUse": 0.2, "coding": 0.15, "speed": 0.1},
    "general": {"reasoning": 0.25, "creative": 0.25, "toolUse": 0.3, "speed": 0.2},
}

_W = r"[\wàèéìòùáíóúñçäöüß]*"


def _kw(words: str) -> re.Pattern:
    return re.compile(rf"\b(?:{words}){_W}", re.IGNORECASE)


# the words of the five languages; a word counts once per subtask
KEYWORDS = {
    "coding": _kw(r"code|coding|codic|códig|programm|implement|svilupp|desarroll|développ|entwickl|api|endpoint|script|function|funzion|función|fonction|funktion|class|bug|fix|deploy|database|backend|frontend|html|css|javascript|typescript|python|react|component|composant|komponent|responsive|build|server|query|schema|esquema|schéma|autentic|authent"),
    "creative": _kw(r"copy|testi|testo|text|texto|texte|write|scriv|escrib|écri|schreib|story|storia|historia|histoire|geschicht|slogan|tagline|brand|marchio|marca|marque|marke|grafic|gráfic|graphi|palette|colori|color|couleur|farb|logo|immagin|image|imagen|bild|post|social|caption|didascal|tono|tone|voce|voz|voix|stimm|creativ|kreativ|naming|headline|titol|títul|titre|titel|benvenut|welcome|bienvenid|bienvenue|willkommen"),
    "research": _kw(r"research|ricerc|investig|recherch|forschung|analy|anali|análisi|competitor|concorren|competen|concurren|wettbewerb|market|mercat|mercad|marché|markt|trend|tendenz|benchmark|survey|sondagg|encuest|source|fonti|fuente|quell|study|studi|estudi|étude|compar|confront|vergleich|prezz|precio|prix|preis|price|recension|review|reseña|avis|bewertung"),
    "reasoning": _kw(r"plan|piano|strateg|architett|architect|arquitect|architektur|logic|logica|lógic|logiqu|logik|math|matemat|mathé|algorithm|algoritm|algorithme|optimi|ottimizz|decid|decision|decisión|décision|entscheid|evaluat|valuta|evalú|évalu|bewert|proof|dimostr|reason|ragion|razon|raisonn|option|opzion|opción"),
}
COMPLEX_RE = _kw(r"complet|vollständig|full|intero|entire|enter|entièr|architett|architect|arquitect|architektur|integra|integrat|intégr|sicurezza|security|seguridad|sécurité|sicherheit|responsive|database|multi|scalab|escalab|skalier|performance|prestazion|rendimiento|leistung|ottimizz|optimi|accessib|zugänglich|refactor|migra|autentic|authent|test")
SIMPLE_RE = _kw(r"semplic|simple|sencill|einfach|breve|short|cort|court|kurz|bozza|draft|borrador|brouillon|entwurf|lista|list|liste|elenco|riassunt|summary|resumen|résumé|zusammenfass|nota|note|notiz")
TEAM_PRIOR = {
    "dev": {"coding": 1.0},
    "research": {"research": 1.0},
    "content": {"creative": 1.0},
    "design": {"creative": 0.8, "coding": 0.2},
    "genai": {"creative": 1.0},
    "prompt": {"creative": 0.6, "reasoning": 0.4},
}
TOOL_HINT = {"run_command": ("coding", 0.5), "web_search": ("research", 0.4), "web_fetch": ("research", 0.2), "generate_image": ("creative", 0.4), "generate_speech": ("creative", 0.3)}
CODE_EXT = {".html", ".htm", ".css", ".scss", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".py", ".sql", ".sh", ".yml", ".yaml", ".toml", ".vue", ".svelte", ".php", ".go", ".rs", ".java", ".json"}
TEXT_EXT = {".md", ".txt", ".rtf", ".docx", ".csv"}


def enabled(cfg: dict) -> bool:
    return bool(((cfg.get("router") or {}).get("hiring") or {}).get("enabled", True))


def _ext(path: str) -> str:
    base = str(path).rsplit("/", 1)[-1]
    return "." + base.rsplit(".", 1)[-1].lower() if "." in base else ""


def _text(task: dict) -> str:
    skills = " ".join(s.get("name", "") for s in task.get("skills") or [])
    return " ".join([task.get("title") or "", task.get("description") or "", task.get("brief") or "", " ".join(task.get("acceptance") or []), skills])


def analyze(task: dict, cfg: dict, *, mission: str | None = None) -> dict:
    """Category, complexity, level and needs of one subtask (no model, no network)."""
    text = _text(task)
    team = task.get("team") or ""
    outputs = task.get("outputs") or []
    scores = {c: 0.0 for c in KEYWORDS}
    for cat, weight in TEAM_PRIOR.get(team, {}).items():
        scores[cat] += 2 * weight
    for cat, rx in KEYWORDS.items():
        hits = {m.group(0).lower() for m in rx.finditer(text)}
        scores[cat] += min(len(hits), 5) * 0.6
    for out in outputs:
        ext = _ext(out)
        if ext in CODE_EXT:
            scores["coding"] += 0.5
        elif ext in TEXT_EXT:
            scores["creative"] += 0.2
            scores["research"] += 0.2
    for tool in ((cfg.get("teams") or {}).get(team) or {}).get("tools") or []:
        if tool in TOOL_HINT:
            cat, w = TOOL_HINT[tool]
            scores[cat] += w
    best = max(scores, key=lambda c: (scores[c], c == "coding"))
    category = best if scores[best] >= 1.0 else "general"

    complexity = 0.25
    complexity += min(max(len(task.get("description") or "") - 120, 0) / 100 * 0.04, 0.2)
    complexity += min(max(len(task.get("acceptance") or []) - 2, 0) * 0.05, 0.15)
    complexity += min(max(len(outputs) - 1, 0) * 0.05, 0.15)
    complexity += min(len(task.get("dependsOn") or []) * 0.05, 0.1)
    hard = {m.group(0).lower()[:6] for m in COMPLEX_RE.finditer(text)}
    if hard:
        complexity += min(0.12 + 0.06 * (len(hard) - 1), 0.3)
    if SIMPLE_RE.search(text):
        complexity -= 0.12
    if mission == "complex":
        complexity += 0.05
    complexity += min(int(task.get("revisions") or 0) * 0.15, 0.3)
    complexity = round(min(max(complexity, 0.0), 1.0), 2)
    if task.get("escalated"):
        complexity = max(complexity, 0.8)
    level = next(name for limit, name in LEVELS if complexity < limit)
    return {"category": category, "complexity": complexity, "level": level, "needs": dict(NEEDS[category]), "scores": {k: round(v, 2) for k, v in scores.items()}}


def score(model: dict, reading: dict, *, sub: bool = False) -> dict | None:
    """The affinity of one catalog model with one reading, or None when it may not be hired."""
    health = model.get("health") or {}
    if not model.get("ready") or health.get("state") in ("benched", "dead", "unready"):
        return None
    sp = model.get("specialties") or {}
    needs = reading["needs"]
    fit = sum(w * sp.get(k, 0.0) for k, w in needs.items()) / sum(needs.values())
    level, size = reading["level"], float(model.get("sizeB") or 0)
    total = fit
    notes = []
    need = MIN_SIZE[level]
    if need and size < need:
        total -= 0.1 + 0.3 * (1 - size / need)
        notes.append("small")
    elif WANT_SIZE[level] and size >= WANT_SIZE[level]:
        total += 0.1 if level == "complex" else 0.05
    if level == "simple" and size >= 200:
        total -= 0.05  # a giant is wasted on a simple task
    total += COST[level].get(model.get("costTier"), 0.0)
    if sp.get("toolUse", 0.0) < TOOL_FLOOR:
        total -= 0.15
        notes.append("json")
    if (model.get("context") or 0) < 16_000:
        total -= 0.1
        notes.append("context")
    rate = health.get("successRate")
    if rate is not None:
        total += 0.1 * (rate - 0.8)
    if sub:
        total += 0.05 * sp.get("speed", 0.0)  # a sub-agent is an extra pair of hands: quick ones help most
    if health.get("state") == "cooling":
        total -= 1.0  # still an option, the last one
        notes.append("cooling")
    top = max(needs, key=lambda k: (needs[k], k))
    return {"key": model["key"], "score": round(total, 3), "fit": round(fit, 3), "tier": model.get("tier"), "sizeB": model.get("sizeB"), "costTier": model.get("costTier"), "top": top, "topScore": sp.get(top), "notes": notes}


def rank(reading: dict, catalog: list[dict], *, limit: int = DEFAULT_CHAIN, sub: bool = False) -> list[dict]:
    scored = [s for s in (score(m, reading, sub=sub) for m in catalog) if s]
    scored.sort(key=lambda s: (-s["score"], s["key"]))
    return scored[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _catalog(router) -> list[dict]:
    fn = getattr(router, "catalog", None)
    return fn() if fn else []


def hire(task: dict, cfg: dict, router, *, mission: str | None = None, sub: bool = False) -> dict:
    """The hiring record of one subtask: its reading, its chain, the hired model."""
    reading = analyze(task, cfg, mission=mission)
    limit = int(((cfg.get("router") or {}).get("hiring") or {}).get("chain", DEFAULT_CHAIN))
    chain = rank(reading, _catalog(router), limit=limit, sub=sub)
    old = task.get("hire") or {}
    return {
        "at": _now(),
        "category": reading["category"],
        "level": reading["level"],
        "complexity": reading["complexity"],
        "needs": reading["needs"],
        "chain": chain,
        "chosen": chain[0]["key"] if chain else None,
        "demo": not chain,
        "revisions": int(task.get("revisions") or 0),
        "escalated": bool(task.get("escalated")),
        "replacements": list(old.get("replacements") or []),
    }


def chain_keys(task: dict) -> list[str]:
    return [c["key"] for c in (task.get("hire") or {}).get("chain") or []]


def promote(task: dict, res: dict, cfg: dict, router) -> dict | None:
    """The hired model failed and another one answered: the record of the
    replacement, with the chain ranked again (the one that answered first),
    or None when nothing changed."""
    rec = task.get("hire") or {}
    chosen, target = rec.get("chosen"), res.get("target")
    if not chosen or not target or target == chosen or str(target).startswith("mock/"):
        return None
    failed = res.get("failed") or []
    reason = next((f["kind"] for f in failed if f.get("target") == chosen), None)
    if reason is None:
        # skipped, not failed, in this call: benched or cooling since another task's call
        h = router.health(chosen) if hasattr(router, "health") else {}
        reason = {"benched": "quota" if h.get("reason") == "quota_exhausted" else "auth", "dead": "model_not_found", "cooling": "cooling"}.get(h.get("state")) or (failed[0]["kind"] if failed else "switch")
    reading = {"category": rec.get("category", "general"), "level": rec.get("level", "medium"), "needs": rec.get("needs") or NEEDS["general"]}
    limit = int(((cfg.get("router") or {}).get("hiring") or {}).get("chain", DEFAULT_CHAIN))
    ranked = rank(reading, _catalog(router), limit=limit + 1)
    first = next((c for c in ranked if c["key"] == target), None) or {"key": target, "score": None, "fit": None, "tier": None, "sizeB": None, "costTier": None, "top": None, "topScore": None, "notes": ["fallback"]}
    chain = [first] + [c for c in ranked if c["key"] != target][: limit - 1]
    return {**rec, "at": _now(), "chain": chain, "chosen": target, "demo": False, "replacements": [*(rec.get("replacements") or []), {"from": chosen, "to": target, "reason": reason, "at": _now()}]}


def size_label(size) -> str:
    if size is None:
        return "?"
    return f"{int(size)}B" if float(size) == int(size) else f"{size}B"
