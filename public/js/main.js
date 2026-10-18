import { DEFAULT_LANG, LANGS, applyStatic, getLang, label, locale, setLang, t, teamName } from './i18n.js';
import { esc, markdown } from './md.js';

// where a local "t" (a task, a team) hides the translator
const tr = t;
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
  staged: {}, // spec 09: zone ('goal', 'refine', 'task:<id>') -> the files chosen, not uploaded yet
  pickZone: null,
};

const TERMINAL = ['completed', 'completed_with_failures', 'failed', 'stopped'];
const TEXT_EXT = /\.(md|txt|html?|css|js|mjs|json|svg|csv|py|ts|tsx|jsx|yml|yaml|xml|sh)$/i;
const IMG_EXT = /\.(png|jpe?g|webp|gif|svg)$/i;
const AUDIO_EXT = /\.(mp3|wav|ogg)$/i;
// spec 09: what the agents can use (the server checks it again, bytes included)
const ATTACH_EXT = /\.(png|jpe?g|webp|svg|gif|pdf|docx|txt|md|csv|json|html?|css|js|mp3|wav|ogg)$/i;

const shown = () => S.view ?? S.run;
const isLive = (run) => run && !TERMINAL.includes(run.status);
const teamOf = (id) => S.config?.teams?.[id];
const teamColor = (id) => (id === 'ceo' ? S.config?.ceo?.color : teamOf(id)?.color) ?? '#888';
const teamLabel = (id) => teamName(id, id === 'ceo' ? undefined : teamOf(id)?.label);
const agentName = (id) => (id === 'user' ? t('you') : id === '*' ? t('everyone') : S.agents.get(id)?.name ?? id);
const agentColor = (id) => {
  const a = S.agents.get(id);
  return id === 'user' ? '#8a6cf0' : a ? teamColor(a.kind === 'ceo' ? 'ceo' : a.team) : '#888';
};
const ago = (iso) => {
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return t('ago.s', { n: s });
  if (s < 3600) return t('ago.min', { n: Math.round(s / 60) });
  if (s < 86400) return t('ago.h', { n: Math.round(s / 3600) });
  return new Date(iso).toLocaleDateString(locale());
};
const dur = (a, b) => {
  const s = Math.max(0, Math.round(((b ? new Date(b) : new Date()) - new Date(a)) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: { 'content-type': 'application/json', ...(opts.headers ?? {}) } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error ?? t('error.status', { n: res.status }));
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

// ---------- spec 09: the owner's files ----------

function stage(zone, files) {
  const list = (S.staged[zone] ??= []);
  for (const f of files) {
    if (!ATTACH_EXT.test(f.name)) toast(t('attach.refused', { name: f.name }), true);
    else list.push(f);
  }
  renderChips(zone);
}

function renderChips(zone) {
  document.querySelectorAll(`[data-chips="${CSS.escape(zone)}"]`).forEach((el) => {
    el.innerHTML = (S.staged[zone] ?? []).map((f, i) => `<span class="att-chip">📎 ${esc(f.name)}<button data-unstage="${esc(zone)}" data-i="${i}" title="${esc(t('attach.remove'))}">✕</button></span>`).join('');
  });
}

async function uploadFile(file, url) {
  const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/octet-stream' }, body: file });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(t('attach.failed', { name: file.name, error: body.error ?? res.status }));
  return body;
}

// Uploads the files of a zone, one at a time; what is uploaded leaves the zone, so a
// retry after an error never sends a file twice. Returns the ids.
async function uploadStaged(zone, urlOf) {
  const files = S.staged[zone] ?? [];
  if (!files.length) return [];
  toast(t('attach.uploading', { n: files.length }));
  const ids = [];
  try {
    while (files.length) {
      ids.push((await uploadFile(files[0], urlOf(files[0]))).id);
      files.shift();
    }
  } finally {
    renderChips(zone);
  }
  return ids;
}

const runFileUrl = (run, taskId) => (f) => `/api/runs/${run.id}/attachments?name=${encodeURIComponent(f.name)}${taskId ? `&taskId=${encodeURIComponent(taskId)}` : ''}`;
const zoneOf = (el) => el?.closest?.('[data-drop]');
const withFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes('Files');
// a pasted screenshot is called image.png: give it a name of its own
const named = (f, i) => (/^image\.\w+$/i.test(f.name) ? new File([f], `pasted-${Date.now()}-${i}${f.name.slice(f.name.lastIndexOf('.'))}`, { type: f.type }) : f);

// Drag & drop everywhere: a zone takes the files; a drop anywhere else is ignored
// (the browser would leave the app to open the file).
document.addEventListener('dragover', (e) => {
  if (!withFiles(e)) return;
  e.preventDefault();
  zoneOf(e.target)?.classList.add('dragging');
});
document.addEventListener('dragleave', (e) => {
  const z = zoneOf(e.target);
  if (z && !z.contains(e.relatedTarget)) z.classList.remove('dragging');
});
document.addEventListener('drop', (e) => {
  if (!withFiles(e)) return;
  e.preventDefault();
  const z = zoneOf(e.target);
  document.querySelectorAll('[data-drop].dragging').forEach((el) => el.classList.remove('dragging'));
  if (z && e.dataTransfer.files.length) stage(z.dataset.drop, e.dataTransfer.files);
});
document.addEventListener('paste', (e) => {
  const z = zoneOf(e.target);
  const files = [...(e.clipboardData?.files ?? [])];
  if (!z || !files.length) return;
  e.preventDefault();
  stage(z.dataset.drop, files.map(named));
});

// ---------- voice ----------

function listen(btn, onText) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast(t('voice.unavailable'), true);
  if (btn.rec) {
    btn.rec.stop();
    return;
  }
  const r = new SR();
  r.lang = locale();
  r.interimResults = true;
  r.onresult = (e) => onText([...e.results].map((x) => x[0].transcript).join(' '), e.results[e.results.length - 1].isFinal);
  r.onerror = (e) => e.error !== 'no-speech' && toast(t('voice.mic', { error: e.error }), true);
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
  u.lang = locale();
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
  current: () => (renderCurrent(), renderRefine()),
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
  mode.title = S.mode === 'live' ? t('top.live') : t('top.demo');
  const r = S.run;
  const agents = [...S.agents.values()];
  const busy = agents.filter((a) => a.state !== 'idle').length;
  $('#stats').innerHTML = `<span>${t('top.agents', { n: agents.length, busy })}</span>${r ? `<span>${t('top.calls')} <b>${r.usage?.calls ?? 0}</b></span><span>${t('top.subs')} <b>${r.usage?.subAgents ?? 0}</b></span>` : ''}<span>🧠 <b>${S.brain.count}</b></span>`;
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

// The focused text field survives a re-render: same field, same caret (spec 09:
// the boxes live in panels that every run event redraws).
function keepFocus(root, attr, render) {
  const active = document.activeElement;
  const key = active && root.contains(active) ? active.getAttribute(attr) : null;
  const caret = key ? [active.selectionStart, active.selectionEnd] : null;
  render();
  if (!key) return;
  const again = root.querySelector(`[${attr}="${CSS.escape(key)}"]`);
  if (again && again !== document.activeElement) {
    again.focus();
    if (caret && again.setSelectionRange) again.setSelectionRange(...caret);
  }
}

function renderWaiting() {
  const el = $('#waiting');
  // spec 09: the questions of the run in view; a stopped run keeps them ("pending"), answered later
  const run = shown();
  const live = isLive(run) && run.id === S.run?.id;
  const open = run ? (run.waiting ?? []).filter((w) => (live ? w.status === 'open' : w.status === 'pending')) : [];
  el.classList.toggle('hidden', !open.length);
  if (!open.length) {
    el.innerHTML = '';
    return;
  }
  // keep what the user is typing
  const drafts = Object.fromEntries([...el.querySelectorAll('textarea[data-wait]')].map((t) => [t.dataset.wait, t.value]));
  keepFocus(el, 'data-wait', () => {
    el.innerHTML = `<h3>${live ? t('wait.title', { n: open.length }) : t('wait.pendingTitle', { n: open.length })}</h3>${open
      .map((w) => {
        const a = S.agents.get(w.from);
        const what = w.kind === 'plan' ? t('wait.plan') : w.kind === 'model' ? t('wait.model') : t('wait.question', { task: esc(w.taskId ?? '') });
        const buttons = w.kind === 'plan'
          ? `<button class="btn go" data-answer="${w.id}" data-decision="approve">${t('wait.approve')}</button><button class="btn danger" data-answer="${w.id}" data-decision="reject">${t('wait.reject')}</button>`
          : w.kind === 'model'
            ? `<button class="btn go" data-answer="${w.id}">${t('wait.retry')}</button>`
            : `<button class="btn go" data-answer="${w.id}">${t('wait.reply')}</button><button class="btn" data-solve="${w.id}">${t('wait.solve')}</button>`;
        return `<div class="wait-item">
          <div class="who"><b style="color:${agentColor(w.from)}">${esc(a?.name ?? w.from)}</b> · ${what}</div>
          <div class="q">${esc(w.text)}</div>
          <textarea data-wait="${w.id}" placeholder="${w.kind === 'plan' ? t('wait.notes') : t('wait.answer')}">${esc(drafts[w.id] ?? '')}</textarea>
          <div class="row">${buttons}</div>
        </div>`;
      })
      .join('')}`;
  });
}

function renderCurrent() {
  const run = shown();
  const el = $('#current');
  const live = isLive(S.run);
  $('#btn-start').disabled = Boolean(live);
  $('#btn-start').textContent = live ? t('current.busy') : t('current.start');
  if (!run) {
    el.innerHTML = `<div class="empty">${t('current.empty')}</div>`;
    return;
  }
  const done = run.tasks.filter((t) => t.status === 'done').length;
  const total = run.tasks.length || 1;
  // spec 09: a stopped run (or one with failures) starts again from where it stopped
  const resumable = !isLive(run) && ['stopped', 'completed_with_failures', 'failed'].includes(run.status) && !isLive(S.run);
  const pendingQ = (run.waiting ?? []).filter((w) => w.status === 'pending').length;
  const controls = isLive(run) && run.id === S.run?.id
    ? `<div class="row" style="margin-top:10px">${run.paused ? `<button class="btn" data-act="resume">${t('current.resume')}</button>` : `<button class="btn" data-act="pause">${t('current.pause')}</button>`}<button class="btn danger" data-act="stop">${t('current.stop')}</button></div>`
    : resumable
      ? `${pendingQ ? `<div class="muted" style="margin-top:8px">${t('current.pendingQ', { n: pendingQ })}</div>` : ''}<div class="row" style="margin-top:10px"><button class="btn go" data-act="resume-block">${t('current.resumeBlock')}</button></div>`
      : '';
  const ws = (run.workstreams ?? []).map((w) => {
    const ts = run.tasks.filter((t) => t.wsId === w.id);
    const d = ts.filter((t) => t.status === 'done').length;
    return `<div style="--team:${teamColor(w.team)}"><i></i><span>${esc(w.title)} <span class="muted">· ${esc(teamLabel(w.team))}</span></span><span class="muted">${ts.length ? `${d}/${ts.length}` : label('ws', w.status)}</span></div>`;
  });
  el.innerHTML = `
    <h3>${S.view ? `${t('current.selected')} · <a href="#" data-act="back">${t('current.back')}</a>` : t('current.title')}</h3>
    <div class="goal">${esc(run.goal)}</div>
    <div class="row" style="flex-wrap:wrap"><span class="status ${run.status}">${label('status', run.status)}${run.paused ? t('current.paused') : ''}</span>${run.complexity ? `<span class="badge cx">${run.complexity === 'complex' ? t('current.complex') : t('current.simple')}</span>` : ''}${run.mode === 'demo' ? '<span class="badge">demo</span>' : ''}</div>
    ${run.planSummary ? `<div class="plan-summary">${esc(run.planSummary)}</div>` : ''}
    <div class="progress"><div style="width:${(done / total) * 100}%"></div></div>
    <div class="meta"><span>${done}/${run.tasks.length} task</span><span>⏱ ${dur(run.createdAt, run.finishedAt)}</span><span>${t('current.calls', { n: run.usage?.calls ?? 0 })}</span>${run.usage?.escalations ? `<span>⬆️ ${run.usage.escalations}</span>` : ''}</div>
    ${ws.length ? `<div class="ws-mini">${ws.join('')}</div>` : ''}
    ${run.error ? `<div class="verdict revise" style="margin-top:8px">${esc(run.error)}</div>` : ''}
    ${controls}`;
}

// spec 09: the box under the mission ("talk to the team or ask for a change") is never
// redrawn, only shown or hidden: what the owner types in it survives every run event
function renderRefine() {
  const run = shown();
  $('#refine').classList.toggle('hidden', !run?.tasks?.length);
}

async function sendRefine() {
  const run = shown();
  const text = $('#refine-text').value.trim();
  if (!run) return;
  if (!text) return toast(t('refine.empty'), true);
  try {
    const attachments = await uploadStaged('refine', runFileUrl(run));
    const r = await api(`/api/runs/${run.id}/refine`, { method: 'POST', body: JSON.stringify({ text, attachments }) });
    $('#refine-text').value = '';
    toast(t('refine.sent', { ids: r.targets.map((x) => x.taskId).join(', ') }));
    if (r.resumed) S.view = null;
    invalidate(...ALL);
  } catch (err) {
    toast(err.message, true);
  }
}

async function resumeBlock() {
  const run = shown();
  try {
    await api(`/api/runs/${run.id}/resume`, { method: 'POST' });
    S.view = null;
    toast(t('current.resumed'));
    invalidate(...ALL);
  } catch (err) {
    toast(err.message, true);
  }
}

function renderRuns() {
  const el = $('#runs');
  if (!S.runs.length) {
    el.innerHTML = `<div class="muted" style="padding:6px 2px">${t('runs.empty')}</div>`;
    return;
  }
  const current = shown()?.id;
  el.innerHTML = S.runs
    .slice(0, 30)
    .map((r) => `<div class="run-item${r.id === current ? ' active' : ''}" data-run="${r.id}"><div class="g">${esc(r.goal)}</div><div class="m">${label('status', r.status)} · ${r.done}/${r.tasks} task · ${ago(r.createdAt)}</div></div>`)
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
      const icon = { verdict: '⚖️', escalate: '⬆️', check: '🧪', switch: '🔀', decision: '💡', model_wait: '⏳' }[h.kind] ?? '⚠️';
      const what = h.kind === 'step' ? `${label('tool', h.tool)}${h.target ? ` <code>${esc(h.target.slice(0, 60))}</code>` : ''}<br><span class="muted">${esc(h.text)}</span>` : `${icon} ${esc(h.text)}`;
      return `<div class="ev"><span class="t">${esc(agentName(h.agentId).slice(0, 2))}</span><div>${what}</div></div>`;
    });
    const verdicts = t.verdicts.map((v) => `<div class="verdict ${v.verdict}">${v.verdict === 'pass' ? '✔️' : '✖️'} <b>${esc(agentName(v.judgeId))}</b>, ${tr('card.attempt', { n: v.attempt })}${v.score != null ? ` · ${v.score}/10` : ''}${v.security ? tr('card.security') : ''}${v.feedback ? `\n${esc(v.feedback)}` : ''}</div>`).join('');
    // spec 09: the question of this task, the talk with its agent, and the box to write to it
    const run = shown();
    const asks = (run?.waiting ?? []).filter((w) => w.taskId === t.id && w.kind === 'question' && ['open', 'pending'].includes(w.status));
    const talk = (t.interactions ?? []).slice(-8).map((i) => `<div class="b ${i.from === 'user' ? 'me' : 'them'}"><b>${esc(i.from === 'user' ? tr('you') : agentName(i.from))}</b> ${esc(i.text)}</div>`).join('');
    detail = `<div class="detail">
      ${esc(t.description)}
      ${t.brief ? `<div class="brief"><b>Prompt Lab</b>\n${esc(t.brief)}</div>` : ''}
      ${t.acceptance.length ? `<ul>${t.acceptance.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>` : ''}
      ${t.outputs.length ? `<div>${tr('card.files')} ${t.outputs.map((o) => `<code>${esc(o)}</code>`).join(' ')}</div>` : ''}
      ${t.skills?.length ? `<div>${tr('card.skills')} ${t.skills.map((s) => `<code>${esc(s.name)}</code>`).join(' ')}</div>` : ''}
      ${t.dependsOn.length ? `<div>${tr('card.after')} ${t.dependsOn.map((d) => `<code>${d}</code>`).join(' ')}</div>` : ''}
      ${t.summary ? `<div style="margin-top:6px"><b>${tr('card.delivery')}</b> ${esc(t.summary)}</div>` : ''}
      ${t.error ? `<div class="verdict revise">${esc(t.error)}</div>` : ''}
      ${verdicts}
      ${asks.map((w) => `<div class="task-q">🙋 <b>${tr('box.question')}</b>\n${esc(w.text)}</div>`).join('')}
      ${talk ? `<div class="ilog">${talk}</div>` : ''}
      <div class="ibox-slot" data-slot="${esc(t.id)}"></div>
      ${hist.length ? `<div class="timeline">${hist.join('')}</div>` : ''}
    </div>`;
  }
  return `<div class="task" style="--team:${teamColor(t.team)}" data-task="${t.id}">
    <div class="top"><span class="ring${t.status === 'done' ? ' done' : ''}" style="--p:${progressOf(t)}"></span><span class="title">${esc(t.title)}</span><span class="id">${t.id}</span></div>
    <div class="sub"><span class="team-chip">${esc(teamLabel(t.team))}</span>${agent ? `<span>${esc(agent.name)}${agent.kind === 'sub' ? tr('card.sub') : ''}</span>` : ''}<span>${label('task', t.status)}</span>${t.revisions ? `<span class="badge rev">${tr('card.rev', { n: t.revisions })}</span>` : ''}${t.escalated ? '<span class="badge esc">⬆️ frontier</span>' : ''}</div>
    ${detail}
  </div>`;
}

