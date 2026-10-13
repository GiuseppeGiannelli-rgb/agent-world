"""Mirrors server/router/mock.js: the demo provider plays every role with
believable answers, reading the [[role:...]] marker in the system prompt."""

import asyncio
import json
import random
import re

FIELD_RE_CACHE: dict[str, re.Pattern] = {}
BLOCK_RE_CACHE: dict[str, re.Pattern] = {}
IMG_RE = re.compile(r"\.(png|jpe?g|webp|svg)$", re.IGNORECASE)
AUDIO_RE = re.compile(r"\.(mp3|wav|ogg)$", re.IGNORECASE)


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


# ---------- CEO ----------


def ceo_plan(goal: str) -> dict:
    web = bool(re.search(r"sito|landing|pagina|web|html|app|gioco|game|dashboard|portfolio|negozio|shop|saas", goal, re.IGNORECASE))
    complex_ = len(goal) > 80 or bool(re.search(r"complet|compless|piattaforma|saas|campagna|brand|lancio|e-?commerce|video|social|startup|agenzia", goal, re.IGNORECASE))
    visual = complex_ or bool(re.search(r"immagin|foto|logo|brand|visual|illustr|hero|poster|copertina|grafica|social", goal, re.IGNORECASE))
    voice = bool(re.search(r"voce|audio|podcast|spot|voice|narra", goal, re.IGNORECASE))
    ws: list[dict] = []

    def add(w):
        ws.append({"id": f"w{len(ws) + 1}", **w})

    if web:
        add({"team": "research", "title": "Ricerca e requisiti", "objective": f'Capire pubblico, sezioni e riferimenti per "{short_goal(goal)}".', "deliverables": ["research/notes.md"], "acceptance": ["Pubblico e obiettivi chiari", "Sezioni della pagina proposte", "Almeno 3 riferimenti"], "dependsOn": []})
        add({"team": "design", "title": "Sistema visivo", "objective": "Palette, tipografia e componenti in un foglio di stile riutilizzabile.", "deliverables": ["css/style.css"], "acceptance": ["Variabili CSS per colori e font", "Layout responsive"], "dependsOn": []})
        add({"team": "content", "title": "Testi e contenuti", "objective": "Titoli, testi di sezione e call to action dalle note di ricerca.", "deliverables": ["content/copy.md"], "acceptance": ["Un testo per ogni sezione", "Call to action chiara"], "dependsOn": ["w1"]})
        media: list[str] = []
        if complex_:
            add({"team": "prompt", "title": "Prompt per le immagini", "objective": "Prompt precisi e coerenti con lo stile per ogni immagine della pagina.", "deliverables": ["prompts/image-prompts.md"], "acceptance": ["Un prompt per immagine", "Stile coerente con la palette"], "dependsOn": ["w1"]})
        if visual:
            deps = ["w2", "w4"] if complex_ else ["w2"]
            add({"team": "genai", "title": "Immagini generate", "objective": "Immagine hero e immagini di sezione coerenti con lo stile.", "deliverables": ["assets/hero.png", "assets/gallery-1.png"] if complex_ else ["assets/hero.png"], "acceptance": ["Immagini coerenti con la palette", "Prompt documentati"], "dependsOn": deps})
            media = [ws[-1]["id"]]
        if voice:
            add({"team": "genai", "title": "Voice-over", "objective": "Una voce narrante per il video di presentazione.", "deliverables": ["audio/voiceover.mp3"], "acceptance": ["Testo chiaro e breve"], "dependsOn": ["w3"]})
        add({"team": "dev", "title": "Sviluppo della pagina", "objective": "Pagina completa che integra stile, testi e immagini, con interazioni leggere.", "deliverables": ["index.html", "js/app.js"], "acceptance": ["HTML semantico", "Testi e stile integrati", "Nessun segnaposto"], "dependsOn": ["w2", "w3"] + media})
    else:
        add({"team": "research", "title": "Ricerca approfondita", "objective": f'Quadro completo su "{short_goal(goal)}": concetti, attori, numeri, casi.', "deliverables": ["research/overview.md"], "acceptance": ["Almeno 5 punti chiave", "Fonti indicate"], "dependsOn": []})
        add({"team": "design", "title": "Schema di presentazione", "objective": "Struttura visiva del documento finale.", "deliverables": ["design/layout.md"], "acceptance": ["Indice del documento", "Indicazioni per tabelle"], "dependsOn": []})
        add({"team": "content", "title": "Documento finale", "objective": "Documento che unisce ricerca e schema, con conclusioni operative.", "deliverables": ["output/report.md"], "acceptance": ["Segue lo schema", "Conclusioni operative"], "dependsOn": ["w1", "w2"]})
        if visual:
            add({"team": "genai", "title": "Copertina", "objective": "Un'immagine di copertina per il documento.", "deliverables": ["assets/cover.png"], "acceptance": ["Coerente con il tema"], "dependsOn": ["w2"]})
        if voice:
            add({"team": "genai", "title": "Versione audio", "objective": "Sintesi vocale del documento.", "deliverables": ["audio/summary.mp3"], "acceptance": ["Testo chiaro"], "dependsOn": ["w3"]})

    return {
        "complexity": "complex" if complex_ else "simple",
        "summary": (
            "Missione complessa: ricerca e design partono subito, il Prompt Lab prepara le immagini, i team lavorano in parallelo con sub-agenti e lo sviluppo integra tutto alla fine."
            if complex_
            else "Ricerca e design partono insieme, poi contenuti e sviluppo in sequenza dove serve."
        ),
        "workstreams": ws,
    }


