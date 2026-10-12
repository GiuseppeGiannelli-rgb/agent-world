import { esc, markdown } from './md.js';
import { World } from './world/world.js';

const $ = (sel) => document.querySelector(sel);

const S = {
  config: null,
  agents: new Map(),
  run: null,
  view: null,
  runs: [],
  router: null,
  media: null,
  skills: { count: 0, sources: [], results: [], query: '' },
  brain: { count: 0, notes: [], query: '' },
  mode: 'demo',
  tab: 'board',
  filter: 'all',
  openTasks: new Set(),
  selected: null,
  team: null,
  files: null,
  chats: new Map(),
  speak: false,
};

const STATUS_LABEL = { planning: 'Pianificazione', awaiting_approval: 'Attende te', running: 'In corso', synthesizing: 'Report finale', completed: 'Completato', completed_with_failures: 'Completato con errori', failed: 'Fallito', stopped: 'Fermato' };
const TASK_STATUS = { queued: 'in coda', assigned: 'assegnato', working: 'al lavoro', review: 'in revisione', revise: 'da correggere', done: 'fatto', failed: 'fallito', skipped: 'saltato' };
const WS_STATUS = { queued: 'in coda', preparing: 'il lead organizza', running: 'in corso', done: 'fatto', failed: 'non completato', skipped: 'saltato' };
const AGENT_STATE = { idle: 'libero', fetching: 'prende il workstream', assigned: 'prende il task', thinking: 'ragiona', tool: 'lavora', waiting: 'attende revisione', reviewing: 'revisiona', verdict: 'dà il verdetto', delivering: 'consegna', paused: 'in pausa', asking: 'ti fa una domanda', celebrating: 'festeggia' };
const KIND_LABEL = { goal: 'obiettivo', plan: 'piano', brief: 'brief', split: 'scomposizione', skills: 'skill', prompt: 'prompt lab', spawn: 'sub-agente', assign: 'incarico', question: 'domanda', answer: 'risposta', review: 'revisione', pass: 'approvato', revise: 'da rivedere', deliver: 'consegna', escalate: 'escalation', stuck: 'bloccato', guidance: 'indicazioni', error: 'errore', system: 'sistema', report: 'report', chat: 'chat', ask_user: 'domanda per te', reply: 'tua risposta' };
const TOOL_LABEL = { list_files: '📂 elenca file', read_file: '📖 legge', write_file: '✍️ scrive', web_search: '🔎 cerca sul web', web_fetch: '🌐 legge una pagina', run_command: '⚙️ esegue', generate_image: '🎨 genera immagine', generate_speech: '🎙️ genera voce', search_skills: '📚 cerca skill', read_skill: '📘 legge skill', remember: '🧠 salva nel Brain', recall: '🧠 consulta il Brain', ask_lead: '❓ chiede al lead', ask_user: '🙋 chiede a te', finish: '✅ consegna' };
const EXAMPLES = [
  'Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi',
  'Una landing page per il mio studio di yoga',
  'Ricerca: confronto tra i principali framework JavaScript nel 2026, con copertina',
  'Uno spot audio di 20 secondi per una palestra, con testo e voce',
];
const TERMINAL = ['completed', 'completed_with_failures', 'failed', 'stopped'];
const TEXT_EXT = /\.(md|txt|html?|css|js|mjs|json|svg|csv|py|ts|tsx|jsx|yml|yaml|xml|sh)$/i;
const IMG_EXT = /\.(png|jpe?g|webp|gif|svg)$/i;
const AUDIO_EXT = /\.(mp3|wav|ogg)$/i;