function renderBoard() {
  const run = shown();
  const el = $('#tab-board');
  if (!run || !run.workstreams?.length) {
    el.innerHTML = `<div class="empty">${run?.status === 'planning' ? t('board.planning') : t('board.empty')}</div>`;
    return;
  }
  const T = run.tasks;
  const waiting = run.waiting?.filter((w) => w.status === 'open').length ?? 0;
  const groups = { all: T, running: T.filter((t) => ['assigned', 'working', 'review', 'revise'].includes(t.status)), queued: T.filter((t) => t.status === 'queued'), done: T.filter((t) => t.status === 'done') };
  const filters = [['all', t('board.all'), T.length], ['running', t('board.running'), groups.running.length], ['queued', t('board.queued'), groups.queued.length], ['done', t('board.done'), groups.done.length]];
  const list = new Set(groups[S.filter].map((t) => t.id));
  const body = run.workstreams
    .map((w) => {
      const ts = T.filter((t) => t.wsId === w.id && list.has(t.id));
      if (!ts.length && S.filter !== 'all') return '';
      return `<div class="ws-head" style="--team:${teamColor(w.team)}"><i></i>${w.id} · ${esc(w.title)}<span>${esc(teamLabel(w.team))} · ${label('ws', w.status)}</span></div>${ts.map(taskCard).join('') || `<div class="muted" style="padding:2px 4px 6px">${w.status === 'preparing' ? t('board.splitting') : t('board.waitingDeps')}</div>`}`;
    })
    .join('');
  const boxes = new Map([...el.querySelectorAll('.ibox')].map((b) => [b.dataset.ibox, b]));
  keepFocus(el, 'data-ibox-text', () => {
    el.innerHTML = `<div class="filters">${filters.map(([k, label, n]) => `<button data-filter="${k}" class="${S.filter === k ? 'on' : ''}">${label} ${n}</button>`).join('')}${waiting ? `<button class="on" style="border-color:#ff6b9a">${t('board.waitingYou', { n: waiting })}</button>` : ''}</div>${body || `<div class="empty">${t('board.nothing')}</div>`}`;
    fillBoxes(el, boxes, run);
  });
}

