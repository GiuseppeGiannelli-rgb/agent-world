"""Mirrors server/router/mock.js: the demo provider plays every role with
believable answers, reading the [[role:...]] marker in the system prompt.

N14: it answers in the run's language. It reads the language rule every
system prompt carries (prompts.language_rule), so nothing is added to the
prompts real models see, and takes its words from router/mock_texts.py.
With no language chosen (the legacy rule) it answers in English, the
project's default. The JSON shapes, tool names, paths and the hashes that
pick the demo's revisions stay the same in every language."""

import asyncio
import json
import random
import re

from backend.i18n import DEFAULT, LANGUAGES
from backend.prompts import language_rule
from backend.router.mock_texts import MOCK_TEXTS

FIELD_RE_CACHE: dict[str, re.Pattern] = {}
BLOCK_RE_CACHE: dict[str, re.Pattern] = {}
IMG_RE = re.compile(r"\.(png|jpe?g|webp|svg|gif)$", re.IGNORECASE)
AUDIO_RE = re.compile(r"\.(mp3|wav|ogg)$", re.IGNORECASE)
DOC_RE = re.compile(r"\.(pdf|docx|txt|md|csv|json)$", re.IGNORECASE)
# spec 09: the owner's files, as the brief and the "just added" messages list them
OWNER_RE = re.compile(r"^- (attachments/\S+) \(", re.MULTILINE)


def _hash(s: str) -> int:
    h = 2166136261
    for ch in s:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    return h


def field(text: str, name: str) -> str:
    pattern = FIELD_RE_CACHE.setdefault(name, re.compile(rf"^{re.escape(name)}:[ \t]*(.*)$", re.MULTILINE))
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def block(text: str, name: str) -> str:
    # Mirrors `${name}:[ \t]*\n([\s\S]*?)(?:\n\n|(?![\s\S]))` from mock.js:
    # non-greedy across lines, stopping at a blank line or end of string.
    pattern = BLOCK_RE_CACHE.setdefault(name, re.compile(rf"^{re.escape(name)}:[ \t]*\n(.*?)(?:\n\n|\Z)", re.MULTILINE | re.DOTALL))
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


def csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip() and x.strip() != "none"]


def short_goal(goal: str) -> str:
    g = re.sub(r"\s+", " ", goal).strip()
    return f"{g[:67]}…" if len(g) > 70 else g


# ---------- the language of the run ----------

# The rule's words up to the language name, taken from prompts.py itself: if
# its wording changes, the mock still reads it (test_prompts.py checks every builder).
_RULE_HEAD = language_rule(DEFAULT).split(LANGUAGES[DEFAULT])[0]
LANGUAGE_RE = re.compile(re.escape(_RULE_HEAD) + r"([A-Za-z]+)")
_BY_NAME = {name: code for code, name in LANGUAGES.items()}


def language_of(system: str) -> str | None:
    """The language the system prompt's rule asks for, None with the legacy rule."""
    m = LANGUAGE_RE.search(system or "")
    return _BY_NAME.get(m.group(1)) if m else None


def _texts(lang: str | None) -> dict:
    return MOCK_TEXTS.get(lang or DEFAULT) or MOCK_TEXTS[DEFAULT]


# ---------- CEO ----------

# The kind of mission, read from the GOAL's words in any of the five languages:
# the same goal makes the same plan whatever language it is written in.
WEB_RE = re.compile(
    r"web|sito|sitio|\bsite\b|landing|pagina|página|homepage|internetseite|html|\bapp|aplicaci|gioco|juego|\bjeux?\b|\bspiel|game"
    r"|dashboard|portfolio|negozio|tienda|boutique|\b(?:e-?|online)?shop|saas",
    re.IGNORECASE,
)
COMPLEX_RE = re.compile(
    r"compl[eèé]t|compless|komplett|vollständig|piattaforma|plataforma|plateforme|plattform|platform|saas"
    r"|campagn|campaña|kampagne|campaign|brand|marca|marque|\bmarke\b"
    r"|lancio|lanzamiento|lancement|\blaunch|markteinführung|e-?commerce|v[ií]d[eé]o|social|startup|agenzia|agencia|agence|agentur|agency",
    re.IGNORECASE,
)
VISUAL_RE = re.compile(
    r"immagin|im[aá]gen|\bimage|\bbild|titelbild|foto|photo|logo|brand|marca|visual|illustr|ilustr|hero|poster"
    r"|copertina|portada|couverture|\bcover|gr[aá]fic|graphi|grafik|social",
    re.IGNORECASE,
)
VOICE_RE = re.compile(r"voce|\bvoz\b|voix|stimme|sprecher|audio|podcast|spot|voice|narra|erzähl|locuci", re.IGNORECASE)