const shown = () => S.view ?? S.run;
const isLive = (run) => run && !TERMINAL.includes(run.status);
const teamOf = (id) => S.config?.teams?.[id];
const teamColor = (id) => (id === 'ceo' ? S.config?.ceo?.color : teamOf(id)?.color) ?? '#888';
const teamLabel = (id) => (id === 'ceo' ? 'Regia' : teamOf(id)?.label ?? id);
const agentName = (id) => (id === 'user' ? 'Tu' : id === '*' ? 'Tutti' : S.agents.get(id)?.name ?? id);
const agentColor = (id) => {
  const a = S.agents.get(id);
  return id === 'user' ? '#8a6cf0' : a ? teamColor(a.kind === 'ceo' ? 'ceo' : a.team) : '#888';
};
const ago = (iso) => {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s fa`;
  if (s < 3600) return `${Math.round(s / 60)} min fa`;
  if (s < 86400) return `${Math.round(s / 3600)} h fa`;
  return new Date(iso).toLocaleDateString('it-IT');
};
const dur = (a, b) => {
  const s = Math.max(0, Math.round(((b ? new Date(b) : new Date()) - new Date(a)) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { 'content-type': 'application/json', ...(opts.headers ?? {}) } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? `Errore ${res.status}`);
  return body;
}

function toast(text, bad = false) {
  const el = document.createElement('div');
  el.className = `toast${bad ? ' bad' : ''}`;
  el.textContent = text;
  $('#toasts').append(el);
  setTimeout(() => el.remove(), 4500);
}

function savePref(k, v) {
  try {
    localStorage.setItem(`aw.${k}`, JSON.stringify(v));
  } catch {
    // storage unavailable: preferences just do not persist
  }
}
function loadPref(k, d) {
  try {
    const v = localStorage.getItem(`aw.${k}`);
    return v === null ? d : JSON.parse(v);
  } catch {
    return d;
  }
}

// ---------- voice ----------

function listen(btn, onText) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast('Il riconoscimento vocale non è disponibile in questo browser (prova Chrome o Edge).', true);
  if (btn.rec) {
    btn.rec.stop();
    return;
  }
  const r = new SR();
  r.lang = 'it-IT';
  r.interimResults = true;
  r.onresult = (e) => onText([...e.results].map((x) => x[0].transcript).join(' '), e.results[e.results.length - 1].isFinal);
  r.onerror = (e) => e.error !== 'no-speech' && toast(`Microfono: ${e.error}`, true);
  r.onend = () => {
    btn.classList.remove('rec');
    btn.rec = null;
  };
  btn.rec = r;
  btn.classList.add('rec');
  r.start();
}

function say(text) {
  if (!S.speak || !window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'it-IT';
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

// ---------- world ----------

const world = new World({
  canvas: $('#scene'),
  labels: $('#labels'),
  minimap: $('#minimap'),
  onPick: (id) => selectAgent(id),
  onPickRoom: (team) => selectTeam(team, true),
});
// handy from the browser console: agentWorld.camera, agentWorld.resetView()
window.agentWorld = world;

// ---------- render scheduling ----------

const dirty = new Set();
let raf = 0;
function invalidate(...parts) {
  parts.forEach((p) => dirty.add(p));
  if (!raf) {
    raf = requestAnimationFrame(() => {
      raf = 0;
      const list = [...dirty];
      dirty.clear();
      for (const p of list) RENDER[p]?.();
    });
  }
}

const RENDER = {
  top: renderTop,
  current: renderCurrent,
  waiting: renderWaiting,
  runs: renderRuns,
  board: () => S.tab === 'board' && renderBoard(),
  comms: () => S.tab === 'comms' && renderComms(),
  teams: () => S.tab === 'teams' && renderTeams(),
  skills: () => S.tab === 'skills' && renderSkills(),
  brain: () => S.tab === 'brain' && renderBrain(),
  router: () => S.tab === 'router' && renderRouter(),
  output: () => S.tab === 'output' && renderOutput(),
  roster: renderRoster,
  inspector: renderInspector,
  rooms: renderRoomStats,
};
const ALL = Object.keys(RENDER);

// ---------- top ----------

function renderTop() {
  const mode = $('#mode');
  mode.textContent = S.mode === 'live' ? 'LIVE' : 'DEMO';
  mode.className = `pill ${S.mode}`;
  mode.title = S.mode === 'live' ? 'Almeno un provider ha una chiave: i modelli sono veri.' : 'Nessuna chiave nel file .env: un simulatore interpreta ogni ruolo.';
  const r = S.run;
  const agents = [...S.agents.values()];
  const busy = agents.filter((a) => a.state !== 'idle').length;
  $('#stats').innerHTML = `<span><b>${agents.length}</b> agenti · <b>${busy}</b> al lavoro</span>${r ? `<span>Chiamate <b>${r.usage?.calls ?? 0}</b></span><span>Sub-agenti <b>${r.usage?.subAgents ?? 0}</b></span>` : ''}<span>🧠 <b>${S.brain.count}</b></span>`;
}

function renderRoomStats() {
  const stats = {};
  for (const a of S.agents.values()) {
    if (a.kind === 'ceo') continue;
    stats[a.team] ??= { agents: 0, busy: 0 };
    stats[a.team].agents += 1;
    if (a.state !== 'idle') stats[a.team].busy += 1;
  }
  world.setRoomStats(stats);
}

// ---------- left ----------

function renderWaiting() {
  const el = $('#waiting');
  const run = S.run;
  const open = isLive(run) ? run.waiting.filter((w) => w.status === 'open') : [];
  el.classList.toggle('hidden', !open.length);
  if (!open.length) {
    el.innerHTML = '';
    return;
  }
  // keep what the user is typing
  const drafts = Object.fromEntries([...el.querySelectorAll('textarea[data-wait]')].map((t) => [t.dataset.wait, t.value]));
  el.innerHTML = `<h3>🙋 In attesa di te · ${open.length}</h3>${open
    .map((w) => {
      const a = S.agents.get(w.from);
      return `<div class="wait-item">
        <div class="who"><b style="color:${agentColor(w.from)}">${esc(a?.name ?? w.from)}</b> · ${w.kind === 'plan' ? 'approvazione del piano' : `domanda su ${esc(w.taskId ?? '')}`}</div>
        <div class="q">${esc(w.text)}</div>
        <textarea data-wait="${w.id}" placeholder="${w.kind === 'plan' ? 'Note facoltative per la squadra…' : 'La tua risposta…'}">${esc(drafts[w.id] ?? '')}</textarea>
        <div class="row">${w.kind === 'plan' ? `<button class="btn go" data-answer="${w.id}" data-decision="approve">Approva</button><button class="btn danger" data-answer="${w.id}" data-decision="reject">Rifiuta</button>` : `<button class="btn go" data-answer="${w.id}">Rispondi</button>`}</div>
      </div>`;
    })
    .join('')}`;
}

function renderCurrent() {
  const run = shown();
  const el = $('#current');
  const live = isLive(S.run);
  $('#btn-start').disabled = Boolean(live);
  $('#btn-start').textContent = live ? 'L\'azienda è al lavoro…' : 'Avvia l\'azienda';
  if (!run) {
    el.innerHTML = '<div class="empty">Scrivi un obiettivo: la CEO lo divide tra i team, i lead scompongono il lavoro, lo Skill Hub assegna le skill e il QA rivede tutto.</div>';
    return;
  }
  const done = run.tasks.filter((t) => t.status === 'done').length;
  const total = run.tasks.length || 1;
  const controls = isLive(run) && run.id === S.run?.id
    ? `<div class="row" style="margin-top:10px">${run.paused ? '<button class="btn" data-act="resume">▶ Riprendi</button>' : '<button class="btn" data-act="pause">⏸ Pausa</button>'}<button class="btn danger" data-act="stop">■ Ferma</button></div>`
    : '';
  const ws = (run.workstreams ?? []).map((w) => {
    const ts = run.tasks.filter((t) => t.wsId === w.id);
    const d = ts.filter((t) => t.status === 'done').length;
    return `<div style="--team:${teamColor(w.team)}"><i></i><span>${esc(w.title)} <span class="muted">· ${esc(teamLabel(w.team))}</span></span><span class="muted">${ts.length ? `${d}/${ts.length}` : WS_STATUS[w.status]}</span></div>`;
  });
  el.innerHTML = `
    <h3>${S.view ? 'Run selezionato · <a href="#" data-act="back">torna al live</a>' : 'Missione attuale'}</h3>
    <div class="goal">${esc(run.goal)}</div>
    <div class="row" style="flex-wrap:wrap"><span class="status ${run.status}">${STATUS_LABEL[run.status] ?? run.status}${run.paused ? ' · pausa' : ''}</span>${run.complexity ? `<span class="badge cx">${run.complexity === 'complex' ? 'complessa' : 'semplice'}</span>` : ''}${run.mode === 'demo' ? '<span class="badge">demo</span>' : ''}</div>
    ${run.planSummary ? `<div class="plan-summary">${esc(run.planSummary)}</div>` : ''}
    <div class="progress"><div style="width:${(done / total) * 100}%"></div></div>
    <div class="meta"><span>${done}/${run.tasks.length} task</span><span>⏱ ${dur(run.createdAt, run.finishedAt)}</span><span>${run.usage?.calls ?? 0} chiamate</span>${run.usage?.escalations ? `<span>⬆️ ${run.usage.escalations}</span>` : ''}</div>
    ${ws.length ? `<div class="ws-mini">${ws.join('')}</div>` : ''}
    ${run.error ? `<div class="verdict revise" style="margin-top:8px">${esc(run.error)}</div>` : ''}
    ${controls}`;
}

function renderRuns() {
  const el = $('#runs');
  if (!S.runs.length) {
    el.innerHTML = '<div class="muted" style="padding:6px 2px">Ancora nessun run.</div>';
    return;
  }
  const current = shown()?.id;
  el.innerHTML = S.runs
    .slice(0, 30)
    .map((r) => `<div class="run-item${r.id === current ? ' active' : ''}" data-run="${r.id}"><div class="g">${esc(r.goal)}</div><div class="m">${STATUS_LABEL[r.status] ?? r.status} · ${r.done}/${r.tasks} task · ${ago(r.createdAt)}</div></div>`)
    .join('');
}

// ---------- board ----------

function progressOf(t) {
  if (t.status === 'done') return 100;
  return { queued: 0, assigned: 10, working: 45, revise: 55, review: 85 }[t.status] ?? 0;
}

function taskCard(t) {
  const open = S.openTasks.has(t.id);
  const agent = t.agentId ? S.agents.get(t.agentId) : null;
  let detail = '';
  if (open) {
    const hist = t.history.slice(-14).map((h) => {
      const what = h.kind === 'step' ? `${TOOL_LABEL[h.tool] ?? h.tool}${h.target ? ` <code>${esc(h.target.slice(0, 60))}</code>` : ''}<br><span class="muted">${esc(h.text)}</span>` : h.kind === 'verdict' ? `⚖️ ${esc(h.text)}` : h.kind === 'escalate' ? `⬆️ ${esc(h.text)}` : h.kind === 'check' ? `🧪 ${esc(h.text)}` : `⚠️ ${esc(h.text)}`;
      return `<div class="ev"><span class="t">${esc(agentName(h.agentId).slice(0, 2))}</span><div>${what}</div></div>`;
    });
    const verdicts = t.verdicts.map((v) => `<div class="verdict ${v.verdict}">${v.verdict === 'pass' ? '✔️' : '✖️'} <b>${esc(agentName(v.judgeId))}</b>, tentativo ${v.attempt}${v.score != null ? ` · ${v.score}/10` : ''}${v.security ? ' · sicurezza' : ''}${v.feedback ? `\n${esc(v.feedback)}` : ''}</div>`).join('');
    detail = `<div class="detail">
      ${esc(t.description)}
      ${t.brief ? `<div class="brief"><b>Prompt Lab</b>\n${esc(t.brief)}</div>` : ''}
      ${t.acceptance.length ? `<ul>${t.acceptance.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>` : ''}
      ${t.outputs.length ? `<div>File: ${t.outputs.map((o) => `<code>${esc(o)}</code>`).join(' ')}</div>` : ''}
      ${t.skills?.length ? `<div>Skill: ${t.skills.map((s) => `<code>${esc(s.name)}</code>`).join(' ')}</div>` : ''}
      ${t.dependsOn.length ? `<div>Dopo: ${t.dependsOn.map((d) => `<code>${d}</code>`).join(' ')}</div>` : ''}
      ${t.summary ? `<div style="margin-top:6px"><b>Consegna:</b> ${esc(t.summary)}</div>` : ''}
      ${t.error ? `<div class="verdict revise">${esc(t.error)}</div>` : ''}
      ${verdicts}
      ${hist.length ? `<div class="timeline">${hist.join('')}</div>` : ''}
    </div>`;
  }
  return `<div class="task" style="--team:${teamColor(t.team)}" data-task="${t.id}">
    <div class="top"><span class="ring${t.status === 'done' ? ' done' : ''}" style="--p:${progressOf(t)}"></span><span class="title">${esc(t.title)}</span><span class="id">${t.id}</span></div>
    <div class="sub"><span class="team-chip">${esc(teamLabel(t.team))}</span>${agent ? `<span>${esc(agent.name)}${agent.kind === 'sub' ? ' (sub)' : ''}</span>` : ''}<span>${TASK_STATUS[t.status]}</span>${t.revisions ? `<span class="badge rev">${t.revisions} rev.</span>` : ''}${t.escalated ? '<span class="badge esc">⬆️ frontier</span>' : ''}</div>
    ${detail}
  </div>`;
}

function renderBoard() {
  const run = shown();
  const el = $('#tab-board');
  if (!run || !run.workstreams?.length) {
    el.innerHTML = `<div class="empty">${run?.status === 'planning' ? '🧠 La CEO sta pianificando…' : 'Il lavoro dell\'azienda apparirà qui.'}</div>`;
    return;
  }
  const T = run.tasks;
  const waiting = run.waiting?.filter((w) => w.status === 'open').length ?? 0;
  const groups = { all: T, running: T.filter((t) => ['assigned', 'working', 'review', 'revise'].includes(t.status)), queued: T.filter((t) => t.status === 'queued'), done: T.filter((t) => t.status === 'done') };
  const filters = [['all', 'Tutti', T.length], ['running', 'In corso', groups.running.length], ['queued', 'In coda', groups.queued.length], ['done', 'Fatti', groups.done.length]];
  const list = new Set(groups[S.filter].map((t) => t.id));
  const body = run.workstreams
    .map((w) => {
      const ts = T.filter((t) => t.wsId === w.id && list.has(t.id));
      if (!ts.length && S.filter !== 'all') return '';
      return `<div class="ws-head" style="--team:${teamColor(w.team)}"><i></i>${w.id} · ${esc(w.title)}<span>${esc(teamLabel(w.team))} · ${WS_STATUS[w.status]}</span></div>${ts.map(taskCard).join('') || `<div class="muted" style="padding:2px 4px 6px">${w.status === 'preparing' ? 'Il lead sta scomponendo il lavoro…' : 'In attesa dei workstream da cui dipende.'}</div>`}`;
    })
    .join('');
  el.innerHTML = `<div class="filters">${filters.map(([k, label, n]) => `<button data-filter="${k}" class="${S.filter === k ? 'on' : ''}">${label} ${n}</button>`).join('')}${waiting ? `<button class="on" style="border-color:#ff6b9a">🙋 In attesa di te ${waiting}</button>` : ''}</div>${body || '<div class="empty">Niente in questa vista.</div>'}`;
}

// ---------- comms ----------

function renderComms() {
  const run = shown();
  const el = $('#tab-comms');
  if (!run || !run.messages.length) {
    el.innerHTML = '<div class="empty">Qui passano i messaggi tra CEO, lead, agenti, Skill Hub, Prompt Lab e QA.</div>';
    return;
  }
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.innerHTML = run.messages
    .slice(-180)
    .map((m) => `<div class="msg"><div class="av" style="--team:${agentColor(m.from)}">${esc(agentName(m.from).slice(0, 1))}</div><div>
      <div class="h"><b>${esc(agentName(m.from))}</b> → ${esc(agentName(m.to))} <span class="k ${m.kind}">${KIND_LABEL[m.kind] ?? m.kind}</span> <span>${new Date(m.ts).toLocaleTimeString('it-IT')}</span></div>
      <div class="body">${esc(m.text.length > 600 ? `${m.text.slice(0, 600)}…` : m.text)}</div></div></div>`)
    .join('');
  if (stick) el.scrollTop = el.scrollHeight;
}

// ---------- teams ----------

function teamStats(id) {
  const run = S.run;
  const tasks = run ? run.tasks.filter((t) => t.team === id) : [];
  const done = tasks.filter((t) => t.status === 'done' && t.startedAt && t.finishedAt);
  const avg = done.length ? done.reduce((n, t) => n + (new Date(t.finishedAt) - new Date(t.startedAt)), 0) / done.length / 1000 : 0;
  return { tasks: tasks.length, running: tasks.filter((t) => ['assigned', 'working', 'review', 'revise'].includes(t.status)).length, avg: avg ? (avg < 60 ? `${Math.round(avg)}s` : `${Math.round(avg / 60)}m`) : '–', skills: [...new Set(tasks.flatMap((t) => t.skills?.map((s) => s.name) ?? []))] };
}

function selectTeam(id, focus = false) {
  S.team = id;
  if (focus) world.focusRoom(id);
  switchTab('teams');
}

function renderTeams() {
  const el = $('#tab-teams');
  const teams = Object.entries(S.config.teams);
  if (S.team && teamOf(S.team)) {
    const t = teamOf(S.team);
    const st = teamStats(S.team);
    const members = [...S.agents.values()].filter((a) => a.team === S.team).sort((a, b) => ({ lead: 0, worker: 1, sub: 2 })[a.kind] - ({ lead: 0, worker: 1, sub: 2 })[b.kind]);
    const tools = ['list_files', 'read_file', 'write_file', ...(t.tools ?? []), 'search_skills', 'recall', 'remember', 'ask_lead', 'ask_user'];
    el.innerHTML = `
      <div class="row" style="margin-bottom:8px"><button class="btn" data-team="">← Tutti i team</button><button class="btn" data-focusroom="${S.team}">Vai alla stanza</button></div>
      <div class="team-card" style="--team:${t.color};cursor:default">
        <div class="hd"><span class="av" style="--team:${t.color}">${esc(t.label.slice(0, 1))}</span><b>${esc(t.label)}</b><span>${t.kind === 'service' ? 'servizio' : 'team operativo'} · combo ${esc(t.combo)}</span></div>
        <p class="muted" style="margin:8px 0 0;line-height:1.45">${esc(t.brief)}</p>
        <div class="kpis"><div class="kpi"><small>Task del run</small><b>${st.tasks}</b></div><div class="kpi"><small>In corso</small><b>${st.running}</b></div><div class="kpi"><small>Tempo medio</small><b>${st.avg}</b></div></div>
        <div class="col-title"><span>Agenti</span><span>fino a ${t.maxSubAgents ?? 0} sub-agenti</span></div>
        <div class="people">${members.map((a) => `<div class="person" data-agent="${a.id}"><span class="av" style="--team:${t.color}">${esc(a.name.slice(0, 1))}</span><span><span class="nm">${esc(a.name)}</span> <span class="muted">${a.kind === 'lead' ? 'lead' : a.kind === 'sub' ? 'sub-agente' : esc(t.title)}</span></span><span class="st${a.state !== 'idle' ? ' on' : ''}">${AGENT_STATE[a.state] ?? a.state}</span></div>`).join('')}</div>
        <div class="col-title"><span>Strumenti</span></div>
        <div class="tools">${tools.filter((x) => x !== 'run_command' || S.config.limits.allowShell).map((x) => `<span class="tool">${esc(x)}</span>`).join('')}</div>
        ${st.skills.length ? `<div class="col-title"><span>Skill usate in questo run</span></div><div class="tools">${st.skills.map((x) => `<span class="tool">${esc(x)}</span>`).join('')}</div>` : ''}
        <div class="col-title"><span>Parla con il team</span></div>
        <div class="muted" style="font-size:12px;margin-bottom:6px">Scrivi al lead: durante un run il messaggio arriva a tutto il team.</div>
        ${t.lead ? `<button class="btn" data-agent="${t.lead.id}">Apri la chat con ${esc(t.lead.name)}</button>` : ''}
      </div>`;
    return;
  }
  el.innerHTML = teams
    .map(([id, t]) => {
      const st = teamStats(id);
      const members = [...S.agents.values()].filter((a) => a.team === id);
      const busy = members.filter((a) => a.state !== 'idle').length;
      return `<div class="team-card" style="--team:${t.color}" data-team="${id}">
        <div class="hd"><span class="av" style="--team:${t.color}">${esc(t.label.slice(0, 1))}</span><b>${esc(t.label)}</b><span>${members.length} agenti · ${busy} al lavoro</span></div>
        <div class="muted" style="font-size:12px;margin-top:6px">${esc(t.brief)}</div>
        ${st.tasks ? `<div class="muted" style="font-size:12px;margin-top:6px">${st.tasks} task · ${st.running} in corso</div>` : ''}
      </div>`;
    })
    .join('');
}

// ---------- skills ----------

async function loadSkills(q = S.skills.query) {
  S.skills = { ...(await api(`/api/skills${q ? `?q=${encodeURIComponent(q)}` : ''}`)), query: q };
  invalidate('skills');
}

function renderSkills() {
  const el = $('#tab-skills');
  const s = S.skills;
  const focused = document.activeElement?.id === 'skill-q';
  el.innerHTML = `
    <div class="muted" style="font-size:12.5px;line-height:1.45;margin-bottom:8px">Lo <b>Skill Hub</b> indicizza ogni <code>SKILL.md</code> delle cartelle qui sotto. Per ogni task il bibliotecario sceglie le skill più utili; gli agenti possono cercarne altre.</div>
    <div class="searchbar"><input type="search" id="skill-q" placeholder="Cerca tra ${s.count} skill…" value="${esc(s.query)}"><button class="btn" data-act="skills-search">Cerca</button></div>
    <div class="col-title"><span>Fonti</span><button class="btn" data-act="skills-reindex">Reindicizza</button></div>
    ${s.sources.map((x) => `<div class="source"><b title="${esc(x.dir)}">${esc(x.label)}</b><span>${x.exists ? `${x.count} skill` : 'non trovata'}</span></div>`).join('')}
    <div class="col-title"><span>Aggiungi una repo GitHub di skill</span></div>
    <div class="searchbar"><input type="url" id="skill-repo" placeholder="https://github.com/utente/repo"><button class="btn" data-act="skills-repo">Aggiungi</button></div>
    <div class="col-title"><span>${s.query ? `Risultati per “${esc(s.query)}”` : 'Libreria'}</span><span>${s.results.length}</span></div>
    ${s.results.map((k) => `<div class="skill" data-skill="${k.id}"><b>${esc(k.name)}</b> <small>· ${esc(k.source)}${k.score ? ` · ${k.score}` : ''}</small><p>${esc(k.description.slice(0, 220))}</p></div>`).join('') || '<div class="empty">Nessuna skill trovata.</div>'}`;
  if (focused) {
    const i = $('#skill-q');
    i.focus();
    i.setSelectionRange(i.value.length, i.value.length);
  }
}

async function openSkill(id) {
  try {
    const s = await api(`/api/skills/read?id=${encodeURIComponent(id)}`);
    $('#viewer-body').innerHTML = `<div class="head"><h2 style="font-family:var(--mono);font-size:14px">${esc(s.name)}</h2><span class="muted">${esc(s.source)}</span><button class="icon-btn x" data-act="close-modal">✕</button></div><div class="hint" style="margin-bottom:8px">${esc(s.path)}</div><div class="md">${markdown(s.content.replace(/^---[\s\S]*?---/, ''))}</div>`;
    $('#viewer').classList.remove('hidden');
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- brain ----------

async function loadBrain(q = S.brain.query) {
  const r = await api(`/api/brain${q ? `?q=${encodeURIComponent(q)}` : ''}`);
  S.brain = { count: r.count, notes: r.notes, query: q };
  invalidate('brain', 'top');
}

function renderBrain() {
  const el = $('#tab-brain');
  const b = S.brain;
  const focused = document.activeElement?.id === 'brain-q';
  const kindLabel = { lesson: 'lezione QA', run: 'missione', note: 'nota agente', user: 'tua nota' };
  el.innerHTML = `
    <div class="muted" style="font-size:12.5px;line-height:1.45;margin-bottom:8px"><b>The Brain</b> è la memoria condivisa: lezioni del QA, note degli agenti e riassunti delle missioni. Ogni nuovo task riceve le note più pertinenti.</div>
    <div class="searchbar"><input type="search" id="brain-q" placeholder="Cerca tra ${b.count} note…" value="${esc(b.query)}"><button class="btn" data-act="brain-search">Cerca</button></div>
    <details style="margin-bottom:10px"><summary class="muted" style="cursor:pointer">+ Aggiungi una nota per la squadra</summary>
      <input type="text" id="note-title" placeholder="Titolo" style="margin:6px 0">
      <textarea id="note-text" placeholder="Es. Il nostro brand usa sempre il tu, mai il lei."></textarea>
      <button class="btn go" data-act="brain-add" style="margin-top:6px">Salva nel Brain</button>
    </details>
    ${b.notes.map((n) => `<div class="note"><div class="t">${esc(n.title)}</div><div class="x">${esc(n.text.slice(0, 500))}</div><div class="m"><span>${kindLabel[n.kind] ?? n.kind}</span>${n.agentId ? `<span>${esc(agentName(n.agentId))}</span>` : ''}${n.team ? `<span>${esc(teamLabel(n.team))}</span>` : ''}<span>${new Date(n.ts).toLocaleString('it-IT')}</span></div></div>`).join('') || '<div class="empty">Il Brain è ancora vuoto: si riempie lavorando.</div>'}`;
  if (focused) $('#brain-q').focus();
}

// ---------- router ----------

function renderRouter() {
  const r = S.router;
  const el = $('#tab-router');
  if (!r) return;
  const providers = r.providers.filter((p) => p.kind !== 'mock').map((p) => `<div class="prov"><span class="dot ${p.ready ? 'on' : ''}"></span><b>${esc(p.id)}</b><span class="muted">${p.ready ? 'pronto' : p.enabled ? `manca ${esc(p.keyEnv ?? 'chiave')}` : 'disattivato'}</span></div>`).join('');
  const combos = r.combos
    .map((c) => `<div class="combo"><div class="name"><span>${esc(c.name)} <span class="muted" style="font-weight:500">· ${esc(c.strategy)}${c.name === S.config.router.escalationCombo ? ' · escalation' : ''}</span></span><button class="btn" data-test="${esc(c.name)}">Prova</button></div>
      ${c.targets.map((t) => `<div class="t ${t.ready ? '' : 'off'}"><span class="dot ${t.coolingMs ? 'cool' : t.ready ? 'on' : ''}"></span>${esc(t.key)}<span class="s">${t.coolingMs ? `pausa ${Math.ceil(t.coolingMs / 1000)}s` : t.stats ? `${t.stats.ok}/${t.stats.calls} ok · ${Math.round(t.stats.totalMs / Math.max(1, t.stats.calls))} ms` : ''}</span></div>`).join('')}</div>`)
    .join('');
  const roles = [['ceo', S.config.ceo.combo], ...Object.entries(S.config.teams).map(([id, t]) => [id, t.combo])].map(([id, combo]) => `<span>${esc(teamLabel(id))}</span><b>${esc(combo)}</b>`).join('');
  const m = S.media;
  const calls = r.recent.slice(0, 40).map((c) => `<div class="call ${c.ok ? '' : 'err'}"><span class="tg">${esc(c.target)}</span><span class="r">${c.ms} ms</span><span class="r">${esc(teamLabel(c.role ?? ''))}${c.agentId ? ` · ${esc(agentName(c.agentId))}` : ''}${c.error ? ` · ${esc(c.error.slice(0, 80))}` : ''}</span><span class="r">${c.tokens.in + c.tokens.out} tok</span></div>`).join('');
  el.innerHTML = `
    <div class="muted" style="line-height:1.45;margin:0 4px 6px">${S.mode === 'live' ? 'Modelli veri: ogni team usa la sua combo, passa al modello successivo se uno fallisce e sale alla combo di escalation dopo troppe bocciature.' : 'Demo: nessuna chiave in <code>.env</code>, un simulatore interpreta i ruoli. Aggiungi una chiave e riavvia per andare live.'}</div>
    <div class="col-title"><span>Provider di testo</span></div>${providers}
    <div class="col-title"><span>Media generativi</span></div>
    ${m ? `<div class="kv" style="margin:0 4px"><span>Immagini</span><b>${esc(m.image.join(' → '))}</b><span>Voce</span><b>${esc(m.speech.join(' → '))}</b></div>${m.providers.map((p) => `<div class="prov"><span class="dot ${p.ready ? 'on' : ''}"></span><b>${esc(p.id)}</b><span class="muted">${p.ready ? 'pronto' : p.enabled ? `manca ${esc(p.keyEnv ?? '')}` : 'disattivato'}</span></div>`).join('')}` : ''}
    <div class="col-title"><span>Team → combo</span></div><div class="kv" style="margin:0 4px">${roles}</div>
    <div class="col-title"><span>Combo</span></div>${combos}
    <div class="col-title"><span>Ultime chiamate</span></div>${calls || '<div class="muted" style="padding:6px">Nessuna chiamata ancora.</div>'}
    <div class="muted" style="margin:10px 4px">Gateway compatibile OpenAI: <code>POST ${location.origin}/v1/chat/completions</code> con <code>"model": "combo:smart"</code>.</div>`;
}

// ---------- output ----------

async function loadFiles(run) {
  try {
    S.files = { runId: run.id, list: await api(`/api/runs/${run.id}/files`) };
  } catch {
    S.files = { runId: run.id, list: [] };
  }
  invalidate('output');
}

function renderOutput() {
  const run = shown();
  const el = $('#tab-output');
  if (!run) {
    el.innerHTML = '<div class="empty">File, immagini, audio e report finale appariranno qui.</div>';
    return;
  }
  if (!S.files || S.files.runId !== run.id) {
    el.innerHTML = '<div class="empty">Carico i file…</div>';
    loadFiles(run);
    return;
  }
  const files = S.files.list;
  const images = files.filter((f) => IMG_EXT.test(f.path));
  const audio = files.filter((f) => AUDIO_EXT.test(f.path));
  const hasIndex = files.some((f) => f.path === 'index.html');
  const src = (p) => `/preview/${run.id}/${p.split('/').map(encodeURIComponent).join('/')}`;
  el.innerHTML = `
    ${hasIndex ? `<a class="btn preview-btn" href="/preview/${run.id}/index.html" target="_blank" rel="noopener">▶ Apri l'anteprima del sito</a>` : ''}
    ${images.length ? `<div class="col-title"><span>Immagini generate</span><span>${images.length}</span></div><div class="gallery">${images.map((f) => `<img src="${src(f.path)}?v=${f.size}" alt="${esc(f.path)}" data-file="${esc(f.path)}">`).join('')}</div>` : ''}
    ${audio.length ? `<div class="col-title"><span>Audio</span></div>${audio.map((f) => `<div style="margin-bottom:6px"><code>${esc(f.path)}</code><audio controls src="${src(f.path)}" style="width:100%;margin-top:4px"></audio></div>`).join('')}` : ''}
    <div class="col-title"><span>File del progetto</span><span>${files.length}</span></div>
    <div class="files">${files.map((f) => `<div class="file" data-file="${esc(f.path)}">${esc(f.path)}<span>${f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`}</span></div>`).join('') || '<div class="muted" style="padding:6px">Nessun file ancora.</div>'}</div>
    <div class="col-title"><span>Report finale</span></div>
    ${run.report ? `<div class="md">${markdown(run.report)}</div>` : `<div class="muted" style="padding:6px">${isLive(run) ? 'Arriva alla fine del run.' : 'Nessun report.'}</div>`}
    <div class="muted" style="font-size:11.5px;margin-top:12px;word-break:break-all">Cartella: ${esc(run.workspace)}</div>`;
}

async function openFile(path) {
  const run = shown();
  const src = `/preview/${run.id}/${path.split('/').map(encodeURIComponent).join('/')}`;
  const head = `<div class="head"><h2 style="font-family:var(--mono);font-size:14px">${esc(path)}</h2>${/\.html?$/.test(path) || IMG_EXT.test(path) ? `<a class="btn" href="${src}" target="_blank" rel="noopener">Apri</a>` : ''}<button class="icon-btn x" data-act="close-modal">✕</button></div>`;
  if (IMG_EXT.test(path) && !path.endsWith('.svg')) {
    $('#viewer-body').innerHTML = `${head}<img class="full" src="${src}" alt="">`;
    $('#viewer').classList.remove('hidden');
    return;
  }
  if (AUDIO_EXT.test(path)) {
    $('#viewer-body').innerHTML = `${head}<audio controls autoplay src="${src}" style="width:100%"></audio>`;
    $('#viewer').classList.remove('hidden');
    return;
  }
  if (!TEXT_EXT.test(path)) return window.open(src, '_blank', 'noopener');
  try {
    const f = await api(`/api/runs/${run.id}/file?path=${encodeURIComponent(path)}`);
    $('#viewer-body').innerHTML = `${head}${path.endsWith('.md') ? `<div class="md">${markdown(f.content)}</div>` : `<pre class="view">${esc(f.content)}</pre>`}`;
    $('#viewer').classList.remove('hidden');
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- roster & inspector ----------

function renderRoster() {
  if (!S.config) return;
  const order = (a) => (a.kind === 'ceo' ? 0 : 1);
  const teams = Object.keys(S.config.teams);
  const list = [...S.agents.values()].sort((a, b) => order(a) - order(b) || teams.indexOf(a.team) - teams.indexOf(b.team) || ({ lead: 0, worker: 1, sub: 2 })[a.kind] - ({ lead: 0, worker: 1, sub: 2 })[b.kind]);
  $('#roster').innerHTML = list
    .map((a) => `<button class="member${a.state !== 'idle' ? ' busy' : ''}${a.kind === 'lead' || a.kind === 'ceo' ? ' lead' : ''}${a.kind === 'sub' ? ' sub' : ''}${S.selected === a.id ? ' sel' : ''}" data-agent="${a.id}" title="${esc(AGENT_STATE[a.state] ?? '')}"><span class="av" style="--team:${agentColor(a.id)}">${esc(a.name.slice(0, 1))}</span><span class="nm">${esc(a.name)}<small>${esc(a.kind === 'ceo' ? 'CEO' : teamLabel(a.team))}</small></span></button>`)
    .join('');
}

async function selectAgent(id) {
  S.selected = S.selected === id ? null : id;
  if (S.selected) {
    world.focus(id);
    if (!S.chats.has(id)) S.chats.set(id, await api(`/api/chat/${id}`).catch(() => []));
  }
  invalidate('inspector', 'roster');
}

function renderInspector() {
  const el = $('#inspector');
  const a = S.selected && S.agents.get(S.selected);
  if (!a) {
    el.classList.add('hidden');
    return;
  }
  el.classList.remove('hidden');
  const t = a.kind === 'ceo' ? null : teamOf(a.team);
  const role = a.kind === 'ceo' ? S.config.ceo.title : a.kind === 'lead' ? `Lead · ${t?.label}` : a.kind === 'sub' ? `Sub-agente · ${t?.label}` : `${t?.title} · ${t?.label}`;
  const run = S.run;
  const task = a.taskId && run ? run.tasks.find((x) => x.id === a.taskId) : null;
  const events = run ? run.tasks.flatMap((x) => x.history.filter((h) => h.agentId === a.id).map((h) => ({ ...h, task: x.id }))).sort((x, y) => y.ts - x.ts).slice(0, 6) : [];
  const chat = S.chats.get(a.id) ?? [];
  const draft = $('#chat-input')?.dataset.agent === a.id ? $('#chat-input').value : '';
  el.innerHTML = `
    <div class="hd"><div class="av" style="--team:${agentColor(a.id)}">${esc(a.name.slice(0, 1))}</div><div><div class="nm">${esc(a.name)}</div><div class="rl">${esc(role)}</div></div><button class="icon-btn x" data-act="close-inspector">✕</button></div>
    <div class="now"><b>${esc(AGENT_STATE[a.state] ?? a.state)}</b>${a.tool ? ` · ${TOOL_LABEL[a.tool] ?? a.tool}` : ''}
      ${task ? `<div>Task <b>${task.id}</b>: ${esc(task.title)}</div>` : ''}
      ${a.text ? `<div class="muted" style="margin-top:4px">${esc(a.text)}</div>` : ''}
      ${a.model ? `<div class="muted" style="margin-top:4px;font-family:var(--mono);font-size:11px">${esc(a.model)}</div>` : ''}</div>
    ${events.length ? `<div class="timeline">${events.map((h) => `<div class="ev"><span class="t">${h.task.split('.').pop()}</span><div>${h.kind === 'step' ? `${TOOL_LABEL[h.tool] ?? h.tool} ${h.target ? `<code>${esc(h.target.slice(0, 36))}</code>` : ''}` : esc(h.text)}</div></div>`).join('')}</div>` : ''}
    <div class="col-title"><span>Chat${run && isLive(run) ? ' · i tuoi messaggi guidano il lavoro' : ''}</span><button class="btn" data-act="speak" title="Leggi ad alta voce le risposte">${S.speak ? '🔊' : '🔈'}</button></div>
    <div class="chat" id="chat-log">${chat.map((m) => `<div class="b ${m.from === 'user' ? 'me' : 'them'}">${esc(m.text)}</div>`).join('') || '<div class="muted" style="font-size:12px">Scrivi o parla con l\'agente.</div>'}</div>
    <div class="chatbox"><input type="text" id="chat-input" data-agent="${a.id}" placeholder="Scrivi a ${esc(a.name)}…" value="${esc(draft)}"><button class="mic" id="chat-mic" title="Parla">🎙</button><button class="btn go" data-act="chat-send">Invia</button></div>`;
  const log = $('#chat-log');
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const input = $('#chat-input');
  const id = input?.dataset.agent;
  const text = input?.value.trim();
  if (!id || !text) return;
  const list = S.chats.get(id) ?? [];
  list.push({ from: 'user', text });
  list.push({ from: id, text: '…' });
  S.chats.set(id, list);
  input.value = '';
  invalidate('inspector');
  try {
    const r = await api(`/api/chat/${id}`, { method: 'POST', body: JSON.stringify({ text }) });
    list[list.length - 1] = { from: id, text: r.reply };
    say(r.reply);
    if (r.steered) toast(`Messaggio inoltrato al lavoro in corso (${agentName(id)})`);
  } catch (err) {
    list[list.length - 1] = { from: id, text: `(${err.message})` };
  }
  invalidate('inspector');
}

// ---------- settings ----------

function openSettings() {
  const c = S.config;
  const combos = Object.keys(c.combos);
  const sel = (key, value) => `<select data-combo="${key}">${combos.map((n) => `<option ${n === value ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
  const teamRows = [`<tr><td><b>CEO</b></td><td>${esc(c.ceo.name)}</td><td>${sel('ceo', c.ceo.combo)}</td><td></td></tr>`, ...Object.entries(c.teams).map(([id, t]) => `<tr><td><span class="team-chip" style="--team:${t.color}">${esc(t.label)}</span></td><td>${esc(t.lead?.name ?? '')}${t.workers?.length ? ` + ${t.workers.map((w) => esc(w.name)).join(', ')}` : ''}</td><td>${sel(id, t.combo)}</td><td><input type="number" min="0" max="3" data-subs="${id}" value="${t.maxSubAgents ?? 0}" title="Sub-agenti massimi"></td></tr>`)].join('');
  const provRows = S.router.providers.filter((p) => p.kind !== 'mock').map((p) => `<tr><td><span class="dot ${p.ready ? 'on' : ''}"></span> <b>${esc(p.id)}</b></td><td>${esc(p.kind)}</td><td><code>${esc(p.keyEnv ?? 'nessuna chiave')}</code></td><td><label><input type="checkbox" data-prov="${p.id}" ${p.enabled ? 'checked' : ''}> attivo</label></td></tr>`).join('');
  const mediaRows = (S.media?.providers ?? []).map((p) => `<tr><td><span class="dot ${p.ready ? 'on' : ''}"></span> <b>${esc(p.id)}</b></td><td><code>${esc(p.keyEnv ?? 'senza chiave')}</code></td><td><label><input type="checkbox" data-mprov="${p.id}" ${p.enabled ? 'checked' : ''}> attivo</label></td></tr>`).join('');
  const L = c.limits;
  const P = c.pacing;
  $('#settings-body').innerHTML = `
    <div class="head"><h2>Impostazioni</h2><button class="icon-btn x" data-act="close-modal">✕</button></div>
    <div class="hint">Le chiavi API stanno solo nel file <code>.env</code> della cartella dell'app, mai qui. Le modifiche finiscono in <code>config/local.json</code>.</div>
    <h3>Team → combo e sub-agenti</h3>
    <table><tr><th>Team</th><th>Persone</th><th>Combo</th><th>Sub max</th></tr>${teamRows}</table>
    <h3>Come lavora l'azienda</h3>
    <div class="row" style="flex-wrap:wrap;gap:14px">
      <label>Task in parallelo <input type="number" min="1" max="20" data-limit="maxParallel" value="${L.maxParallel}"></label>
      <label>Passi per tentativo <input type="number" min="3" max="60" data-limit="maxSteps" value="${L.maxSteps}"></label>
      <label>Revisioni max <input type="number" min="0" max="10" data-limit="maxRevisions" value="${L.maxRevisions}"></label>
      <label>Escalation dopo <input type="number" min="1" max="10" data-limit="escalateAfter" value="${L.escalateAfter}"></label>
      <label>Workstream max <input type="number" min="1" max="12" data-limit="maxWorkstreams" value="${L.maxWorkstreams}"></label>
      <label>Sotto-task max <input type="number" min="1" max="10" data-limit="maxSubtasks" value="${L.maxSubtasks}"></label>
    </div>
    <div class="row" style="margin-top:8px;gap:14px;flex-wrap:wrap">
      <label>Combo di escalation ${sel('__escalation', c.router.escalationCombo)}</label>
      <label class="check" style="margin:0"><input type="checkbox" data-bool="approvePlan" ${L.approvePlan ? 'checked' : ''}> Chiedi sempre l'approvazione del piano</label>
    </div>
    <div class="hint" style="margin-top:6px">Comandi shell per gli agenti: <b>${L.allowShell ? 'attivi' : 'disattivati'}</b> (si cambia con <code>AGENT_WORLD_ALLOW_SHELL=1</code> nel file <code>.env</code>).</div>
    <h3>Ritmo dell'animazione (ms)</h3>
    <div class="row" style="flex-wrap:wrap;gap:14px">${Object.entries(P).map(([k, v]) => `<label>${esc(k)} <input type="number" min="0" step="100" data-pace="${k}" value="${v}"></label>`).join('')}</div>
    <h3>Provider di testo</h3><table>${provRows}</table>
    <h3>Provider media (immagini e voce)</h3><table>${mediaRows}</table>
    <div class="hint">Pollinations genera immagini gratis senza chiave ma invia i prompt a un servizio esterno: è spento finché non lo attivi.</div>
    <h3>Combo</h3>
    <div class="hint">Liste ordinate di <code>provider/modello</code>: il router prova il primo con la chiave e passa al successivo se fallisce. <code>strategy</code>: <code>fallback</code> o <code>round-robin</code>.</div>
    <textarea class="code" id="combos-json" spellcheck="false">${esc(JSON.stringify(c.combos, null, 2))}</textarea>
    <div class="foot"><button class="btn" data-act="close-modal">Annulla</button><button class="btn go" data-act="save-settings">Salva</button></div>`;
  $('#settings').classList.remove('hidden');
}

async function saveSettings() {
  const body = { ceo: {}, teams: {}, limits: {}, pacing: {}, providers: {}, router: {}, media: { providers: {} } };
  document.querySelectorAll('#settings [data-combo]').forEach((s) => {
    if (s.dataset.combo === 'ceo') body.ceo.combo = s.value;
    else if (s.dataset.combo === '__escalation') body.router.escalationCombo = s.value;
    else (body.teams[s.dataset.combo] ??= {}).combo = s.value;
  });
  document.querySelectorAll('#settings [data-subs]').forEach((i) => ((body.teams[i.dataset.subs] ??= {}).maxSubAgents = Number(i.value)));
  document.querySelectorAll('#settings [data-limit]').forEach((i) => (body.limits[i.dataset.limit] = Number(i.value)));
  document.querySelectorAll('#settings [data-bool]').forEach((i) => (body.limits[i.dataset.bool] = i.checked));
  document.querySelectorAll('#settings [data-pace]').forEach((i) => (body.pacing[i.dataset.pace] = Number(i.value)));
  document.querySelectorAll('#settings [data-prov]').forEach((i) => (body.providers[i.dataset.prov] = { enabled: i.checked }));
  document.querySelectorAll('#settings [data-mprov]').forEach((i) => (body.media.providers[i.dataset.mprov] = { enabled: i.checked }));
  try {
    body.combos = JSON.parse($('#combos-json').value);
  } catch {
    toast('Il JSON delle combo non è valido', true);
    return;
  }
  try {
    S.config = await api('/api/config', { method: 'POST', body: JSON.stringify(body) });
    S.router = await api('/api/router');
    S.media = await api('/api/media');
    S.mode = S.router.mode;
    $('#approve-plan').checked = S.config.limits.approvePlan;
    $('#settings').classList.add('hidden');
    toast('Impostazioni salvate');
    invalidate(...ALL);
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- actions ----------

async function startRun() {
  const goal = $('#goal').value.trim();
  if (goal.length < 4) return toast('Scrivi un obiettivo per l\'azienda', true);
  try {
    $('#btn-start').disabled = true;
    await api('/api/runs', { method: 'POST', body: JSON.stringify({ goal, approvePlan: $('#approve-plan').checked }) });
    S.view = null;
    S.openTasks.clear();
    S.filter = 'all';
    $('#goal').value = '';
  } catch (err) {
    toast(err.message, true);
    $('#btn-start').disabled = false;
  }
}

async function runAction(act) {
  try {
    await api(`/api/runs/${S.run.id}/${act}`, { method: 'POST' });
  } catch (err) {
    toast(err.message, true);
  }
}

async function answerWaiting(id, decision) {
  const text = document.querySelector(`textarea[data-wait="${id}"]`)?.value ?? '';
  try {
    await api(`/api/runs/${S.run.id}/answer`, { method: 'POST', body: JSON.stringify({ itemId: id, text, decision }) });
    toast(decision === 'approve' ? 'Piano approvato: si parte!' : decision === 'reject' ? 'Piano rifiutato' : 'Risposta inviata');
  } catch (err) {
    toast(err.message, true);
  }
}

function switchTab(tab) {
  S.tab = tab;
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-body').forEach((b) => b.classList.toggle('hidden', b.id !== `tab-${tab}`));
  if (narrow.matches) {
    $('#right').classList.add('open');
    $('#left').classList.remove('open');
  } else $('#right').classList.remove('closed');
  if (tab === 'router') api('/api/router').then((r) => ((S.router = r), invalidate('router')));
  if (tab === 'skills' && !S.skills.results.length) loadSkills('');
  if (tab === 'brain') loadBrain();
  invalidate(tab);
}

document.addEventListener('click', async (e) => {
  const t = e.target.closest('[data-act],[data-task],[data-run],[data-agent],[data-file],[data-test],[data-tab],[data-filter],[data-team],[data-focusroom],[data-skill],[data-answer],.chip');
  if (!t) {
    if (e.target.classList.contains('modal')) e.target.classList.add('hidden');
    return;
  }
  if (t.dataset.tab) return switchTab(t.dataset.tab);
  if (t.classList.contains('chip')) {
    $('#goal').value = t.textContent;
    return $('#goal').focus();
  }
  if (t.dataset.answer) return answerWaiting(t.dataset.answer, t.dataset.decision ?? null);
  if (t.dataset.filter) {
    S.filter = t.dataset.filter;
    return invalidate('board');
  }
  if (t.dataset.team !== undefined) {
    S.team = t.dataset.team || null;
    if (S.team) world.focusRoom(S.team);
    return invalidate('teams');
  }
  if (t.dataset.focusroom) return world.focusRoom(t.dataset.focusroom);
  if (t.dataset.skill) return openSkill(t.dataset.skill);
  if (t.dataset.task) {
    if (e.target.closest('.detail')) return;
    S.openTasks.has(t.dataset.task) ? S.openTasks.delete(t.dataset.task) : S.openTasks.add(t.dataset.task);
    return invalidate('board');
  }
  if (t.dataset.run) {
    S.view = t.dataset.run === S.run?.id ? null : await api(`/api/runs/${t.dataset.run}`).catch(() => null);
    S.openTasks.clear();
    return invalidate(...ALL);
  }
  if (t.dataset.agent) return selectAgent(t.dataset.agent);
  if (t.dataset.file) return openFile(t.dataset.file);
  if (t.dataset.test) {
    t.textContent = '…';
    const r = await api('/api/router/test', { method: 'POST', body: JSON.stringify({ use: t.dataset.test }) }).catch((err) => ({ ok: false, error: err.message }));
    toast(r.ok ? `${t.dataset.test}: risponde ${r.target} in ${r.ms} ms${r.demo ? ' (demo)' : ''}` : `${t.dataset.test}: ${r.error}`, !r.ok);
    t.textContent = 'Prova';
    return;
  }
  const act = t.dataset.act;
  e.preventDefault();
  if (['pause', 'resume', 'stop'].includes(act)) return runAction(act);
  if (act === 'back') {
    S.view = null;
    invalidate(...ALL);
  }
  if (act === 'close-inspector') selectAgent(S.selected);
  if (act === 'close-modal') t.closest('.modal').classList.add('hidden');
  if (act === 'save-settings') saveSettings();
  if (act === 'chat-send') sendChat();
  if (act === 'speak') {
    S.speak = !S.speak;
    savePref('speak', S.speak);
    invalidate('inspector');
  }
  if (act === 'skills-search') loadSkills($('#skill-q').value.trim());
  if (act === 'skills-reindex') {
    toast('Reindicizzo le skill…');
    await api('/api/skills/reindex', { method: 'POST' }).catch((err) => toast(err.message, true));
    loadSkills();
  }
  if (act === 'skills-repo') {
    const url = $('#skill-repo').value.trim();
    toast('Clono la repo…');
    try {
      const r = await api('/api/skills/repo', { method: 'POST', body: JSON.stringify({ url }) });
      toast(`${r.repo}: +${r.added} skill (totale ${r.total})`);
      loadSkills();
    } catch (err) {
      toast(err.message, true);
    }
  }
  if (act === 'brain-search') loadBrain($('#brain-q').value.trim());
  if (act === 'brain-add') {
    try {
      await api('/api/brain', { method: 'POST', body: JSON.stringify({ title: $('#note-title').value, text: $('#note-text').value }) });
      toast('Nota salvata nel Brain');
      loadBrain('');
    } catch (err) {
      toast(err.message, true);
    }
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') document.querySelectorAll('.modal').forEach((m) => m.classList.add('hidden'));
  if (e.key === 'Enter' && e.target.id === 'chat-input') sendChat();
  if (e.key === 'Enter' && e.target.id === 'skill-q') loadSkills(e.target.value.trim());
  if (e.key === 'Enter' && e.target.id === 'brain-q') loadBrain(e.target.value.trim());
});
document.addEventListener('click', (e) => {
  if (e.target.id === 'chat-mic') listen(e.target, (text, final) => {
    const input = $('#chat-input');
    input.value = text;
    if (final) sendChat();
  });
});

$('#btn-start').addEventListener('click', startRun);
$('#goal').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) startRun();
});
$('#goal-mic').addEventListener('click', (e) => listen(e.currentTarget, (text) => ($('#goal').value = text)));
$('#btn-settings').addEventListener('click', openSettings);
$('#btn-home').addEventListener('click', () => world.resetView({ animate: true }));
$('#btn-theme').addEventListener('click', () => setTheme(!document.body.classList.contains('night')));

function setTheme(night) {
  document.body.classList.toggle('night', night);
  $('#btn-theme').textContent = night ? '☾' : '☀';
  world.setTheme(night);
  savePref('theme-night', night);
}

const narrow = matchMedia('(max-width: 900px)');
function togglePanel(id, other) {
  if (narrow.matches) {
    $(id).classList.toggle('open');
    $(other).classList.remove('open');
  } else {
    $(id).classList.toggle('closed');
    document.body.classList.toggle('left-closed', $('#left').classList.contains('closed'));
    document.body.classList.toggle('right-closed', $('#right').classList.contains('closed'));
  }
}
$('#btn-left').addEventListener('click', () => togglePanel('#left', '#right'));
$('#btn-right').addEventListener('click', () => togglePanel('#right', '#left'));

// How far the UI reaches into the 3D canvas from each edge, so the camera frames the
// office in the free area. On narrow screens the panels are full-screen overlays and
// do not count. The observer also fires when a panel is hidden (its size drops to 0).
function measureInsets() {
  const c = $('#scene').getBoundingClientRect();
  const box = (el, counts = true) => {
    const r = el.getBoundingClientRect();
    return counts && r.width > 0 && r.height > 0 ? r : null;
  };
  const top = box($('.topbar'));
  const left = box($('#left'), !narrow.matches);
  const right = box($('#right'), !narrow.matches);
  const roster = box($('#roster'));
  return {
    top: top ? top.bottom - c.top : 0,
    right: right ? c.right - right.left : 0,
    bottom: roster ? c.bottom - roster.top : 0,
    left: left ? left.right - c.left : 0,
  };
}
const insetsObserver = new ResizeObserver(() => world.setInsets(measureInsets()));
for (const el of [$('.topbar'), $('#left'), $('#right'), $('#roster')]) insetsObserver.observe(el);
$('#examples').innerHTML = EXAMPLES.map((x) => `<button class="chip">${esc(x)}</button>`).join('');

// ---------- live data ----------

function upsertTask(task) {
  if (!S.run) return;
  const i = S.run.tasks.findIndex((t) => t.id === task.id);
  if (i >= 0) S.run.tasks[i] = task;
  else S.run.tasks.push(task);
}

async function refreshRuns() {
  S.runs = await api('/api/runs').catch(() => S.runs);
  invalidate('runs');
}

function handle({ type, payload }) {
  switch (type) {
    case 'run': {
      const isNew = payload.id !== S.run?.id;
      S.run = payload;
      world.onRun(payload);
      if (isNew) {
        S.files = null;
        refreshRuns();
      }
      invalidate('top', 'current', 'waiting', 'board', 'comms', 'output', 'inspector', 'teams');
      break;
    }
    case 'task':
      if (S.run?.id === payload.runId) upsertTask(payload.task);
      world.onTask(payload);
      invalidate('board', 'current', 'inspector');
      break;
    case 'workstream':
      world.onWorkstream(payload);
      break;
    case 'subtasks':
      world.onSubtasks(payload);
      break;
    case 'agent':
      S.agents.set(payload.id, payload);
      world.applyState(payload);
      invalidate('roster', 'inspector', 'top', 'rooms', 'teams');
      break;
    case 'agent.spawn':
      S.agents.set(payload.id, payload);
      world.onSpawn(payload);
      invalidate('roster', 'rooms', 'teams', 'top');
      break;
    case 'agent.despawn':
      S.agents.delete(payload.id);
      world.onDespawn(payload);
      if (S.selected === payload.id) S.selected = null;
      invalidate('roster', 'rooms', 'teams', 'inspector', 'top');
      break;
    case 'message':
      world.onMessage(payload);
      if (payload.kind === 'ask_user') toast(`🙋 ${agentName(payload.from)} ti fa una domanda`);
      break;
    case 'plan':
      world.onPlan(payload);
      break;
    case 'file':
      world.onFile(payload);
      if (S.files?.runId === payload.runId) {
        S.files = null;
        invalidate('output');
      }
      break;
    case 'waiting':
      invalidate('waiting', 'board');
      break;
    case 'brain':
      S.brain.count = payload.count;
      world.onBrain(payload);
      invalidate('top');
      if (S.tab === 'brain' && payload.op === 'remember') loadBrain();
      break;
    case 'skills':
      S.skills.count = payload.count;
      if (S.tab === 'skills') loadSkills();
      break;
    case 'run.done':
      world.onRunDone(payload);
      S.files = null;
      refreshRuns();
      toast(payload.status === 'completed' ? '🎉 Missione completata!' : `Run terminato: ${STATUS_LABEL[payload.status] ?? payload.status}`, payload.status !== 'completed');
      invalidate(...ALL);
      break;
    case 'router.call':
      if (S.router) {
        S.router.recent.unshift(payload);
        S.router.recent.length = Math.min(S.router.recent.length, 60);
      }
      invalidate('router');
      break;
    case 'config':
      S.config = payload;
      world.build(S.config, [...S.agents.values()]);
      invalidate(...ALL);
      break;
  }
}

async function boot() {
  S.speak = loadPref('speak', false);
  const night = loadPref('theme-night', false);
  document.body.classList.toggle('night', night);
  $('#btn-theme').textContent = night ? '☾' : '☀';
  world.setTheme(night);

  const st = await api('/api/state');
  S.config = st.config;
  S.mode = st.mode;
  S.router = st.router;
  S.media = st.media;
  S.runs = st.runs;
  S.run = st.run;
  S.skills = { ...S.skills, ...st.skills };
  S.brain = { count: st.brain.count, notes: st.brain.recent, query: '' };
  $('#approve-plan').checked = S.config.limits.approvePlan;
  st.agents.forEach((a) => S.agents.set(a.id, a));
  world.build(S.config, st.agents);
  world.setBrainCount(st.brain.count);
  world.syncRun(S.run && isLive(S.run) ? S.run : null);
  if (S.run && !isLive(S.run)) world.onRun(S.run);
  invalidate(...ALL);

  const es = new EventSource('/api/events');
  es.onmessage = (e) => handle(JSON.parse(e.data));
  let wasDown = false;
  es.onerror = () => (wasDown = true);
  es.onopen = async () => {
    if (!wasDown) return;
    wasDown = false;
    const fresh = await api('/api/state').catch(() => null);
    if (!fresh) return;
    S.run = fresh.run;
    S.runs = fresh.runs;
    S.agents.clear();
    fresh.agents.forEach((a) => S.agents.set(a.id, a));
    for (const a of fresh.agents) world.applyState(a, true);
    world.syncRun(S.run);
    invalidate(...ALL);
  };

  setInterval(async () => {
    if (S.tab === 'router') {
      S.router = await api('/api/router').catch(() => S.router);
      invalidate('router');
    }
    if (isLive(S.run)) invalidate('current');
  }, 3000);
}

boot().catch((err) => toast(`Impossibile caricare lo stato: ${err.message}`, true));