// The box of a task is one DOM node that survives the redraws of the board (what the
// owner types stays); it is built again only when its kind changes (done or not, live
// or stopped, the language).
function fillBoxes(root, boxes, run) {
  for (const slot of root.querySelectorAll('.ibox-slot')) {
    const task = run.tasks.find((x) => x.id === slot.dataset.slot);
    if (!task) continue;
    const key = `${task.status === 'done'}|${isLive(run) && run.id === S.run?.id}|${getLang()}`;
    let box = boxes.get(task.id);
    if (!box || box.dataset.key !== key) {
      const fresh = taskBox(task, run, key);
      if (box) fresh.querySelector('textarea').value = box.querySelector('textarea').value;
      box = fresh;
    }
    slot.replaceWith(box);
    renderChips(`task:${task.id}`);
  }
}

function taskBox(task, run, key) {
  const done = task.status === 'done';
  const stopped = !(isLive(run) && run.id === S.run?.id);
  const box = document.createElement('div');
  box.className = 'ibox';
  box.dataset.ibox = task.id;
  box.dataset.drop = `task:${task.id}`;
  box.dataset.key = key;
  box.innerHTML = `<div class="ibox-title">${t('box.title')}</div>
    <textarea rows="2" data-ibox-text="${esc(task.id)}" placeholder="${esc(done ? t('box.changePlaceholder') : t('box.placeholder'))}"></textarea>
    <div class="att-chips" data-chips="task:${esc(task.id)}"></div>
    <div class="row"><button class="mic attach" data-attach="task:${esc(task.id)}" title="${esc(t('html.attach'))}">📎</button><button class="btn go" data-isend="${esc(task.id)}">${t('box.send')}</button>${done ? '' : `<button class="btn" data-isolve="${esc(task.id)}">${t('box.solve')}</button>`}${stopped && !done ? `<label class="check"><input type="checkbox" data-iresume="${esc(task.id)}" checked> ${t('box.resume')}</label>` : ''}</div>`;
  return box;
}

async function refreshView(run) {
  if (S.view?.id === run.id && !isLive(S.view)) S.view = await api(`/api/runs/${run.id}`).catch(() => S.view);
  invalidate(...ALL);
}

