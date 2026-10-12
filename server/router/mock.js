// Demo provider: plays every role with believable answers so the whole
// company (CEO plan, team leads, sub-agents, skills, prompt lab, media,
// reviews, escalations, brain, report) can be watched without any API key.
// It reads the [[role:…]] marker at the top of the system prompt.

const sleep = (ms, signal) =>
  new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      clearTimeout(t);
      reject(signal.reason ?? new Error('aborted'));
    }, { once: true });
  });

function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return h >>> 0;
}

const field = (text, name) => text.match(new RegExp(`^${name}:[ \\t]*(.*)$`, 'm'))?.[1]?.trim() ?? '';

function block(text, name) {
  const m = text.match(new RegExp(`^${name}:[ \\t]*\\n([\\s\\S]*?)(?:\\n\\n|(?![\\s\\S]))`, 'm'));
  return m ? m[1].trim() : '';
}

const csv = (s) => s.split(',').map((x) => x.trim()).filter((x) => x && x !== 'none');
const IMG = /\.(png|jpe?g|webp|svg)$/i;
const AUDIO = /\.(mp3|wav|ogg)$/i;

function shortGoal(goal) {
  const g = goal.replace(/\s+/g, ' ').trim();
  return g.length > 70 ? `${g.slice(0, 67)}…` : g;
}

// ---------- CEO ----------

function ceoPlan(goal) {
  const web = /sito|landing|pagina|web|html|app|gioco|game|dashboard|portfolio|negozio|shop|saas/i.test(goal);
  const complex = goal.length > 80 || /complet|compless|piattaforma|saas|campagna|brand|lancio|e-?commerce|video|social|startup|agenzia/i.test(goal);
  const visual = complex || /immagin|foto|logo|brand|visual|illustr|hero|poster|copertina|grafica|social/i.test(goal);
  const voice = /voce|audio|podcast|spot|voice|narra/i.test(goal);
  const ws = [];
  const add = (w) => ws.push({ id: `w${ws.length + 1}`, ...w });
  if (web) {
    add({ team: 'research', title: 'Ricerca e requisiti', objective: `Capire pubblico, sezioni e riferimenti per "${shortGoal(goal)}".`, deliverables: ['research/notes.md'], acceptance: ['Pubblico e obiettivi chiari', 'Sezioni della pagina proposte', 'Almeno 3 riferimenti'], dependsOn: [] });
    add({ team: 'design', title: 'Sistema visivo', objective: 'Palette, tipografia e componenti in un foglio di stile riutilizzabile.', deliverables: ['css/style.css'], acceptance: ['Variabili CSS per colori e font', 'Layout responsive'], dependsOn: [] });
    add({ team: 'content', title: 'Testi e contenuti', objective: 'Titoli, testi di sezione e call to action dalle note di ricerca.', deliverables: ['content/copy.md'], acceptance: ['Un testo per ogni sezione', 'Call to action chiara'], dependsOn: ['w1'] });
    let media = [];
    if (complex) add({ team: 'prompt', title: 'Prompt per le immagini', objective: 'Prompt precisi e coerenti con lo stile per ogni immagine della pagina.', deliverables: ['prompts/image-prompts.md'], acceptance: ['Un prompt per immagine', 'Stile coerente con la palette'], dependsOn: ['w1'] });
    if (visual) {
      const deps = complex ? ['w2', 'w4'] : ['w2'];
      add({ team: 'genai', title: 'Immagini generate', objective: 'Immagine hero e immagini di sezione coerenti con lo stile.', deliverables: complex ? ['assets/hero.png', 'assets/gallery-1.png'] : ['assets/hero.png'], acceptance: ['Immagini coerenti con la palette', 'Prompt documentati'], dependsOn: deps });
      media = [ws.at(-1).id];
    }
    if (voice) add({ team: 'genai', title: 'Voice-over', objective: 'Una voce narrante per il video di presentazione.', deliverables: ['audio/voiceover.mp3'], acceptance: ['Testo chiaro e breve'], dependsOn: ['w3'] });
    add({ team: 'dev', title: 'Sviluppo della pagina', objective: 'Pagina completa che integra stile, testi e immagini, con interazioni leggere.', deliverables: ['index.html', 'js/app.js'], acceptance: ['HTML semantico', 'Testi e stile integrati', 'Nessun segnaposto'], dependsOn: ['w2', 'w3', ...media] });
  } else {
    add({ team: 'research', title: 'Ricerca approfondita', objective: `Quadro completo su "${shortGoal(goal)}": concetti, attori, numeri, casi.`, deliverables: ['research/overview.md'], acceptance: ['Almeno 5 punti chiave', 'Fonti indicate'], dependsOn: [] });
    add({ team: 'design', title: 'Schema di presentazione', objective: 'Struttura visiva del documento finale.', deliverables: ['design/layout.md'], acceptance: ['Indice del documento', 'Indicazioni per tabelle'], dependsOn: [] });
    add({ team: 'content', title: 'Documento finale', objective: 'Documento che unisce ricerca e schema, con conclusioni operative.', deliverables: ['output/report.md'], acceptance: ['Segue lo schema', 'Conclusioni operative'], dependsOn: ['w1', 'w2'] });
    if (visual) add({ team: 'genai', title: 'Copertina', objective: 'Un\'immagine di copertina per il documento.', deliverables: ['assets/cover.png'], acceptance: ['Coerente con il tema'], dependsOn: ['w2'] });
    if (voice) add({ team: 'genai', title: 'Versione audio', objective: 'Sintesi vocale del documento.', deliverables: ['audio/summary.mp3'], acceptance: ['Testo chiaro'], dependsOn: ['w3'] });
  }
  return {
    complexity: complex ? 'complex' : 'simple',
    summary: complex
      ? 'Missione complessa: ricerca e design partono subito, il Prompt Lab prepara le immagini, i team lavorano in parallelo con sub-agenti e lo sviluppo integra tutto alla fine.'
      : 'Ricerca e design partono insieme, poi contenuti e sviluppo in sequenza dove serve.',
    workstreams: ws,
  };
}