# ---------- team lead ----------


def lead_plan(text: str) -> dict:
    id_ = field(text, "WORKSTREAM ID")
    team = field(text, "WORKSTREAM TEAM")
    title = field(text, "WORKSTREAM")
    deliverables = csv(field(text, "DELIVERABLES"))
    if len(deliverables) >= 2:
        parts = [
            {
                "id": str(i + 1),
                "title": f"Immagine {d.split('/')[-1]}" if IMG_RE.search(d) else f"Parte {d.split('/')[-1]}",
                "description": f'Produci {d} per "{title}".',
                "acceptance": ["Completo e coerente con il resto del progetto", "Nessun segnaposto"],
                "outputs": [d],
                "dependsOn": [],
            }
            for i, d in enumerate(deliverables)
        ]
        return {"subtasks": parts}
    d = deliverables[0] if deliverables else f"notes/{id_}.md"
    angles = {
        "research": ["Mercato e pubblico", "Concorrenti", "Riferimenti e ispirazioni"],
        "genai": ["Concept visivo", "Prompt e varianti"],
        "design": ["Palette e tipografia", "Componenti"],
        "content": ["Struttura e tono", "Bozze di sezione"],
        "dev": ["Struttura", "Interazioni"],
        "prompt": ["Analisi dello stile", "Bozze dei prompt"],
    }.get(team, ["Analisi", "Bozza"])
    parts = [
        {"id": str(i + 1), "title": a, "description": f'{a} per "{title}".', "acceptance": ["Note chiare e utilizzabili dal resto del team"], "outputs": [f"notes/{id_}-{i + 1}.md"], "dependsOn": []}
        for i, a in enumerate(angles)
    ]
    parts.append({"id": str(len(parts) + 1), "title": "Integrazione finale", "description": f"Unisci le parti in {d}.", "acceptance": ["Usa tutte le parti del team", "Risultato finale completo"], "outputs": [d], "dependsOn": [p["id"] for p in parts]})
    return {"subtasks": parts}


# ---------- file contents ----------