def ceo_plan(goal: str, lang: str = DEFAULT) -> dict:
    t = _texts(lang)
    web = bool(WEB_RE.search(goal))
    complex_ = len(goal) > 80 or bool(COMPLEX_RE.search(goal))
    visual = complex_ or bool(VISUAL_RE.search(goal))
    voice = bool(VOICE_RE.search(goal))
    ws: list[dict] = []

    def add(key: str, team: str, deliverables: list[str], depends_on: list[str]):
        w = t["ws"][key]
        ws.append(
            {
                "id": f"w{len(ws) + 1}",
                "team": team,
                "title": w["title"],
                "objective": w["objective"].format(goal=short_goal(goal)),
                "deliverables": deliverables,
                "acceptance": list(w["acceptance"]),
                "dependsOn": depends_on,
            }
        )

    if web:
        add("web_research", "research", ["research/notes.md"], [])
        add("web_design", "design", ["css/style.css"], [])
        add("web_content", "content", ["content/copy.md"], ["w1"])
        media: list[str] = []
        if complex_:
            add("web_prompts", "prompt", ["prompts/image-prompts.md"], ["w1"])
        if visual:
            add("web_images", "genai", ["assets/hero.png", "assets/gallery-1.png"] if complex_ else ["assets/hero.png"], ["w2", "w4"] if complex_ else ["w2"])
            media = [ws[-1]["id"]]
        if voice:
            add("web_voice", "genai", ["audio/voiceover.mp3"], ["w3"])
        add("web_dev", "dev", ["index.html", "js/app.js"], ["w2", "w3"] + media)
    else:
        add("doc_research", "research", ["research/overview.md"], [])
        add("doc_design", "design", ["design/layout.md"], [])
        add("doc_content", "content", ["output/report.md"], ["w1", "w2"])
        if visual:
            add("doc_cover", "genai", ["assets/cover.png"], ["w2"])
        if voice:
            add("doc_audio", "genai", ["audio/summary.mp3"], ["w3"])

    return {"complexity": "complex" if complex_ else "simple", "summary": t["plan_complex"] if complex_ else t["plan_simple"], "workstreams": ws}


# ---------- team lead ----------


def lead_plan(text: str, lang: str = DEFAULT) -> dict:
    t = _texts(lang)
    id_ = field(text, "WORKSTREAM ID")
    team = field(text, "WORKSTREAM TEAM")
    title = field(text, "WORKSTREAM")
    deliverables = csv(field(text, "DELIVERABLES"))
    if len(deliverables) >= 2:
        parts = [
            {
                "id": str(i + 1),
                "title": (t["part_image"] if IMG_RE.search(d) else t["part_file"]).format(name=d.split("/")[-1]),
                "description": t["part_description"].format(file=d, title=title),
                "acceptance": list(t["part_acceptance"]),
                "outputs": [d],
                "dependsOn": [],
            }
            for i, d in enumerate(deliverables)
        ]
        return {"subtasks": parts}
    d = deliverables[0] if deliverables else f"notes/{id_}.md"
    angles = t["angles"].get(team, t["angles"]["other"])
    parts = [
        {"id": str(i + 1), "title": a, "description": t["angle_description"].format(angle=a, title=title), "acceptance": list(t["angle_acceptance"]), "outputs": [f"notes/{id_}-{i + 1}.md"], "dependsOn": []}
        for i, a in enumerate(angles)
    ]
    parts.append({"id": str(len(parts) + 1), "title": t["final_title"], "description": t["final_description"].format(file=d), "acceptance": list(t["final_acceptance"]), "outputs": [d], "dependsOn": [p["id"] for p in parts]})
    return {"subtasks": parts}


# ---------- file contents ----------


def md_file(task: str, goal: str, revised: bool, lang: str = DEFAULT) -> str:
    md = _texts(lang)["md"]
    extra = f"\n## {md['revised_title']}\n" + "".join(f"- {x}\n" for x in md["revised_items"]) if revised else ""
    points = "\n".join(f"- {p}" for p in md["points"])
    details = "\n".join(f"{i}. **{label}**: {text}" for i, (label, text) in enumerate(md["detail_items"], 1))
    return f"""# {task}

> {md['goal_label']}: {goal}

## {md['key_points']}
{points}

## {md['details']}
{details}
{extra}_{md['signature']}_
"""