// ---------- team lead ----------

function leadPlan(text) {
  const id = field(text, 'WORKSTREAM ID');
  const team = field(text, 'WORKSTREAM TEAM');
  const title = field(text, 'WORKSTREAM');
  const deliverables = csv(field(text, 'DELIVERABLES'));
  if (deliverables.length >= 2) {
    const parts = deliverables.map((d, i) => ({ id: String(i + 1), title: IMG.test(d) ? `Immagine ${d.split('/').pop()}` : `Parte ${d.split('/').pop()}`, description: `Produci ${d} per "${title}".`, acceptance: ['Completo e coerente con il resto del progetto', 'Nessun segnaposto'], outputs: [d], dependsOn: [] }));
    return { subtasks: parts };
  }
  const d = deliverables[0] ?? `notes/${id}.md`;
  const angles = {
    research: ['Mercato e pubblico', 'Concorrenti', 'Riferimenti e ispirazioni'],
    genai: ['Concept visivo', 'Prompt e varianti'],
    design: ['Palette e tipografia', 'Componenti'],
    content: ['Struttura e tono', 'Bozze di sezione'],
    dev: ['Struttura', 'Interazioni'],
    prompt: ['Analisi dello stile', 'Bozze dei prompt'],
  }[team] ?? ['Analisi', 'Bozza'];
  const parts = angles.map((a, i) => ({ id: String(i + 1), title: a, description: `${a} per "${title}".`, acceptance: ['Note chiare e utilizzabili dal resto del team'], outputs: [`notes/${id}-${i + 1}.md`], dependsOn: [] }));
  parts.push({ id: String(parts.length + 1), title: 'Integrazione finale', description: `Unisci le parti in ${d}.`, acceptance: ['Usa tutte le parti del team', 'Risultato finale completo'], outputs: [d], dependsOn: parts.map((p) => p.id) });
  return { subtasks: parts };
}