def md_file(task: str, goal: str, revised: bool) -> str:
    extra = (
        "\n## Aggiunte dopo la revisione\n- Esempi concreti con dati e numeri.\n- Ogni criterio di accettazione è coperto da una sezione dedicata.\n"
        if revised
        else ""
    )
    return f"""# {task}

> Obiettivo: {goal}

## Punti chiave
- Pubblico principale e bisogni, descritti in modo concreto.
- Cosa distingue questo progetto dalle alternative.
- Il messaggio da comunicare in una frase.

## Dettagli
1. **Contesto**: perché il progetto esiste e cosa risolve.
2. **Struttura**: le parti principali e il loro ordine.
3. **Esempi**: tre riferimenti da cui prendere spunto.
{extra}_Scritto dall'agente come parte del lavoro di squadra._
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


def html(goal: str, files: list[str]) -> str:
    hero = '\n      <img src="assets/hero.png" alt="">' if "assets/hero.png" in files else ""
    gallery = '\n        <article class="card"><img src="assets/gallery-1.png" alt="" style="width:100%;border-radius:12px"></article>' if "assets/gallery-1.png" in files else ""
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{short_goal(goal)}</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header><strong>Progetto</strong><a class="btn" href="#contatti">Contattaci</a></header>
  <main>
    <section class="hero">
      <div>
        <h1>{short_goal(goal)}</h1>
        <p>Una pagina costruita da un'azienda di agenti: ricerca, design, testi, immagini e sviluppo.</p>
        <a class="btn" href="#servizi">Scopri di più</a>
      </div>{hero}
    </section>
    <section id="servizi">
      <h2>Cosa offriamo</h2>
      <div class="grid">
        <article class="card"><h3>Chiarezza</h3><p>Un messaggio semplice, scritto per chi legge.</p></article>
        <article class="card"><h3>Velocità</h3><p>Una pagina leggera che si apre subito.</p></article>
        <article class="card"><h3>Cura</h3><p>Ogni dettaglio rivisto prima della consegna.</p></article>{gallery}
      </div>
    </section>
    <section id="contatti">
      <h2>Parliamone</h2>
      <p>Scrivici e ti rispondiamo entro un giorno.</p>
    </section>
  </main>
  <footer>Costruito con Agent World</footer>
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


def file_content(path: str, task: str, goal: str, revised: bool, files: list[str]) -> str:
    if path.endswith(".css"):
        return CSS
    if path.endswith(".html"):
        return html(goal, files)
    if path.endswith(".js"):
        return JS
    return md_file(task, goal, revised)


# ---------- worker ----------


def worker_turn(messages: list[dict], team: str) -> dict:
    brief = messages[1]["content"] if len(messages) > 1 else ""
    goal = field(brief, "GOAL")
    task_id = field(brief, "TASK ID")
    title = field(brief, "TASK")
    outputs = csv(field(brief, "OUTPUTS"))
    skills = csv(field(brief, "SKILLS"))
    input_files = [f for m in re.finditer(r"^\s+files: (.*)$", brief, re.MULTILINE) for f in csv(m.group(1)) if not IMG_RE.search(f) and not AUDIO_RE.search(f)]
    files = [m.group(1) for m in re.finditer(r"^(\S+) \(\d+ B\)$", brief, re.MULTILINE)]

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
            steps.append({"thought": "Rileggo il file per capire cosa sistemare.", "tool": "read_file", "args": {"path": text_out[0]}})
    else:
        steps.append({"thought": "Guardo cosa c'è già nella cartella del progetto.", "tool": "list_files", "args": {"path": "."}})
        if h % 3 == 0:
            steps.append({"thought": "Controllo se il Brain ha lezioni utili.", "tool": "recall", "args": {"query": title}})
        if skills:
            steps.append({"thought": f'Ripasso la skill "{skills[0]}".', "tool": "read_skill", "args": {"name": skills[0]}})
        if input_files:
            steps.append({"thought": f"Leggo il lavoro dei compagni: {input_files[0]}.", "tool": "read_file", "args": {"path": input_files[0]}})
        if h % 4 == 1:
            steps.append({"thought": "Chiedo una conferma al mio lead.", "tool": "ask_lead", "args": {"question": f'Per "{title}" punto su un tono diretto e concreto: va bene?'}})
    for out in outputs:
        if IMG_RE.search(out):
            steps.append({"thought": f"Genero l'immagine {out}.", "tool": "generate_image", "args": {"prompt": f"{title}, {short_goal(goal)}, soft editorial light, warm palette, clean composition", "path": out}})
        elif AUDIO_RE.search(out):
            steps.append({"thought": f"Registro la voce per {out}.", "tool": "generate_speech", "args": {"text": f"{short_goal(goal)}. Scopri di più sul nostro progetto.", "path": out}})
        else:
            steps.append({"thought": (f"Correggo {out} seguendo il feedback." if revised else f"Scrivo {out}."), "tool": "write_file", "args": {"path": out, "content": file_content(out, title, goal, revised, files)}})
    if text_out:
        steps.append({"thought": "Ricontrollo il risultato prima di consegnare.", "tool": "read_file", "args": {"path": text_out[-1]}})
    if not revised and h % 3 == 2:
        steps.append({"thought": "Salvo una lezione utile nel Brain.", "tool": "remember", "args": {"title": f"Come fare: {title}", "text": "Partire dai file dei compagni e chiudere ogni sezione con un esempio concreto.", "tags": [team]}})
    steps.append(
        {
            "thought": "Tutti i criteri sono coperti: consegno.",
            "tool": "finish",
            "args": {
                "summary": (f"Ho corretto {', '.join(outputs)} seguendo ogni punto della revisione." if revised else f"Ho completato \"{title}\" in {', '.join(outputs) or 'note'} e ho verificato il risultato."),
                "files": outputs,
            },
        }
    )
    return steps[min(since, len(steps) - 1)]


# ---------- QA, lead help, CEO wrap-up ----------


def judge_turn(messages: list[dict]) -> dict:
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
        return {
            "verdict": "revise",
            "score": 5 + attempt,
            "feedback": "1. Mancano esempi concreti: aggiungine almeno due con dati reali.\n2. Un criterio di accettazione non è coperto in modo esplicito: dedicagli una sezione.",
            "lesson": f"Nei task del team {team}: coprire ogni criterio di accettazione con una sezione esplicita e almeno un esempio concreto.",
        }
    return {"verdict": "pass", "score": 8 + (h % 3), "feedback": "", "lesson": ""}


def report(messages: list[dict]) -> str:
    text = messages[1]["content"] if len(messages) > 1 else ""
    goal = field(text, "GOAL")
    ws = block(text, "WORKSTREAMS")
    files = block(text, "PROJECT FILES")
    has_index = "index.html" in files
    how = "- Apri l'anteprima dal pannello **Output** oppure apri `index.html` nella cartella del progetto." if has_index else "- Apri i file markdown nella cartella del progetto, partendo dal documento finale."
    return f"""# Report finale