// Spec 09: the owner talks to one task -- and gives it files. A delivered task takes a
// change (it runs again and QA reviews it again); a stopped run can resume at once.
async function sendBox(taskId, solve = false) {
  const run = shown();
  const task = run?.tasks.find((x) => x.id === taskId);
  if (!task) return;
  const area = document.querySelector(`[data-ibox-text="${CSS.escape(taskId)}"]`);
  let text = (area?.value ?? '').trim();
  if (solve) {
    const q = (run.waiting ?? []).find((w) => w.taskId === taskId && w.kind === 'question' && ['open', 'pending'].includes(w.status));
    if (q) return solveWaiting(q.id);
    text = t('box.solveText');
  }
  const resume = Boolean(document.querySelector(`[data-iresume="${CSS.escape(taskId)}"]`)?.checked);
  try {
    const attachments = await uploadStaged(`task:${taskId}`, runFileUrl(run, taskId));
    if (!text && !attachments.length) return toast(t('refine.empty'), true);
    let r;
    if (task.status === 'done') {
      r = await api(`/api/runs/${run.id}/refine`, { method: 'POST', body: JSON.stringify({ text: text || t('box.useFiles'), attachments, taskId }) });
      toast(t('box.changed'));
    } else {
      r = await api(`/api/runs/${run.id}/tasks/${encodeURIComponent(taskId)}/interact`, { method: 'POST', body: JSON.stringify({ text, attachments, resume }) });
      toast(r.resumed ? t('current.resumed') : t(`box.${r.delivered}`));
    }
    if (area) area.value = '';
    if (r.resumed) S.view = null;
    await refreshView(run);
  } catch (err) {
    toast(err.message, true);
  }
}