// ---------- file contents ----------

function mdFile(task, goal, revised) {
  return `# ${task}

> Obiettivo: ${goal}

## Punti chiave
- Pubblico principale e bisogni, descritti in modo concreto.
- Cosa distingue questo progetto dalle alternative.
- Il messaggio da comunicare in una frase.

## Dettagli
1. **Contesto**: perché il progetto esiste e cosa risolve.
2. **Struttura**: le parti principali e il loro ordine.
3. **Esempi**: tre riferimenti da cui prendere spunto.
${revised ? '\n## Aggiunte dopo la revisione\n- Esempi concreti con dati e numeri.\n- Ogni criterio di accettazione è coperto da una sezione dedicata.\n' : ''}
_Scritto dall'agente come parte del lavoro di squadra._
`;
}

const CSS = `:root {
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
`;

function html(goal, files) {
  const hero = files.includes('assets/hero.png') ? '\n      <img src="assets/hero.png" alt="">' : '';
  const gallery = files.includes('assets/gallery-1.png') ? '\n        <article class="card"><img src="assets/gallery-1.png" alt="" style="width:100%;border-radius:12px"></article>' : '';
  return `<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${shortGoal(goal)}</title>
  <link rel="stylesheet" href="css/style.css">
</head>
<body>
  <header><strong>Progetto</strong><a class="btn" href="#contatti">Contattaci</a></header>
  <main>
    <section class="hero">
      <div>
        <h1>${shortGoal(goal)}</h1>
        <p>Una pagina costruita da un'azienda di agenti: ricerca, design, testi, immagini e sviluppo.</p>
        <a class="btn" href="#servizi">Scopri di più</a>
      </div>${hero}
    </section>
    <section id="servizi">
      <h2>Cosa offriamo</h2>
      <div class="grid">
        <article class="card"><h3>Chiarezza</h3><p>Un messaggio semplice, scritto per chi legge.</p></article>
        <article class="card"><h3>Velocità</h3><p>Una pagina leggera che si apre subito.</p></article>
        <article class="card"><h3>Cura</h3><p>Ogni dettaglio rivisto prima della consegna.</p></article>${gallery}
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
`;
}

const JS = `// Smooth reveal of sections while scrolling.
const observer = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) e.target.animate([{ opacity: 0, transform: 'translateY(16px)' }, { opacity: 1, transform: 'none' }], { duration: 500, fill: 'both' });
}, { threshold: 0.15 });
document.querySelectorAll('section').forEach((s) => observer.observe(s));
`;

function fileContent(path, task, goal, revised, files) {
  if (path.endsWith('.css')) return CSS;
  if (path.endsWith('.html')) return html(goal, files);
  if (path.endsWith('.js')) return JS;
  return mdFile(task, goal, revised);
}

// ---------- worker ----------