CSS = """:root {
  --bg: #fbf7f1;
  --ink: #26221d;
  --muted: #6d655b;
  --accent: #e7a83b;
  --card: #ffffff;
  --radius: 18px;
  --font: "Segoe UI Variable Display", system-ui, sans-serif;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: var(--font); background: var(--bg); color: var(--ink); line-height: 1.6; }
header { padding: 18px 6vw; display: flex; justify-content: space-between; align-items: center; }
.hero { padding: 10vh 6vw; display: grid; grid-template-columns: 1.1fr 1fr; gap: 40px; align-items: center; }
.hero img { width: 100%; border-radius: var(--radius); box-shadow: 0 20px 50px rgba(60, 40, 10, .18); }
.hero h1 { font-size: clamp(2.2rem, 5vw, 4rem); line-height: 1.05; margin: 0 0 16px; }
section { padding: 72px 6vw; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; }
.card { background: var(--card); border-radius: var(--radius); padding: 24px; box-shadow: 0 10px 30px rgba(60, 40, 10, .08); }
.btn { display: inline-block; padding: 12px 22px; border-radius: 999px; background: var(--ink); color: #fff; text-decoration: none; }
.btn:hover { background: var(--accent); }
footer { padding: 40px 6vw; color: var(--muted); }
@media (max-width: 760px) { .hero { grid-template-columns: 1fr; } }
"""


def page_images(files: list[str]) -> tuple[str | None, list[str]]:
    """The hero and the gallery of the page: the images the team put in assets/
    (whatever their format: spec 09, the owner's .jpg), or else the owner's own."""
    images = [f for f in files if IMG_RE.search(f)]
    # spec 09: a photo the owner gave with a change request takes the hero's place
    hero = next((f for f in images if re.match(r"^assets/hero-owner\.", f)), None) or next((f for f in images if re.match(r"^assets/hero\.", f)), None)
    gallery = [f for f in images if re.match(r"^assets/gallery-\d+\.", f)]
    if not hero and not gallery:
        owner = [f for f in images if f.startswith("attachments/")]
        if owner:
            hero, gallery = owner[0], owner[1:4]
    return hero, gallery


def html(goal: str, files: list[str], lang: str = DEFAULT) -> str:
    p = _texts(lang)["page"]
    lang = lang if lang in MOCK_TEXTS else DEFAULT
    hero_path, gallery_paths = page_images(files)
    hero = f'\n      <img src="{hero_path}" alt="">' if hero_path else ""
    gallery = "".join(f'\n        <article class="card"><img src="{g}" alt="" style="width:100%;border-radius:12px"></article>' for g in gallery_paths)
    cards = "\n".join(f"        <article class=\"card\"><h3>{h}</h3><p>{x}</p></article>" for h, x in p["cards"])
    return f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{short_goal(goal)}</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header><strong>{p['brand']}</strong><a class="btn" href="#contact">{p['contact_cta']}</a></header>
  <main>
    <section class="hero">
      <div>
        <h1>{short_goal(goal)}</h1>
        <p>{p['hero_text']}</p>
        <a class="btn" href="#services">{p['more']}</a>
      </div>{hero}
    </section>
    <section id="services">
      <h2>{p['services']}</h2>
      <div class="grid">
{cards}{gallery}
      </div>
    </section>
    <section id="contact">
      <h2>{p['contact_title']}</h2>
      <p>{p['contact_text']}</p>
    </section>
  </main>
  <footer>{p['footer']}</footer>
  <script src="js/app.js"></script>