async function solveWaiting(id) {
  const run = shown();
  try {
    const r = await api(`/api/runs/${run.id}/answer`, { method: 'POST', body: JSON.stringify({ itemId: id, solve: true }) });
    toast(t('answer.solved', { name: agentName(r.by), text: r.decision.slice(0, 180) }));
    await refreshView(run);
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- comms ----------

function renderComms() {
  const run = shown();
  const el = $('#tab-comms');
  if (!run || !run.messages.length) {
    el.innerHTML = `<div class="empty">${t('comms.empty')}</div>`;
    return;
  }
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.innerHTML = run.messages
    .slice(-180)
    .map((m) => `<div class="msg"><div class="av" style="--team:${agentColor(m.from)}">${esc(agentName(m.from).slice(0, 1))}</div><div>
      <div class="h"><b>${esc(agentName(m.from))}</b> → ${esc(agentName(m.to))} <span class="k ${m.kind}">${label('kind', m.kind)}</span> <span>${new Date(m.ts).toLocaleTimeString(locale())}</span></div>
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
  switchTab('teams');
  if (focus) {
    // the tab may have just opened the right panel: the room is centred in the area it
    // leaves free, measured now rather than when the ResizeObserver reports it (S3.7)
    world.setInsets(measureInsets());
    world.focusRoom(id);
  }
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
      <div class="row" style="margin-bottom:8px"><button class="btn" data-team="">${tr('teams.all')}</button><button class="btn" data-focusroom="${S.team}">${tr('teams.room')}</button></div>
      <div class="team-card" style="--team:${t.color};cursor:default">
        <div class="hd"><span class="av" style="--team:${t.color}">${esc(teamLabel(S.team).slice(0, 1))}</span><b>${esc(teamLabel(S.team))}</b><span>${t.kind === 'service' ? tr('teams.service') : tr('teams.work')} · combo ${esc(t.combo)}</span></div>
        <p class="muted" style="margin:8px 0 0;line-height:1.45">${esc(t.brief)}</p>
        <div class="kpis"><div class="kpi"><small>${tr('teams.runTasks')}</small><b>${st.tasks}</b></div><div class="kpi"><small>${tr('teams.running')}</small><b>${st.running}</b></div><div class="kpi"><small>${tr('teams.avg')}</small><b>${st.avg}</b></div></div>
        <div class="col-title"><span>${tr('teams.agents')}</span><span>${tr('teams.upTo', { n: t.maxSubAgents ?? 0 })}</span></div>
        <div class="people">${members.map((a) => `<div class="person" data-agent="${a.id}"><span class="av" style="--team:${t.color}">${esc(a.name.slice(0, 1))}</span><span><span class="nm">${esc(a.name)}</span> <span class="muted">${a.kind === 'lead' ? tr('teams.lead') : a.kind === 'sub' ? tr('teams.sub') : esc(t.title)}</span></span><span class="st${a.state !== 'idle' ? ' on' : ''}">${label('state', a.state)}</span></div>`).join('')}</div>
        <div class="col-title"><span>${tr('teams.tools')}</span></div>
        <div class="tools">${tools.filter((x) => x !== 'run_command' || S.config.limits.allowShell).map((x) => `<span class="tool">${esc(x)}</span>`).join('')}</div>
        ${st.skills.length ? `<div class="col-title"><span>${tr('teams.skillsUsed')}</span></div><div class="tools">${st.skills.map((x) => `<span class="tool">${esc(x)}</span>`).join('')}</div>` : ''}
        <div class="col-title"><span>${tr('teams.talk')}</span></div>
        <div class="muted" style="font-size:12px;margin-bottom:6px">${tr('teams.talkHint')}</div>
        ${t.lead ? `<button class="btn" data-agent="${t.lead.id}">${tr('teams.openChat', { name: esc(t.lead.name) })}</button>` : ''}
      </div>`;
    return;
  }
  el.innerHTML = teams
    .map(([id, t]) => {
      const st = teamStats(id);
      const members = [...S.agents.values()].filter((a) => a.team === id);
      const busy = members.filter((a) => a.state !== 'idle').length;
      return `<div class="team-card" style="--team:${t.color}" data-team="${id}">
        <div class="hd"><span class="av" style="--team:${t.color}">${esc(teamLabel(id).slice(0, 1))}</span><b>${esc(teamLabel(id))}</b><span>${tr('teams.members', { n: members.length, busy })}</span></div>
        <div class="muted" style="font-size:12px;margin-top:6px">${esc(t.brief)}</div>
        ${st.tasks ? `<div class="muted" style="font-size:12px;margin-top:6px">${tr('teams.tasks', { n: st.tasks, running: st.running })}</div>` : ''}
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
    <div class="muted" style="font-size:12.5px;line-height:1.45;margin-bottom:8px">${t('skills.intro')}</div>
    <div class="searchbar"><input type="search" id="skill-q" placeholder="${t('skills.search', { n: s.count })}" value="${esc(s.query)}"><button class="btn" data-act="skills-search">${t('search')}</button></div>
    <div class="col-title"><span>${t('skills.sources')}</span><button class="btn" data-act="skills-reindex">${t('skills.reindex')}</button></div>
    ${s.sources.map((x) => `<div class="source"><b title="${esc(x.dir)}">${esc(x.label)}</b><span>${x.exists ? t('skills.count', { n: x.count }) : t('skills.missing')}</span></div>`).join('')}
    <div class="col-title"><span>${t('skills.addRepo')}</span></div>
    <div class="searchbar"><input type="url" id="skill-repo" placeholder="${t('skills.repoPlaceholder')}"><button class="btn" data-act="skills-repo">${t('skills.add')}</button></div>
    <div class="col-title"><span>${s.query ? t('skills.results', { q: esc(s.query) }) : t('skills.library')}</span><span>${s.results.length}</span></div>
    ${s.results.map((k) => `<div class="skill" data-skill="${k.id}"><b>${esc(k.name)}</b> <small>· ${esc(k.source)}${k.score ? ` · ${k.score}` : ''}</small><p>${esc(k.description.slice(0, 220))}</p></div>`).join('') || `<div class="empty">${t('skills.none')}</div>`}`;
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
  el.innerHTML = `
    <div class="muted" style="font-size:12.5px;line-height:1.45;margin-bottom:8px">${t('brain.intro')}</div>
    <div class="searchbar"><input type="search" id="brain-q" placeholder="${t('brain.search', { n: b.count })}" value="${esc(b.query)}"><button class="btn" data-act="brain-search">${t('search')}</button></div>
    <details style="margin-bottom:10px"><summary class="muted" style="cursor:pointer">${t('brain.add')}</summary>
      <input type="text" id="note-title" placeholder="${t('brain.titlePlaceholder')}" style="margin:6px 0">
      <textarea id="note-text" placeholder="${t('brain.textPlaceholder')}"></textarea>
      <button class="btn go" data-act="brain-add" style="margin-top:6px">${t('brain.save')}</button>
    </details>
    ${b.notes.map((n) => `<div class="note"><div class="t">${esc(n.title)}</div><div class="x">${esc(n.text.slice(0, 500))}</div><div class="m"><span>${label('note', n.kind)}</span>${n.agentId ? `<span>${esc(agentName(n.agentId))}</span>` : ''}${n.team ? `<span>${esc(teamLabel(n.team))}</span>` : ''}<span>${new Date(n.ts).toLocaleString(locale())}</span></div></div>`).join('') || `<div class="empty">${t('brain.empty')}</div>`}`;
  if (focused) $('#brain-q').focus();
}

// ---------- router ----------

function renderRouter() {
  const r = S.router;
  const el = $('#tab-router');
  if (!r) return;
  const providers = r.providers.filter((p) => p.kind !== 'mock').map((p) => `<div class="prov"><span class="dot ${p.ready ? 'on' : ''}"></span><b>${esc(p.id)}</b><span class="muted">${p.ready ? t('router.ready') : p.enabled ? t('router.missing', { key: esc(p.keyEnv ?? t('router.key')) }) : t('router.off')}</span></div>`).join('');
  const combos = r.combos
    .map((c) => `<div class="combo"><div class="name"><span>${esc(c.name)} <span class="muted" style="font-weight:500">· ${esc(c.strategy)}${c.name === S.config.router.escalationCombo ? t('router.escalation') : ''}</span></span><button class="btn" data-test="${esc(c.name)}">${t('router.test')}</button></div>
      ${c.targets.map((t) => `<div class="t ${t.ready ? '' : 'off'}"><span class="dot ${t.coolingMs ? 'cool' : t.ready ? 'on' : ''}"></span>${esc(t.key)}<span class="s">${t.coolingMs ? tr('router.cooling', { n: Math.ceil(t.coolingMs / 1000) }) : t.stats ? `${t.stats.ok}/${t.stats.calls} ok · ${Math.round(t.stats.totalMs / Math.max(1, t.stats.calls))} ms` : ''}</span></div>`).join('')}</div>`)
    .join('');
  const roles = [['ceo', S.config.ceo.combo], ...Object.entries(S.config.teams).map(([id, t]) => [id, t.combo])].map(([id, combo]) => `<span>${esc(teamLabel(id))}</span><b>${esc(combo)}</b>`).join('');
  const m = S.media;
  const calls = r.recent.slice(0, 40).map((c) => `<div class="call ${c.ok ? '' : 'err'}"><span class="tg">${esc(c.target)}</span><span class="r">${c.ms} ms</span><span class="r">${esc(teamLabel(c.role ?? ''))}${c.agentId ? ` · ${esc(agentName(c.agentId))}` : ''}${c.error ? ` · ${esc(c.error.slice(0, 80))}` : ''}</span><span class="r">${c.tokens.in + c.tokens.out} tok</span></div>`).join('');
  el.innerHTML = `
    <div class="muted" style="line-height:1.45;margin:0 4px 6px">${S.mode === 'live' ? t('router.live') : t('router.demo')}</div>
    <div class="col-title"><span>${t('router.text')}</span></div>${providers}
    <div class="col-title"><span>${t('router.media')}</span></div>
    ${m ? `<div class="kv" style="margin:0 4px"><span>${t('router.images')}</span><b>${esc(m.image.join(' → '))}</b><span>${t('router.voice')}</span><b>${esc(m.speech.join(' → '))}</b></div>${m.providers.map((p) => `<div class="prov"><span class="dot ${p.ready ? 'on' : ''}"></span><b>${esc(p.id)}</b><span class="muted">${p.ready ? t('router.ready') : p.enabled ? t('router.missing', { key: esc(p.keyEnv ?? '') }) : t('router.off')}</span></div>`).join('')}` : ''}
    <div class="col-title"><span>${t('router.teams')}</span></div><div class="kv" style="margin:0 4px">${roles}</div>
    <div class="col-title"><span>${t('router.combos')}</span></div>${combos}
    <div class="col-title"><span>${t('router.recent')}</span></div>${calls || `<div class="muted" style="padding:6px">${t('router.noCalls')}</div>`}
    <div class="muted" style="margin:10px 4px">${t('router.gateway', { origin: location.origin })}</div>`;
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
    el.innerHTML = `<div class="empty">${t('output.empty')}</div>`;
    return;
  }
  if (!S.files || S.files.runId !== run.id) {
    el.innerHTML = `<div class="empty">${t('output.loading')}</div>`;
    loadFiles(run);
    return;
  }
  const files = S.files.list;
  const images = files.filter((f) => IMG_EXT.test(f.path) && !f.path.startsWith('attachments/')); // spec 09: the owner's are under "Your files"
  const audio = files.filter((f) => AUDIO_EXT.test(f.path));
  const hasIndex = files.some((f) => f.path === 'index.html');
  const src = (p) => `/preview/${run.id}/${p.split('/').map(encodeURIComponent).join('/')}`;
  el.innerHTML = `
    ${hasIndex ? `<a class="btn preview-btn" href="/preview/${run.id}/index.html" target="_blank" rel="noopener">${t('output.preview')}</a>` : ''}
    ${images.length ? `<div class="col-title"><span>${t('output.images')}</span><span>${images.length}</span></div><div class="gallery">${images.map((f) => `<img src="${src(f.path)}?v=${f.size}" alt="${esc(f.path)}" data-file="${esc(f.path)}">`).join('')}</div>` : ''}
    ${audio.length ? `<div class="col-title"><span>${t('output.audio')}</span></div>${audio.map((f) => `<div style="margin-bottom:6px"><code>${esc(f.path)}</code><audio controls src="${src(f.path)}" style="width:100%;margin-top:4px"></audio></div>`).join('')}` : ''}
    ${run.attachments?.length ? `<div class="col-title"><span>${t('output.attachments')}</span><span>${run.attachments.length}</span></div><div class="files">${run.attachments.map((a) => `<div class="file" data-file="${esc(a.path)}">📎 ${esc(a.name)}<span>${esc(a.info?.text ?? a.kind)}</span></div>`).join('')}</div>` : ''}
    <div class="col-title"><span>${t('output.files')}</span><span>${files.length}</span></div>
    <div class="files">${files.map((f) => `<div class="file" data-file="${esc(f.path)}">${esc(f.path)}<span>${f.size < 1024 ? `${f.size} B` : `${(f.size / 1024).toFixed(1)} KB`}</span></div>`).join('') || `<div class="muted" style="padding:6px">${t('output.noFiles')}</div>`}</div>
    <div class="col-title"><span>${t('output.report')}</span></div>
    ${run.report ? `<div class="md">${markdown(run.report)}</div>` : `<div class="muted" style="padding:6px">${isLive(run) ? t('output.reportLater') : t('output.noReport')}</div>`}
    <div class="muted" style="font-size:11.5px;margin-top:12px;word-break:break-all">${t('output.folder', { path: esc(run.workspace) })}</div>`;
}

async function openFile(path) {
  const run = shown();
  const src = `/preview/${run.id}/${path.split('/').map(encodeURIComponent).join('/')}`;
  const head = `<div class="head"><h2 style="font-family:var(--mono);font-size:14px">${esc(path)}</h2>${/\.html?$/.test(path) || IMG_EXT.test(path) ? `<a class="btn" href="${src}" target="_blank" rel="noopener">${t('open')}</a>` : ''}<button class="icon-btn x" data-act="close-modal">✕</button></div>`;
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
    .map((a) => `<button class="member${a.state !== 'idle' ? ' busy' : ''}${a.kind === 'lead' || a.kind === 'ceo' ? ' lead' : ''}${a.kind === 'sub' ? ' sub' : ''}${S.selected === a.id ? ' sel' : ''}" data-agent="${a.id}" title="${esc(a.state ? label('state', a.state) : '')}"><span class="av" style="--team:${agentColor(a.id)}">${esc(a.name.slice(0, 1))}</span><span class="nm">${esc(a.name)}<small>${esc(a.kind === 'ceo' ? 'CEO' : teamLabel(a.team))}</small></span></button>`)
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
  const team = teamLabel(a.team);
  const role = a.kind === 'ceo' ? teamName('ceo.title', S.config.ceo.title) : a.kind === 'lead' ? tr('inspector.lead', { team }) : a.kind === 'sub' ? tr('inspector.sub', { team }) : `${t?.title} · ${team}`;
  const run = S.run;
  const task = a.taskId && run ? run.tasks.find((x) => x.id === a.taskId) : null;
  const events = run ? run.tasks.flatMap((x) => x.history.filter((h) => h.agentId === a.id).map((h) => ({ ...h, task: x.id }))).sort((x, y) => y.ts - x.ts).slice(0, 6) : [];
  const chat = S.chats.get(a.id) ?? [];
  const draft = $('#chat-input')?.dataset.agent === a.id ? $('#chat-input').value : '';
  el.innerHTML = `
    <div class="hd"><div class="av" style="--team:${agentColor(a.id)}">${esc(a.name.slice(0, 1))}</div><div><div class="nm">${esc(a.name)}</div><div class="rl">${esc(role)}</div></div><button class="icon-btn x" data-act="close-inspector">✕</button></div>
    <div class="now"><b>${esc(label('state', a.state))}</b>${a.tool ? ` · ${label('tool', a.tool)}` : ''}
      ${task ? `<div>${tr('inspector.task', { id: task.id, title: esc(task.title) })}</div><button class="btn" style="margin-top:6px" data-openbox="${esc(task.id)}">${tr('box.openFromInspector', { id: esc(task.id) })}</button>` : ''}
      ${a.text ? `<div class="muted" style="margin-top:4px">${esc(a.text)}</div>` : ''}
      ${a.model ? `<div class="muted" style="margin-top:4px;font-family:var(--mono);font-size:11px">${esc(a.model)}</div>` : ''}</div>
    ${events.length ? `<div class="timeline">${events.map((h) => `<div class="ev"><span class="t">${h.task.split('.').pop()}</span><div>${h.kind === 'step' ? `${label('tool', h.tool)} ${h.target ? `<code>${esc(h.target.slice(0, 36))}</code>` : ''}` : esc(h.text)}</div></div>`).join('')}</div>` : ''}
    <div class="col-title"><span>${tr('inspector.chat')}${run && isLive(run) ? tr('inspector.steers') : ''}</span><button class="btn" data-act="speak" title="${tr('inspector.speak')}">${S.speak ? '🔊' : '🔈'}</button></div>
    <div class="chat" id="chat-log">${chat.map((m) => `<div class="b ${m.from === 'user' ? 'me' : 'them'}">${esc(m.text)}</div>`).join('') || `<div class="muted" style="font-size:12px">${tr('inspector.empty')}</div>`}</div>
    <div class="chatbox"><input type="text" id="chat-input" data-agent="${a.id}" placeholder="${tr('inspector.write', { name: esc(a.name) })}" value="${esc(draft)}"><button class="mic" id="chat-mic" title="${tr('inspector.talk')}">🎙</button><button class="btn go" data-act="chat-send">${tr('inspector.send')}</button></div>`;
  const log = $('#chat-log');
  log.scrollTop = log.scrollHeight;
}

// spec 09: from an agent to the box of its task, on the board
function openTaskBox(id) {
  S.openTasks.add(id);
  switchTab('board');
  setTimeout(() => document.querySelector(`[data-ibox-text="${CSS.escape(id)}"]`)?.focus(), 80);
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
    if (r.steered) toast(t('chat.steered', { name: agentName(id) }));
  } catch (err) {
    list[list.length - 1] = { from: id, text: `(${err.message})` };
  }
  invalidate('inspector');
}

// ---------- language (spec 06) ----------

// The language lives in the config (ui.language, D1): applied at boot and on every
// config change, so a choice made in another tab reaches this one too.
function applyLanguage() {
  const lang = setLang(S.config?.ui?.language ?? DEFAULT_LANG);
  $('#lang').value = lang;
  applyStatic();
  renderExamples();
  world.relabel((team) => teamLabel(team));
  invalidate(...ALL);
}

async function chooseLanguage(lang) {
  if (lang === getLang()) return;
  try {
    S.config = await api('/api/config', { method: 'POST', body: JSON.stringify({ ui: { language: lang } }) });
    applyLanguage();
    toast(t('lang.saved', { name: LANGS[lang] }));
  } catch (err) {
    $('#lang').value = getLang();
    toast(err.message, true);
  }
}

// ---------- settings ----------

function openSettings() {
  const c = S.config;
  const combos = Object.keys(c.combos);
  const sel = (key, value) => `<select data-combo="${key}">${combos.map((n) => `<option ${n === value ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
  const teamRows = [`<tr><td><b>CEO</b></td><td>${esc(c.ceo.name)}</td><td>${sel('ceo', c.ceo.combo)}</td><td></td></tr>`, ...Object.entries(c.teams).map(([id, t]) => `<tr><td><span class="team-chip" style="--team:${t.color}">${esc(teamLabel(id))}</span></td><td>${esc(t.lead?.name ?? '')}${t.workers?.length ? ` + ${t.workers.map((w) => esc(w.name)).join(', ')}` : ''}</td><td>${sel(id, t.combo)}</td><td><input type="number" min="0" max="3" data-subs="${id}" value="${t.maxSubAgents ?? 0}" title="${tr('settings.subMaxTitle')}"></td></tr>`)].join('');
  const provRows = S.router.providers.filter((p) => p.kind !== 'mock').map((p) => `<tr><td><span class="dot ${p.ready ? 'on' : ''}"></span> <b>${esc(p.id)}</b>${c.providers[p.id]?.custom ? ` <span class="muted">· ${tr('settings.custom')}</span>` : ''}</td><td>${esc(p.kind)}</td><td><code>${esc(p.keyEnv ?? tr('settings.noKey'))}</code></td><td><label><input type="checkbox" data-prov="${p.id}" ${p.enabled ? 'checked' : ''}> ${tr('settings.on')}</label>${c.providers[p.id]?.custom ? ` <button class="btn" data-prov-remove="${esc(p.id)}">${tr('settings.providerRemove')}</button>` : ''}</td></tr>`).join('');
  const mediaRows = (S.media?.providers ?? []).map((p) => `<tr><td><span class="dot ${p.ready ? 'on' : ''}"></span> <b>${esc(p.id)}</b></td><td><code>${esc(p.keyEnv ?? tr('settings.keyless'))}</code></td><td><label><input type="checkbox" data-mprov="${p.id}" ${p.enabled ? 'checked' : ''}> ${tr('settings.on')}</label></td></tr>`).join('');
  const L = c.limits;
  const P = c.pacing;
  $('#settings-body').innerHTML = `
    <div class="head"><h2>${t('settings.title')}</h2><button class="icon-btn x" data-act="close-modal">✕</button></div>
    <h3>${t('settings.language')}</h3>
    <div class="row" style="gap:10px;flex-wrap:wrap"><select data-ui-lang>${Object.entries(LANGS).map(([k, name]) => `<option value="${k}" ${k === getLang() ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select><span class="hint" style="margin:0">${t('settings.languageHint')}</span></div>
    <div class="hint">${t('settings.keys')}</div>
    <h3>${t('settings.teams')}</h3>
    <table><tr><th>${t('settings.team')}</th><th>${t('settings.people')}</th><th>${t('settings.combo')}</th><th>${t('settings.subMax')}</th></tr>${teamRows}</table>
    <h3>${t('settings.how')}</h3>
    <div class="row" style="flex-wrap:wrap;gap:14px">
      <label>${t('settings.parallel')} <input type="number" min="1" max="20" data-limit="maxParallel" value="${L.maxParallel}"></label>
      <label>${t('settings.steps')} <input type="number" min="3" max="60" data-limit="maxSteps" value="${L.maxSteps}"></label>
      <label>${t('settings.revisions')} <input type="number" min="0" max="10" data-limit="maxRevisions" value="${L.maxRevisions}"></label>
      <label>${t('settings.escalateAfter')} <input type="number" min="1" max="10" data-limit="escalateAfter" value="${L.escalateAfter}"></label>
      <label>${t('settings.workstreams')} <input type="number" min="1" max="12" data-limit="maxWorkstreams" value="${L.maxWorkstreams}"></label>
      <label>${t('settings.subtasks')} <input type="number" min="1" max="10" data-limit="maxSubtasks" value="${L.maxSubtasks}"></label>
    </div>
    <div class="row" style="margin-top:8px;gap:14px;flex-wrap:wrap">
      <label>${t('settings.escalationCombo')} ${sel('__escalation', c.router.escalationCombo)}</label>
      <label class="check" style="margin:0"><input type="checkbox" data-bool="approvePlan" ${L.approvePlan ? 'checked' : ''}> ${t('settings.alwaysApprove')}</label>
    </div>
    <div class="row" style="margin-top:8px;gap:14px;flex-wrap:wrap">
      <label>${t('settings.askTimeout')} <input type="number" min="1" max="1440" data-limit-min="askUserTimeoutMs" value="${Math.max(1, Math.round((L.askUserTimeoutMs ?? 300000) / 60000))}"></label>
      <label class="check" style="margin:0"><input type="checkbox" data-bool="autoAnswer" ${L.autoAnswer !== false ? 'checked' : ''}> ${t('settings.autoAnswer')}</label>
    </div>
    <div class="hint" style="margin-top:6px">${t('settings.shell', { state: L.allowShell ? t('settings.shellOn') : t('settings.shellOff') })}</div>
    <h3>${t('settings.pacing')}</h3>
    <div class="row" style="flex-wrap:wrap;gap:14px">${Object.entries(P).map(([k, v]) => `<label>${esc(k)} <input type="number" min="0" step="100" data-pace="${k}" value="${v}"></label>`).join('')}</div>
    <h3>${t('settings.textProviders')}</h3><table>${provRows}</table>
    <h3>${t('settings.providerTitle')}</h3>
    <div class="hint">${t('settings.providerHint')}</div>
    <div class="prov-form">
      <label>${t('settings.providerId')} <input id="prov-id" placeholder="my-llm"></label>
      <label>${t('settings.providerUrl')} <input id="prov-url" placeholder="https://api.example.com/v1"></label>
      <label>${t('settings.providerKey')} <input id="prov-key" placeholder="MY_LLM_API_KEY"></label>
      <label>${t('settings.providerModels')} <input id="prov-models" placeholder="model-a, model-b"></label>
    </div>
    <div class="row" style="flex-wrap:wrap;gap:10px;margin-top:6px"><label class="check" style="margin:0"><input type="checkbox" id="prov-keyless"> ${t('settings.providerKeyless')}</label><span class="muted">${t('settings.providerCombos')}</span>${combos.map((n) => `<label class="check" style="margin:0"><input type="checkbox" data-prov-combo="${esc(n)}"> ${esc(n)}</label>`).join('')}<button class="btn go" data-act="prov-add">${t('settings.providerAdd')}</button></div>
    <h3>${t('settings.mediaProviders')}</h3><table>${mediaRows}</table>
    <div class="hint">${t('settings.pollinations')}</div>
    <h3>${t('settings.combo')}</h3>
    <div class="hint">${t('settings.combosHint')}</div>
    <textarea class="code" id="combos-json" spellcheck="false">${esc(JSON.stringify(c.combos, null, 2))}</textarea>
    <div class="foot"><button class="btn" data-act="close-modal">${t('settings.cancel')}</button><button class="btn go" data-act="save-settings">${t('settings.save')}</button></div>`;
  $('#settings').classList.remove('hidden');
}

async function saveSettings() {
  const body = { ceo: {}, teams: {}, limits: {}, pacing: {}, providers: {}, router: {}, media: { providers: {} }, ui: { language: $('#settings [data-ui-lang]').value } };
  document.querySelectorAll('#settings [data-combo]').forEach((s) => {
    if (s.dataset.combo === 'ceo') body.ceo.combo = s.value;
    else if (s.dataset.combo === '__escalation') body.router.escalationCombo = s.value;
    else (body.teams[s.dataset.combo] ??= {}).combo = s.value;
  });
  document.querySelectorAll('#settings [data-subs]').forEach((i) => ((body.teams[i.dataset.subs] ??= {}).maxSubAgents = Number(i.value)));
  document.querySelectorAll('#settings [data-limit]').forEach((i) => (body.limits[i.dataset.limit] = Number(i.value)));
  document.querySelectorAll('#settings [data-limit-min]').forEach((i) => (body.limits[i.dataset.limitMin] = Math.max(1, Number(i.value)) * 60000));
  document.querySelectorAll('#settings [data-bool]').forEach((i) => (body.limits[i.dataset.bool] = i.checked));
  document.querySelectorAll('#settings [data-pace]').forEach((i) => (body.pacing[i.dataset.pace] = Number(i.value)));
  document.querySelectorAll('#settings [data-prov]').forEach((i) => (body.providers[i.dataset.prov] = { enabled: i.checked }));
  document.querySelectorAll('#settings [data-mprov]').forEach((i) => (body.media.providers[i.dataset.mprov] = { enabled: i.checked }));
  try {
    body.combos = JSON.parse($('#combos-json').value);
  } catch {
    toast(t('settings.badCombos'), true);
    return;
  }
  try {
    S.config = await api('/api/config', { method: 'POST', body: JSON.stringify(body) });
    applyLanguage();
    S.router = await api('/api/router');
    S.media = await api('/api/media');
    S.mode = S.router.mode;
    $('#approve-plan').checked = S.config.limits.approvePlan;
    $('#settings').classList.add('hidden');
    toast(t('settings.saved'));
    invalidate(...ALL);
  } catch (err) {
    toast(err.message, true);
  }
}

// spec 09: a provider registered while the server runs; the sheet is drawn again, so
// its combos (saved with the other settings) include the new models
async function refreshSettings() {
  S.config = await api('/api/config');
  S.router = await api('/api/router');
  S.mode = S.router.mode;
  openSettings();
  invalidate(...ALL);
}

async function addProvider() {
  const body = { id: $('#prov-id').value.trim(), baseUrl: $('#prov-url').value.trim(), keyless: $('#prov-keyless').checked, models: $('#prov-models').value.split(',').map((m) => m.trim()).filter(Boolean) };
  const key = $('#prov-key').value.trim();
  if (key) body.keyEnv = key;
  const combos = [...document.querySelectorAll('#settings [data-prov-combo]:checked')].map((i) => i.dataset.provCombo);
  if (combos.length) body.combos = combos;
  try {
    const r = await api('/api/providers', { method: 'POST', body: JSON.stringify(body) });
    toast(r.ready ? t('settings.providerAdded', { id: r.provider }) : t('settings.providerNoKey', { id: r.provider, key: r.missingKey ?? key }), !r.ready);
    await refreshSettings();
  } catch (err) {
    toast(err.message, true);
  }
}

async function removeProvider(id) {
  try {
    await api(`/api/providers/${encodeURIComponent(id)}`, { method: 'DELETE' });
    await refreshSettings();
  } catch (err) {
    toast(err.message, true);
  }
}

// ---------- actions ----------

async function startRun() {
  const goal = $('#goal').value.trim();
  if (goal.length < 4) return toast(t('start.noGoal'), true);
  try {
    $('#btn-start').disabled = true;
    // spec 09: the composer's files are in the run before the CEO plans it
    const attachments = await uploadStaged('goal', (f) => `/api/uploads?name=${encodeURIComponent(f.name)}`);
    await api('/api/runs', { method: 'POST', body: JSON.stringify({ goal, approvePlan: $('#approve-plan').checked, language: getLang(), attachments }) });
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
  const run = shown(); // spec 09: a stopped run's question too
  try {
    const r = await api(`/api/runs/${run.id}/answer`, { method: 'POST', body: JSON.stringify({ itemId: id, text, decision }) });
    toast(r.resumable ? t('wait.saved') : decision === 'approve' ? t('answer.approved') : decision === 'reject' ? t('answer.rejected') : t('answer.sent'));
    if (r.resumable) await refreshView(run);
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
  const t = e.target.closest('[data-act],[data-task],[data-run],[data-agent],[data-file],[data-test],[data-tab],[data-filter],[data-team],[data-focusroom],[data-skill],[data-answer],[data-solve],[data-attach],[data-unstage],[data-isend],[data-isolve],[data-openbox],[data-prov-remove],.chip');
  if (!t) {
    if (e.target.classList.contains('modal')) e.target.classList.add('hidden');
    return;
  }
  // spec 09: files, the box of a task, the questions of a stopped run
  if (t.dataset.attach) {
    S.pickZone = t.dataset.attach;
    return $('#file-picker').click();
  }
  if (t.dataset.unstage !== undefined) {
    (S.staged[t.dataset.unstage] ?? []).splice(Number(t.dataset.i), 1);
    return renderChips(t.dataset.unstage);
  }
  if (t.dataset.isend) return sendBox(t.dataset.isend);
  if (t.dataset.isolve) return sendBox(t.dataset.isolve, true);
  if (t.dataset.solve) return solveWaiting(t.dataset.solve);
  if (t.dataset.openbox) return openTaskBox(t.dataset.openbox);
  if (t.dataset.provRemove) return removeProvider(t.dataset.provRemove);
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
    toast(r.ok ? tr('router.answers', { combo: t.dataset.test, target: r.target, ms: r.ms, demo: r.demo ? ' (demo)' : '' }) : `${t.dataset.test}: ${r.error}`, !r.ok);
    t.textContent = tr('router.test');
    return;
  }
  const act = t.dataset.act;
  e.preventDefault();
  if (['pause', 'resume', 'stop'].includes(act)) return runAction(act);
  if (act === 'resume-block') return resumeBlock();
  if (act === 'prov-add') return addProvider();
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
    toast(tr('skills.reindexing'));
    await api('/api/skills/reindex', { method: 'POST' }).catch((err) => toast(err.message, true));
    loadSkills();
  }
  if (act === 'skills-repo') {
    const url = $('#skill-repo').value.trim();
    toast(tr('skills.cloning'));
    try {
      const r = await api('/api/skills/repo', { method: 'POST', body: JSON.stringify({ url }) });
      toast(tr('skills.added', { repo: r.repo, added: r.added, total: r.total }));
      loadSkills();
    } catch (err) {
      toast(err.message, true);
    }
  }
  if (act === 'brain-search') loadBrain($('#brain-q').value.trim());
  if (act === 'brain-add') {
    try {
      await api('/api/brain', { method: 'POST', body: JSON.stringify({ title: $('#note-title').value, text: $('#note-text').value }) });
      toast(tr('brain.saved'));
      loadBrain('');
    } catch (err) {
      toast(err.message, true);
    }
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') document.querySelectorAll('.modal').forEach((m) => m.classList.add('hidden'));
  if (e.key === 'Enter' && e.target.id === 'chat-input') sendChat();
  // spec 09: Ctrl/Cmd+Enter sends from the box of a task or from the change box
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.dataset?.iboxText) sendBox(e.target.dataset.iboxText);
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && e.target.id === 'refine-text') sendRefine();
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
$('#file-picker').addEventListener('change', (e) => {
  if (S.pickZone) stage(S.pickZone, e.target.files);
  e.target.value = '';
});
$('#refine-send').addEventListener('click', sendRefine);
$('#goal').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) startRun();
});
$('#goal-mic').addEventListener('click', (e) => listen(e.currentTarget, (text) => ($('#goal').value = text)));
$('#btn-settings').addEventListener('click', openSettings);
// the topbar selector lists LANGS: short codes, each language's own name as the tooltip
$('#lang').innerHTML = Object.entries(LANGS).map(([k, name]) => `<option value="${k}" title="${esc(name)}">${k.toUpperCase()}</option>`).join('');
$('#lang').addEventListener('change', (e) => chooseLanguage(e.target.value));
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
  } else $(id).classList.toggle('closed'); // app.css reads it with :has()
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
const renderExamples = () => ($('#examples').innerHTML = t('examples').map((x) => `<button class="chip">${esc(x)}</button>`).join(''));
renderExamples();

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
    case 'run.view':
      // spec 09: a stored run changed (an answer, a file, words to a task): only its view
      if (S.view?.id === payload.id) S.view = payload;
      if (S.run?.id === payload.id && !isLive(S.run)) S.run = payload;
      invalidate('current', 'waiting', 'board', 'output', 'runs');
      break;
    case 'attachment':
      if (shown()?.id === payload.runId) {
        S.files = null;
        invalidate('output');
      }
      break;
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
      if (payload.kind === 'ask_user') toast(t('toast.asks', { name: agentName(payload.from) }));
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
      toast(payload.status === 'completed' ? t('toast.done') : t('toast.over', { status: label('status', payload.status) }), payload.status !== 'completed');
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
      applyLanguage();
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
  applyLanguage();
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

boot().catch((err) => toast(t('boot.failed', { error: err.message }), true));