function workerTurn(messages, team) {
  const brief = messages[1]?.content ?? '';
  const goal = field(brief, 'GOAL');
  const taskId = field(brief, 'TASK ID');
  const title = field(brief, 'TASK');
  const outputs = csv(field(brief, 'OUTPUTS'));
  const skills = csv(field(brief, 'SKILLS'));
  const inputFiles = [...brief.matchAll(/^\s+files: (.*)$/gm)].flatMap((m) => csv(m[1])).filter((f) => !IMG.test(f) && !AUDIO.test(f));
  const files = [...brief.matchAll(/^(\S+) \(\d+ B\)$/gm)].map((m) => m[1]);

  let revIndex = -1;
  messages.forEach((m, i) => {
    if (m.role === 'user' && m.content.startsWith('REVISION REQUESTED')) revIndex = i;
  });
  const since = messages.slice(revIndex >= 0 ? revIndex : 2).filter((m) => m.role === 'assistant').length;
  const revised = revIndex >= 0;
  const h = hash(taskId + goal);
  const textOut = outputs.filter((o) => !IMG.test(o) && !AUDIO.test(o));

  const steps = [];
  if (revised) {
    if (textOut[0]) steps.push({ thought: 'Rileggo il file per capire cosa sistemare.', tool: 'read_file', args: { path: textOut[0] } });
  } else {
    steps.push({ thought: 'Guardo cosa c\'è già nella cartella del progetto.', tool: 'list_files', args: { path: '.' } });
    if (h % 3 === 0) steps.push({ thought: 'Controllo se il Brain ha lezioni utili.', tool: 'recall', args: { query: title } });
    if (skills[0]) steps.push({ thought: `Ripasso la skill "${skills[0]}".`, tool: 'read_skill', args: { name: skills[0] } });
    if (inputFiles[0]) steps.push({ thought: `Leggo il lavoro dei compagni: ${inputFiles[0]}.`, tool: 'read_file', args: { path: inputFiles[0] } });
    if (h % 4 === 1) steps.push({ thought: 'Chiedo una conferma al mio lead.', tool: 'ask_lead', args: { question: `Per "${title}" punto su un tono diretto e concreto: va bene?` } });
  }
  for (const out of outputs) {
    if (IMG.test(out)) {
      steps.push({ thought: `Genero l'immagine ${out}.`, tool: 'generate_image', args: { prompt: `${title}, ${shortGoal(goal)}, soft editorial light, warm palette, clean composition`, path: out } });
    } else if (AUDIO.test(out)) {
      steps.push({ thought: `Registro la voce per ${out}.`, tool: 'generate_speech', args: { text: `${shortGoal(goal)}. Scopri di più sul nostro progetto.`, path: out } });
    } else {
      steps.push({ thought: revised ? `Correggo ${out} seguendo il feedback.` : `Scrivo ${out}.`, tool: 'write_file', args: { path: out, content: fileContent(out, title, goal, revised, files) } });
    }
  }
  if (textOut.length) steps.push({ thought: 'Ricontrollo il risultato prima di consegnare.', tool: 'read_file', args: { path: textOut.at(-1) } });
  if (!revised && h % 3 === 2) steps.push({ thought: 'Salvo una lezione utile nel Brain.', tool: 'remember', args: { title: `Come fare: ${title}`, text: 'Partire dai file dei compagni e chiudere ogni sezione con un esempio concreto.', tags: [team] } });
  steps.push({ thought: 'Tutti i criteri sono coperti: consegno.', tool: 'finish', args: { summary: revised ? `Ho corretto ${outputs.join(', ')} seguendo ogni punto della revisione.` : `Ho completato "${title}" in ${outputs.join(', ') || 'note'} e ho verificato il risultato.`, files: outputs } });
  return steps[Math.min(since, steps.length - 1)];
}

// ---------- QA, lead help, CEO wrap-up ----------

function judgeTurn(messages) {
  const text = messages[1]?.content ?? '';
  const taskId = field(text, 'TASK ID');
  const attempt = Number(field(text, 'ATTEMPT')) || 1;
  const goal = field(text, 'GOAL');
  const team = field(text, 'TEAM');
  const h = hash(`${taskId}|${goal}`);
  const strict = h % 5 < 2;
  const stubborn = h % 11 === 3;
  if ((attempt === 1 && strict) || (attempt === 2 && stubborn)) {
    return {
      verdict: 'revise',
      score: 5 + attempt,
      feedback: '1. Mancano esempi concreti: aggiungine almeno due con dati reali.\n2. Un criterio di accettazione non è coperto in modo esplicito: dedicagli una sezione.',
      lesson: `Nei task del team ${team}: coprire ogni criterio di accettazione con una sezione esplicita e almeno un esempio concreto.`,
    };
  }
  return { verdict: 'pass', score: 8 + (h % 3), feedback: '', lesson: '' };
}