**Obiettivo:** {goal}

## Cosa ha fatto l'azienda
{ws}

## File
{files}

## Come usarlo
{how}

## Note
- Run eseguito in **modalità demo**: risposte e immagini sono simulate. Aggiungi una chiave in `.env` per far lavorare modelli veri.
"""


def chat_reply(messages: list[dict]) -> str:
    system = messages[0]["content"] if messages else ""
    m = re.search(r"You are ([^,]+),", system)
    name = m.group(1) if m else "L'agente"
    last = messages[-1]["content"] if messages else ""
    if str(last).strip().endswith("?"):
        return f"Sono {name}. In questo momento seguo il lavoro del mio team: ti rispondo appena ho il quadro completo, intanto puoi vedere i dettagli nella board."
    return f"Ricevuto, ci penso io: lo passo subito al team e lo teniamo presente da adesso. ({name})"


def answer(kind: str, messages: list[dict], team: str) -> str:
    user = messages[1]["content"] if len(messages) > 1 else ""
    if kind == "planner":
        return json.dumps(ceo_plan(block(user, "GOAL") or field(user, "GOAL")))
    if kind == "lead":
        return json.dumps(lead_plan(user))
    if kind == "librarian":
        ids = [m.group(1) for m in re.finditer(r"^- id: (\S+) \|", user, re.MULTILINE)][:2]
        return json.dumps({"picks": [{"id": i, "why": "Copre il modo di lavorare richiesto dal task."} for i in ids]})
    if kind == "prompteng":
        title = field(user, "TASK")
        return json.dumps(
            {
                "brief": f"Obiettivo: {title}, concreto e pronto da usare.\nStruttura: parti dai file dei compagni, poi produci i file richiesti completi.\nQualità: ogni sezione con un esempio reale, niente frasi generiche.\nVerifica: rileggi i file e spunta ogni criterio prima di consegnare.",
                "acceptance": ["Il risultato è coerente con gli altri file del progetto"],
                "pitfalls": ["Testi generici o segnaposto", "Ignorare il lavoro dei compagni"],
            }
        )
    if kind == "judge":
        return json.dumps(judge_turn(messages))
    if kind == "advisor":
        return "Sì, vai con un tono diretto e concreto. Tieni le frasi brevi e chiudi ogni sezione con un'azione chiara."
    if kind == "rescue":
        return json.dumps({"action": "retry", "guidance": "Riparti dai criteri di accettazione uno per uno e verifica ciascuno nel file prima di consegnare."})
    if kind == "synth":
        return report(messages)
    if kind == "chat":
        return chat_reply(messages)
    if not re.match(r"^\[\[role:", messages[0]["content"] if messages else ""):
        return "pong"
    return json.dumps(worker_turn(messages, team))


ROLE_RE = re.compile(r"\[\[role:([a-z]+)(?::([a-z]+))?\]\]")


async def mock_chat(provider: dict, model: str, req: dict) -> dict:
    system = next((m["content"] for m in req["messages"] if m["role"] == "system"), "")
    m = ROLE_RE.search(system)
    marker, team = (m.group(1), m.group(2) or "") if m else ("other", "")
    lo, hi = provider.get("latencyMs", [700, 1900])
    slow = 1.5 if marker in ("planner", "synth", "lead") else 1
    await asyncio.sleep((lo + random.random() * (hi - lo)) * slow / 1000)
    text = answer(marker, req["messages"], team)
    prompt_chars = sum(len(str(m["content"])) for m in req["messages"])
    return {"text": text, "model": model, "usage": {"in": -(-prompt_chars // 4), "out": -(-len(text) // 4)}}