</body>
</html>
"""


JS = """// Smooth reveal of sections while scrolling.
const observer = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) e.target.animate([{ opacity: 0, transform: 'translateY(16px)' }, { opacity: 1, transform: 'none' }], { duration: 500, fill: 'both' });
}, { threshold: 0.15 });
document.querySelectorAll('section').forEach((s) => observer.observe(s));
"""


def file_content(path: str, task: str, goal: str, revised: bool, files: list[str], lang: str = DEFAULT) -> str:
    if path.endswith(".css"):
        return CSS
    if path.endswith(".html"):
        return html(goal, files, lang)
    if path.endswith(".js"):
        return JS
    return md_file(task, goal, revised, lang)


# ---------- worker ----------


def _owner_pick(out: str, files: list[str]) -> str:
    """hero -> the first owner file, gallery-1 -> the second...: each output its own photo."""
    m = re.search(r"(\d+)", out.rsplit("/", 1)[-1])
    return files[(int(m.group(1)) if m else 0) % len(files)]


def worker_turn(messages: list[dict], team: str, lang: str = DEFAULT) -> dict:
    t = _texts(lang)
    say = t["thoughts"]
    brief = messages[1]["content"] if len(messages) > 1 else ""
    goal = field(brief, "GOAL")
    task_id = field(brief, "TASK ID")
    title = field(brief, "TASK")
    outputs = csv(field(brief, "OUTPUTS"))
    skills = csv(field(brief, "SKILLS"))
    input_files = [f for m in re.finditer(r"^\s+files: (.*)$", brief, re.MULTILINE) for f in csv(m.group(1)) if not IMG_RE.search(f) and not AUDIO_RE.search(f)]
    files = [m.group(1) for m in re.finditer(r"^(\S+) \(\d+ B\)$", brief, re.MULTILINE)]

    owner_text = "\n".join(str(m["content"]) for m in messages[1:] if m["role"] == "user" and "FILES FROM THE OWNER" in str(m["content"]))
    owner = list(dict.fromkeys(OWNER_RE.findall(owner_text)))
    owner_images = [f for f in owner if IMG_RE.search(f)]
    owner_audio = [f for f in owner if AUDIO_RE.search(f)]
    owner_docs = [f for f in owner if DOC_RE.search(f)]

    rev_index = -1
    for i, m in enumerate(messages):
        if m["role"] == "user" and str(m["content"]).startswith("REVISION REQUESTED"):
            rev_index = i
    since = len([m for m in messages[rev_index if rev_index >= 0 else 2 :] if m["role"] == "assistant"])
    revised = rev_index >= 0
    h = _hash(task_id + goal)
    text_out = [o for o in outputs if not IMG_RE.search(o) and not AUDIO_RE.search(o)]

    steps = []
    if revised:
        if text_out:
            steps.append({"thought": say["reread"], "tool": "read_file", "args": {"path": text_out[0]}})
    else:
        steps.append({"thought": say["list"], "tool": "list_files", "args": {"path": "."}})
        if h % 3 == 0:
            steps.append({"thought": say["recall"], "tool": "recall", "args": {"query": title}})
        if skills:
            steps.append({"thought": say["skill"].format(skill=skills[0]), "tool": "read_skill", "args": {"name": skills[0]}})
        if input_files:
            steps.append({"thought": say["inputs"].format(file=input_files[0]), "tool": "read_file", "args": {"path": input_files[0]}})
        if h % 4 == 1:
            steps.append({"thought": say["ask"], "tool": "ask_lead", "args": {"question": t["ask_question"].format(title=title)}})
        # spec 09: what the owner gave comes first
        if owner_docs:
            steps.append({"thought": say["read_doc"].format(file=owner_docs[0]), "tool": "read_document", "args": {"path": owner_docs[0]}})
        if owner_images and (team in ("genai", "design") or any(IMG_RE.search(o) for o in outputs)):
            steps.append({"thought": say["inspect"].format(file=owner_images[0]), "tool": "inspect_image", "args": {"path": owner_images[0]}})
    asked = any(m["role"] == "user" and "MESSAGE FROM THE OWNER about this task" in str(m["content"]) for m in messages)  # also kept by compact()
    if asked and owner_images and any(o.endswith(".html") for o in outputs) and "assets/hero-owner" not in " ".join(files):
        # spec 09: "use this photo instead": the newest owner photo becomes the hero, then the page is written again
        src = owner_images[-1]
        steps.append({"thought": say["use_file"].format(src=src, file="assets/hero-owner"), "tool": "use_attachment", "args": {"from": src, "path": f"assets/hero-owner{src[src.rfind('.'):]}"}})
        files = [*files, f"assets/hero-owner{src[src.rfind('.'):]}"]
    for out in outputs:
        if IMG_RE.search(out) and owner_images:
            src = _owner_pick(out, owner_images)
            steps.append({"thought": say["use_file"].format(src=src, file=out), "tool": "use_attachment", "args": {"from": src, "path": out}})
        elif AUDIO_RE.search(out) and owner_audio:
            src = _owner_pick(out, owner_audio)
            steps.append({"thought": say["use_file"].format(src=src, file=out), "tool": "use_attachment", "args": {"from": src, "path": out}})
        elif IMG_RE.search(out):
            # the image prompt stays in English: it is written for the image model, not for the user
            steps.append({"thought": say["image"].format(file=out), "tool": "generate_image", "args": {"prompt": f"{title}, {short_goal(goal)}, soft editorial light, warm palette, clean composition", "path": out}})
        elif AUDIO_RE.search(out):
            steps.append({"thought": say["voice"].format(file=out), "tool": "generate_speech", "args": {"text": t["voice_text"].format(goal=short_goal(goal)), "path": out}})
        else:
            steps.append({"thought": (say["fix"] if revised else say["write"]).format(file=out), "tool": "write_file", "args": {"path": out, "content": file_content(out, title, goal, revised, files, lang)}})
    if text_out:
        steps.append({"thought": say["check"], "tool": "read_file", "args": {"path": text_out[-1]}})
    if not revised and h % 3 == 2:
        steps.append({"thought": say["remember"], "tool": "remember", "args": {"title": t["remember_title"].format(title=title), "text": t["remember_text"], "tags": [team]}})
    steps.append(
        {
            "thought": say["finish"],
            "tool": "finish",
            "args": {
                "summary": (t["finish_revised"].format(files=", ".join(outputs)) if revised else t["finish_done"].format(title=title, files=", ".join(outputs) or t["notes_word"])),
                "files": outputs,
            },
        }
    )
    return steps[min(since, len(steps) - 1)]


# ---------- QA, lead help, CEO wrap-up ----------


def judge_turn(messages: list[dict], lang: str = DEFAULT) -> dict:
    t = _texts(lang)["judge"]
    text = messages[1]["content"] if len(messages) > 1 else ""
    task_id = field(text, "TASK ID")
    try:
        attempt = int(field(text, "ATTEMPT")) or 1
    except ValueError:
        attempt = 1
    goal = field(text, "GOAL")
    team = field(text, "TEAM")
    h = _hash(f"{task_id}|{goal}")
    strict = h % 5 < 2
    stubborn = h % 11 == 3
    if (attempt == 1 and strict) or (attempt == 2 and stubborn):
        return {"verdict": "revise", "score": 5 + attempt, "feedback": t["feedback"], "lesson": t["lesson"].format(team=team)}
    return {"verdict": "pass", "score": 8 + (h % 3), "feedback": "", "lesson": ""}


def report(messages: list[dict], lang: str = DEFAULT) -> str:
    r = _texts(lang)["report"]
    text = messages[1]["content"] if len(messages) > 1 else ""
    goal = field(text, "GOAL")
    ws = block(text, "WORKSTREAMS")
    files = block(text, "PROJECT FILES")
    how = r["how_index"] if "index.html" in files else r["how_docs"]
    return f"""# {r['title']}