function report(messages) {
  const text = messages[1]?.content ?? '';
  const goal = field(text, 'GOAL');
  const ws = block(text, 'WORKSTREAMS');
  const files = block(text, 'PROJECT FILES');
  const hasIndex = /index\.html/.test(files);
  return `# Report finale

**Obiettivo:** ${goal}

## Cosa ha fatto l'azienda
${ws}

## File
${files}

## Come usarlo
${hasIndex ? '- Apri l\'anteprima dal pannello **Output** oppure apri `index.html` nella cartella del progetto.' : '- Apri i file markdown nella cartella del progetto, partendo dal documento finale.'}

## Note
- Run eseguito in **modalità demo**: risposte e immagini sono simulate. Aggiungi una chiave in \`.env\` per far lavorare modelli veri.
`;
}

function chatReply(messages) {
  const system = messages[0]?.content ?? '';
  const name = system.match(/You are ([^,]+),/)?.[1] ?? 'L\'agente';
  const last = messages.at(-1)?.content ?? '';
  if (/\?$/.test(last.trim())) return `Sono ${name}. In questo momento seguo il lavoro del mio team: ti rispondo appena ho il quadro completo, intanto puoi vedere i dettagli nella board.`;
  return `Ricevuto, ci penso io: lo passo subito al team e lo teniamo presente da adesso. (${name})`;
}

function answer(kind, messages, team) {
  const user = messages[1]?.content ?? '';
  switch (kind) {
    case 'planner':
      return JSON.stringify(ceoPlan(block(user, 'GOAL') || field(user, 'GOAL')));
    case 'lead':
      return JSON.stringify(leadPlan(user));
    case 'librarian': {
      const ids = [...user.matchAll(/^- id: (\S+) \|/gm)].map((m) => m[1]).slice(0, 2);
      return JSON.stringify({ picks: ids.map((id) => ({ id, why: 'Copre il modo di lavorare richiesto dal task.' })) });
    }
    case 'prompteng': {
      const title = field(user, 'TASK');
      return JSON.stringify({
        brief: `Obiettivo: ${title}, concreto e pronto da usare.\nStruttura: parti dai file dei compagni, poi produci i file richiesti completi.\nQualità: ogni sezione con un esempio reale, niente frasi generiche.\nVerifica: rileggi i file e spunta ogni criterio prima di consegnare.`,
        acceptance: ['Il risultato è coerente con gli altri file del progetto'],
        pitfalls: ['Testi generici o segnaposto', 'Ignorare il lavoro dei compagni'],
      });
    }
    case 'judge':
      return JSON.stringify(judgeTurn(messages));
    case 'advisor':
      return 'Sì, vai con un tono diretto e concreto. Tieni le frasi brevi e chiudi ogni sezione con un\'azione chiara.';
    case 'rescue':
      return JSON.stringify({ action: 'retry', guidance: 'Riparti dai criteri di accettazione uno per uno e verifica ciascuno nel file prima di consegnare.' });
    case 'synth':
      return report(messages);
    case 'chat':
      return chatReply(messages);
    default:
      if (!/^\[\[role:/.test(messages[0]?.content ?? '')) return 'pong';
      return JSON.stringify(workerTurn(messages, team));
  }
}

export async function mockChat(provider, model, req, signal) {
  const system = req.messages.find((m) => m.role === 'system')?.content ?? '';
  const [, marker = 'other', team = ''] = system.match(/\[\[role:([a-z]+)(?::([a-z]+))?\]\]/) ?? [];
  const [min, max] = provider.latencyMs ?? [700, 1900];
  const slow = marker === 'planner' || marker === 'synth' || marker === 'lead' ? 1.5 : 1;
  await sleep((min + Math.random() * (max - min)) * slow, signal);
  const text = answer(marker, req.messages, team);
  const promptChars = req.messages.reduce((n, m) => n + String(m.content).length, 0);
  return { text, model, usage: { in: Math.ceil(promptChars / 4), out: Math.ceil(text.length / 4) } };
}