**{r['goal']}:** {goal}

## {r['done']}
{ws}

## {r['files']}
{files}

## {r['how']}
- {how}

## {r['notes']}
- {r['demo']}
"""


def chat_reply(messages: list[dict], lang: str = DEFAULT) -> str:
    c = _texts(lang)["chat"]
    system = messages[0]["content"] if messages else ""
    m = re.search(r"You are ([^,]+),", system)
    name = m.group(1) if m else c["someone"]
    last = messages[-1]["content"] if messages else ""
    return (c["question"] if str(last).strip().endswith("?") else c["ack"]).format(name=name)


def refine_targets(text: str) -> dict:
    """The tasks a change names: those whose title shares a word with the
    directive, or else the one that owns the page, or else the last one."""
    directive = field(text, "DIRECTIVE")
    words = {w.lower() for w in re.findall(r"[\w']{5,}", directive)}
    rows = [r.split(" | ") for r in re.findall(r"^- (.+)$", block(text, "DONE TASKS") or text.split("DONE TASKS:", 1)[-1], re.MULTILINE)]
    rows = [r for r in rows if len(r) >= 4]
    picked = [r[0] for r in rows if words & {w.lower() for w in re.findall(r"[\w']{5,}", r[1])}]
    if not picked:
        page = [r[0] for r in rows if "index.html" in r[3]]
        picked = page[-1:] or [r[0] for r in rows[-1:]]
    return {"targets": [{"taskId": tid, "instruction": directive} for tid in picked[:3]]}


def answer(kind: str, messages: list[dict], team: str) -> str:
    system = messages[0]["content"] if messages else ""
    lang = language_of(system) or DEFAULT
    t = _texts(lang)
    if kind == "arbiter":
        a = t["arbiter"]
        return json.dumps({"options": [{"id": "a", "solution": a["a"], "why": a["why_a"]}, {"id": "b", "solution": a["b"], "why": a["why_b"]}], "pick": "a"})
    if kind == "refiner":
        return json.dumps(refine_targets(messages[1]["content"] if len(messages) > 1 else ""))
    if kind == "vision":
        content = messages[1]["content"] if len(messages) > 1 else ""
        text = "".join(p if isinstance(p, str) else (p or {}).get("text", "") for p in content) if isinstance(content, list) else str(content)
        m = re.search(r"^IMAGE: (\S+) \((.*)\)$", text, re.MULTILINE)
        return t["vision"].format(file=m.group(1) if m else "?", head=m.group(2) if m else "")
    user = messages[1]["content"] if len(messages) > 1 else ""
    if kind == "planner":
        return json.dumps(ceo_plan(block(user, "GOAL") or field(user, "GOAL"), lang))
    if kind == "lead":
        return json.dumps(lead_plan(user, lang))
    if kind == "librarian":
        ids = [m.group(1) for m in re.finditer(r"^- id: (\S+) \|", user, re.MULTILINE)][:2]
        return json.dumps({"picks": [{"id": i, "why": t["librarian_why"]} for i in ids]})
    if kind == "prompteng":
        p = t["prompteng"]
        return json.dumps({"brief": p["brief"].format(title=field(user, "TASK")), "acceptance": list(p["acceptance"]), "pitfalls": list(p["pitfalls"])})
    if kind == "judge":
        return json.dumps(judge_turn(messages, lang))
    if kind == "advisor":
        return t["advisor"]
    if kind == "rescue":
        return json.dumps({"action": "retry", "guidance": t["rescue"]})
    if kind == "synth":
        return report(messages, lang)
    if kind == "chat":
        return chat_reply(messages, lang)
    if not re.match(r"^\[\[role:", system):
        return "pong"
    return json.dumps(worker_turn(messages, team, lang))


ROLE_RE = re.compile(r"\[\[role:([a-z]+)(?::([a-z]+))?\]\]")


async def _mock_answer(provider: dict, req: dict) -> tuple[str, dict]:
    """The simulated answer after the simulated latency, with its usage."""
    system = next((m["content"] for m in req["messages"] if m["role"] == "system"), "")
    m = ROLE_RE.search(system)
    marker, team = (m.group(1), m.group(2) or "") if m else ("other", "")
    lo, hi = provider.get("latencyMs", [700, 1900])
    slow = 1.5 if marker in ("planner", "synth", "lead") else 1
    await asyncio.sleep((lo + random.random() * (hi - lo)) * slow / 1000)
    text = answer(marker, req["messages"], team)
    prompt_chars = sum(len(str(m["content"])) for m in req["messages"])
    return text, {"in": -(-prompt_chars // 4), "out": -(-len(text) // 4)}


async def mock_chat(provider: dict, model: str, req: dict) -> dict:
    text, usage = await _mock_answer(provider, req)
    return {"text": text, "model": model, "usage": usage}


STREAM_PIECE_RE = re.compile(r"\S+\s*|\s+")


def stream_pieces(text: str, words: int = 3) -> list[str]:
    """The answer in pieces of a few words, spaces included: joined, the same text."""
    tokens = STREAM_PIECE_RE.findall(text)
    return ["".join(tokens[i : i + words]) for i in range(0, len(tokens), words)]


async def mock_stream(provider: dict, model: str, req: dict):
    """Spec 11 T05: the simulator streams like a provider: the answer of
    mock_chat in pieces of a few words, a short pause between them (the
    whole stream stays under ~2.5 s however long the answer)."""
    text, usage = await _mock_answer(provider, req)
    pieces = stream_pieces(text)
    lo, hi = provider.get("streamMs", [8, 20])
    pause = min(lo + random.random() * (hi - lo), 2500 / max(1, len(pieces))) / 1000
    for i, piece in enumerate(pieces):
        if i:
            await asyncio.sleep(pause)
        yield {"text": piece}
    yield {"end": True, "usage": usage, "finish": "stop", "model": model}
