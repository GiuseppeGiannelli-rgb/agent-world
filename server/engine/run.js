import { randomUUID } from 'node:crypto';
import { extname, join } from 'node:path';
import { extractJson } from './json.js';
import { advisorPrompt, ceoPlanPrompt, judgePrompt, leadPlanPrompt, librarianPrompt, promptEngPrompt, rescuePrompt, synthPrompt, workTeams } from './prompts.js';
import { Tasker } from './tasker.js';
import { runCommand, Workspace } from './tools.js';
import { webFetch, webSearch } from './web.js';

const TERMINAL = new Set(['done', 'failed', 'skipped']);
const TERMINAL_RUN = new Set(['completed', 'completed_with_failures', 'failed', 'stopped']);
const TEXT_EXT = new Set(['.md', '.txt', '.html', '.htm', '.css', '.js', '.mjs', '.ts', '.tsx', '.jsx', '.json', '.svg', '.py', '.csv', '.yml', '.yaml', '.xml', '.sh', '.php', '.sql']);
const clip = (s, n) => (s.length > n ? `${s.slice(0, n)}\n… [truncated, ${s.length - n} more chars]` : s);

function slugify(text, max = 40) {
  const base = String(text).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, max);
  return base || 'progetto';
}

const TEAM_SYNONYMS = {
  research: ['research', 'researcher', 'analyst', 'ricerca', 'analysis'],
  dev: ['dev', 'builder', 'engineer', 'developer', 'coder', 'code', 'sviluppo', 'engineering', 'programmer'],
  content: ['content', 'writer', 'copywriter', 'author', 'contenuti', 'editor', 'copy', 'writing'],
  design: ['design', 'designer', 'ui', 'ux'],
  genai: ['genai', 'generative', 'media', 'image', 'images', 'art', 'artist', 'audio', 'voice', 'video', 'immagini', 'creative'],
  prompt: ['prompt', 'prompts', 'prompting', 'prompt-engineering', 'promptlab'],
};

function pickTeam(team, teams) {
  const r = String(team ?? '').toLowerCase().trim();
  if (teams.includes(r)) return r;
  for (const [canon, words] of Object.entries(TEAM_SYNONYMS)) if (words.includes(r) && teams.includes(canon)) return canon;
  return teams.includes('dev') ? 'dev' : teams[0];
}

function safeRelPath(p) {
  const s = String(p ?? '').trim().replace(/\\/g, '/').replace(/^\.?\/+/, '');
  if (!s || s.split('/').includes('..') || /^[a-z]:/i.test(s)) return null;
  return s;
}

const strings = (v, max) => (Array.isArray(v) ? v : v ? [v] : []).filter(Boolean).map(String).slice(0, max);

// Maps model-given ids to ours and removes dependency cycles (Kahn's algorithm:
// whatever is left in a cycle loses the dependencies that close it).
function toDag(items, makeId) {
  const idMap = new Map();
  items.forEach((it, i) => idMap.set(String(it.id ?? i + 1), makeId(i)));
  const nodes = items.map((it, i) => ({ it, id: makeId(i), deps: [...new Set(strings(it.dependsOn, 20).map((d) => idMap.get(d)).filter((d) => d && d !== makeId(i)))] }));
  const indeg = new Map(nodes.map((n) => [n.id, n.deps.length]));
  const order = [];
  const queue = nodes.filter((n) => n.deps.length === 0);
  while (queue.length) {
    const n = queue.shift();
    order.push(n);
    for (const u of nodes) {
      if (u.deps.includes(n.id)) {
        indeg.set(u.id, indeg.get(u.id) - 1);
        if (indeg.get(u.id) === 0) queue.push(u);
      }
    }
  }
  for (const n of nodes) {
    if (!order.includes(n)) {
      n.deps = n.deps.filter((d) => order.some((o) => o.id === d));
      order.push(n);
    }
  }
  return nodes;
}

export function normalizePlan(raw, cfg) {
  const teams = workTeams(cfg);
  const items = Array.isArray(raw?.workstreams) ? raw.workstreams.slice(0, cfg.limits.maxWorkstreams) : [];
  if (!items.length) throw new Error('The plan has no workstreams');
  const workstreams = toDag(items, (i) => `w${i + 1}`).map(({ it, id, deps }) => ({
    id,
    team: pickTeam(it.team ?? it.role, teams),
    title: String(it.title ?? `Workstream ${id}`).slice(0, 80),
    objective: String(it.objective ?? it.description ?? it.title ?? '').slice(0, 2000),
    deliverables: [...new Set(strings(it.deliverables ?? it.outputs, 8).map(safeRelPath).filter(Boolean))],
    acceptance: strings(it.acceptance, 6),
    dependsOn: deps,
    status: 'queued',
    leadId: null,
    summary: '',
    error: null,
    startedAt: null,
    finishedAt: null,
  }));
  return { complexity: raw.complexity === 'complex' ? 'complex' : 'simple', summary: String(raw.summary ?? '').slice(0, 600), workstreams };
}

function newTask(fields) {
  return { skills: [], brief: '', pitfalls: [], status: 'queued', agentId: null, attempts: 0, revisions: 0, escalated: false, summary: '', files: [], verdicts: [], history: [], error: null, startedAt: null, finishedAt: null, ...fields };
}

export function normalizeSubtasks(raw, ws, cfg) {
  const items = Array.isArray(raw?.subtasks) ? raw.subtasks.slice(0, cfg.limits.maxSubtasks) : [];
  if (!items.length) return singleSubtask(ws);
  const tasks = toDag(items, (i) => `${ws.id}.${i + 1}`).map(({ it, id, deps }) =>
    newTask({
      id,
      wsId: ws.id,
      team: ws.team,
      title: String(it.title ?? `Parte ${id}`).slice(0, 80),
      description: String(it.description ?? it.title ?? '').slice(0, 2000),
      acceptance: strings(it.acceptance, 6),
      outputs: [...new Set(strings(it.outputs, 5).map(safeRelPath).filter(Boolean))],
      dependsOn: deps,
    }),
  );
  // every deliverable must belong to somebody: orphans go to the last subtask
  const covered = new Set(tasks.flatMap((t) => t.outputs));
  const orphans = ws.deliverables.filter((d) => !covered.has(d));
  if (orphans.length) tasks.at(-1).outputs.push(...orphans);
  return tasks;
}

function singleSubtask(ws) {
  return [newTask({ id: `${ws.id}.1`, wsId: ws.id, team: ws.team, title: ws.title, description: ws.objective, acceptance: ws.acceptance, outputs: ws.deliverables, dependsOn: [] })];
}

export class Run {
  constructor({ goal, ctx, options = {} }) {
    this.ctx = ctx;
    this.abort = new AbortController();
    this.active = new Set();
    this.preparing = new Set();
    this.resumeWaiters = [];
    this.answerWaiters = new Map();
    this.steering = [];
    this.seenSteering = new Map();
    this.lastRunEmit = 0;
    const id = randomUUID().slice(0, 8);
    const slug = `${slugify(goal)}-${id}`;
    this.data = {
      id,
      slug,
      goal,
      status: 'planning',
      complexity: null,
      paused: false,
      approvePlan: Boolean(options.approvePlan ?? ctx.config.get().limits.approvePlan),
      mode: ctx.router.mode(),
      createdAt: new Date().toISOString(),
      finishedAt: null,
      planSummary: '',
      workstreams: [],
      tasks: [],
      messages: [],
      waiting: [],
      report: '',
      error: null,
      usage: { calls: 0, tokensIn: 0, tokensOut: 0, escalations: 0, subAgents: 0 },
      workspace: join(ctx.workspaceRoot, slug),
    };
    this.ws = new Workspace(this.data.workspace);
  }

  get cfg() {
    return this.ctx.config.get();
  }

  get team() {
    return this.ctx.team;
  }

  get ceo() {
    return this.team.ceo();
  }

  taskById(id) {
    return this.data.tasks.find((t) => t.id === id);
  }

  wsById(id) {
    return this.data.workstreams.find((w) => w.id === id);
  }

  // ---------- events ----------

  emitRun(force = false) {
    this.ctx.store.save(this.data, force);
    const now = Date.now();
    if (!force && now - this.lastRunEmit < 200) {
      clearTimeout(this.runEmitTimer);
      this.runEmitTimer = setTimeout(() => this.emitRun(true), 220);
      return;
    }
    clearTimeout(this.runEmitTimer);
    this.lastRunEmit = now;
    this.ctx.bus.emit('run', this.data);
  }

  emitTask(task) {
    this.ctx.bus.emit('task', { runId: this.data.id, task });
    this.emitRun();
  }

  emitWs(ws) {
    this.ctx.bus.emit('workstream', { runId: this.data.id, ws });
    this.emitRun();
  }

  message(from, to, kind, text) {
    const m = { id: randomUUID().slice(0, 8), runId: this.data.id, ts: Date.now(), from, to, kind, text: String(text).slice(0, 4000) };
    this.data.messages.push(m);
    if (this.data.messages.length > 800) this.data.messages.splice(0, this.data.messages.length - 800);
    this.ctx.bus.emit('message', m);
    this.emitRun();
  }

  note(task, agent, kind, text, extra = {}) {
    task.history.push({ ts: Date.now(), agentId: agent.id, kind, text: String(text).slice(0, 600), ...extra });
    if (task.history.length > 80) task.history.splice(0, task.history.length - 80);
  }

  step(task, agent, action) {
    const a = action.args;
    const target = a.path ?? a.url ?? a.query ?? a.cmd ?? a.question ?? a.name ?? a.title ?? a.prompt ?? '';
    this.note(task, agent, 'step', action.thought, { tool: action.tool, target: String(target).slice(0, 200) });
    this.team.set(agent.id, { state: action.tool === 'finish' ? 'thinking' : 'tool', tool: action.tool, text: action.thought, toolTarget: String(target).slice(0, 120) });
    this.emitRun();
  }

  // ---------- flow control ----------

  sleep(ms) {
    const signal = this.abort.signal;
    return new Promise((resolve, reject) => {
      if (signal.aborted) return reject(signal.reason);
      const t = setTimeout(resolve, ms);
      signal.addEventListener('abort', () => {
        clearTimeout(t);
        reject(signal.reason);
      }, { once: true });
    });
  }

  async gate(agent) {
    if (this.abort.signal.aborted) throw this.abort.signal.reason;
    if (!this.data.paused) return;
    if (agent) this.team.set(agent.id, { state: 'paused' });
    await new Promise((resolve) => this.resumeWaiters.push(resolve));
    if (this.abort.signal.aborted) throw this.abort.signal.reason;
    if (agent) this.team.set(agent.id, { state: 'thinking' });
  }

  pause() {
    if (TERMINAL_RUN.has(this.data.status)) return;
    this.data.paused = true;
    this.message(this.ceo.id, '*', 'system', 'Run in pausa: il lavoro in corso termina il passo attuale.');
    this.emitRun(true);
  }

  resume() {
    if (!this.data.paused) return;
    this.data.paused = false;
    this.resumeWaiters.splice(0).forEach((r) => r());
    this.message(this.ceo.id, '*', 'system', 'Si riparte.');
    this.emitRun(true);
    this.tick();
  }

  stop() {
    if (TERMINAL_RUN.has(this.data.status)) return;
    this.abort.abort(new Error('Stopped by the user'));
    this.resumeWaiters.splice(0).forEach((r) => r());
    for (const [, resolve] of this.answerWaiters) resolve(null);
  }

  // The owner's messages, routed to everyone ("all"), a team or one agent.
  steer(scope, text) {
    this.steering.push({ id: randomUUID().slice(0, 6), scope, text: String(text).slice(0, 2000) });
  }

  takeSteering(task, agent) {
    const seen = this.seenSteering.get(agent.id) ?? new Set();
    this.seenSteering.set(agent.id, seen);
    const scopes = new Set(['all', `team:${task.team}`, `agent:${agent.id}`]);
    const fresh = this.steering.filter((s) => scopes.has(s.scope) && !seen.has(s.id));
    fresh.forEach((s) => seen.add(s.id));
    return fresh.map((s) => s.text);
  }

  // ---------- waiting for the owner ----------

  addWaiting(item) {
    const w = { id: randomUUID().slice(0, 8), status: 'open', answer: null, createdAt: Date.now(), ...item };
    this.data.waiting.push(w);
    this.ctx.bus.emit('waiting', { runId: this.data.id, item: w });
    this.emitRun(true);
    return w;
  }

  waitAnswer(item, timeoutMs) {
    return new Promise((resolve) => {
      let timer = null;
      const done = (answer) => {
        clearTimeout(timer);
        this.answerWaiters.delete(item.id);
        if (item.status === 'open') item.status = answer ? 'answered' : 'expired';
        this.ctx.bus.emit('waiting', { runId: this.data.id, item });
        this.emitRun(true);
        resolve(answer);
      };
      this.answerWaiters.set(item.id, done);
      if (timeoutMs) timer = setTimeout(() => done(null), timeoutMs);
    });
  }

  answer(id, { text = '', decision = null }) {
    const item = this.data.waiting.find((w) => w.id === id);
    const resolve = this.answerWaiters.get(id);
    if (!item || !resolve || item.status !== 'open') return false;
    item.answer = { text: String(text).slice(0, 4000), decision, at: Date.now() };
    item.status = 'answered';
    this.message('user', item.from, 'reply', decision ? `${decision === 'approve' ? 'Approvato' : 'Rifiutato'}${text ? `: ${text}` : ''}` : text);
    resolve(item.answer);
    return true;
  }

  // ---------- model calls ----------

  async chat({ role, use, messages, json, maxTokens, agent, task }) {
    const res = await this.ctx.router.chat({ role, use: use ?? undefined, messages, json, maxTokens, signal: this.abort.signal, meta: { runId: this.data.id, taskId: task?.id, agentId: agent?.id } });
    this.data.usage.calls += 1;
    this.data.usage.tokensIn += res.usage?.in ?? 0;
    this.data.usage.tokensOut += res.usage?.out ?? 0;
    if (agent && this.team.get(agent.id)) this.team.get(agent.id).model = res.target;
    return res;
  }

  async chatJson(opts, validate, tries = 2) {
    let messages = opts.messages;
    for (let i = 0; i < tries; i++) {
      const res = await this.chat({ ...opts, messages, json: true });
      const obj = extractJson(res.text);
      if (obj && (!validate || validate(obj))) return obj;
      messages = [...messages, { role: 'assistant', content: res.text.slice(0, 3000) }, { role: 'user', content: 'That was not the JSON object I asked for. Reply again with ONLY the JSON object, exactly in the requested shape.' }];
    }
    return null;
  }

  // ---------- lifecycle ----------

  async start() {
    try {
      await this.ws.ensure();
      await this.plan();
      if (this.data.approvePlan) await this.approval();
      this.data.status = 'running';
      this.emitRun(true);
      await this.schedule();
      this.data.status = 'synthesizing';
      this.emitRun(true);
      await this.synthesize();
      const failed = this.data.workstreams.some((w) => w.status !== 'done');
      this.data.status = failed ? 'completed_with_failures' : 'completed';
    } catch (err) {
      if (this.abort.signal.aborted) {
        this.data.status = 'stopped';
        this.data.error ??= err.message === 'Stopped by the user' ? null : err.message;
        for (const t of this.data.tasks) if (!TERMINAL.has(t.status)) t.status = 'skipped';
        for (const w of this.data.workstreams) if (!TERMINAL.has(w.status)) w.status = 'skipped';
      } else {
        this.data.status = 'failed';
        this.data.error = err.message;
        this.message(this.ceo.id, '*', 'error', `Il run si è fermato: ${err.message}`);
      }
    } finally {
      this.data.finishedAt = new Date().toISOString();
      this.data.paused = false;
      for (const w of this.data.waiting) if (w.status === 'open') w.status = 'expired';
      for (const a of this.team.list()) {
        if (a.runId === this.data.id || a.kind === 'ceo') this.team.release(a.id, a.kind === 'ceo' && this.data.status === 'completed' ? { state: 'celebrating', text: 'Missione compiuta!' } : {});
      }
      this.emitRun(true);
      this.ctx.bus.emit('run.done', { runId: this.data.id, status: this.data.status });
    }
  }

  async plan() {
    const ceo = this.ceo;
    this.team.set(ceo.id, { state: 'thinking', runId: this.data.id, text: 'Studio l\'obiettivo e organizzo i team…' });
    this.message('user', ceo.id, 'goal', this.data.goal);
    const memory = this.ctx.brain.search(this.data.goal, 4, { agentId: ceo.id }).map((n) => `- ${n.title}: ${n.text.slice(0, 240)}`).join('\n');
    const obj = await this.chatJson(
      { role: 'ceo', messages: ceoPlanPrompt({ cfg: this.cfg, ceo, goal: this.data.goal, memory }), maxTokens: 6000, agent: ceo },
      (o) => Array.isArray(o.workstreams) && o.workstreams.length > 0,
    );
    if (!obj) throw new Error('The CEO could not produce a valid plan');
    const plan = normalizePlan(obj, this.cfg);
    this.data.complexity = plan.complexity;
    this.data.planSummary = plan.summary;
    this.data.workstreams = plan.workstreams;
    this.ctx.bus.emit('plan', { runId: this.data.id, workstreams: plan.workstreams, complexity: plan.complexity, summary: plan.summary });
    const label = (t) => this.cfg.teams[t]?.label ?? t;
    this.message(ceo.id, '*', 'plan', `${plan.complexity === 'complex' ? 'Missione complessa' : 'Missione semplice'}. ${plan.summary}\n\n${plan.workstreams.map((w) => `${w.id} · ${w.title} → ${label(w.team)}${w.dependsOn.length ? ` (dopo ${w.dependsOn.join(', ')})` : ''}`).join('\n')}`);
    this.team.set(ceo.id, { state: 'idle', text: `Piano: ${plan.workstreams.length} workstream` });
    this.emitRun(true);
    await this.sleep(1200 + plan.workstreams.length * 200);
  }

  async approval() {
    this.data.status = 'awaiting_approval';
    const label = (t) => this.cfg.teams[t]?.label ?? t;
    const item = this.addWaiting({
      kind: 'plan',
      from: this.ceo.id,
      text: `Approvi il piano?\n${this.data.planSummary}\n\n${this.data.workstreams.map((w) => `${w.id} · ${w.title} → ${label(w.team)}`).join('\n')}`,
    });
    this.team.set(this.ceo.id, { state: 'asking', text: 'Aspetto la tua approvazione del piano' });
    const answer = await this.waitAnswer(item, 0);
    if (this.abort.signal.aborted) throw this.abort.signal.reason;
    if (answer?.decision === 'reject') {
      this.data.error = `Piano rifiutato${answer.text ? `: ${answer.text}` : ''}`;
      this.abort.abort(new Error(this.data.error));
      throw this.abort.signal.reason;
    }
    if (answer?.text) this.steer('all', answer.text);
    this.team.set(this.ceo.id, { state: 'idle', text: 'Piano approvato' });
  }

  schedule() {
    return new Promise((resolve, reject) => {
      this.finishSchedule = resolve;
      this.abort.signal.addEventListener('abort', () => reject(this.abort.signal.reason), { once: true });
      this.tick();
    });
  }

  tick() {
    if (!this.finishSchedule || this.abort.signal.aborted) return;
    const W = this.data.workstreams;
    const T = this.data.tasks;
    const bad = (s) => s === 'failed' || s === 'skipped';

    let changed = true;
    while (changed) {
      changed = false;
      for (const w of W) {
        const blocker = w.status === 'queued' && w.dependsOn.find((d) => bad(this.wsById(d)?.status));
        if (blocker) {
          w.status = 'skipped';
          w.error = `Dipende da ${blocker}, che non è stato completato`;
          this.emitWs(w);
          changed = true;
        }
      }
      for (const t of T) {
        const blocker = t.status === 'queued' && t.dependsOn.find((d) => bad(this.taskById(d)?.status));
        if (blocker) {
          t.status = 'skipped';
          t.error = `Dipende da ${blocker}, che non è stato completato`;
          this.emitTask(t);
          changed = true;
        }
      }
      for (const w of W) {
        if (w.status !== 'running') continue;
        const mine = T.filter((t) => t.wsId === w.id);
        if (!mine.length || !mine.every((t) => TERMINAL.has(t.status))) continue;
        w.status = mine.every((t) => t.status === 'done') ? 'done' : 'failed';
        w.summary = mine.map((t) => t.summary).filter(Boolean).join(' ').slice(0, 1500);
        w.finishedAt = new Date().toISOString();
        this.emitWs(w);
        const lead = this.team.lead(w.team);
        this.message(lead?.id ?? this.ceo.id, this.ceo.id, w.status === 'done' ? 'deliver' : 'error', w.status === 'done' ? `${w.id} completato: ${w.title}` : `${w.id} chiuso con task non completati`);
        changed = true;
      }
    }

    if (!this.data.paused) {
      for (const w of W) {
        if (w.status !== 'queued' || !w.dependsOn.every((d) => this.wsById(d)?.status === 'done')) continue;
        const lead = this.team.tryAcquireLead(w.team, this.data.id);
        if (!lead) continue;
        w.status = 'preparing';
        w.leadId = lead.id;
        w.startedAt = new Date().toISOString();
        this.preparing.add(w.id);
        this.emitWs(w);
        this.prepare(w, lead)
          .then(() => {
            w.status = 'running';
            this.emitWs(w);
          })
          .catch((err) => {
            if (this.abort.signal.aborted) return;
            w.status = 'failed';
            w.error = err.message;
            this.message(lead.id, this.ceo.id, 'error', `Non riesco a organizzare ${w.id}: ${err.message}`);
            this.emitWs(w);
          })
          .finally(() => {
            this.preparing.delete(w.id);
            if (!this.abort.signal.aborted) this.team.release(lead.id);
            this.tick();
          });
      }
      for (const t of T) {
        if (this.active.size >= this.cfg.limits.maxParallel) break;
        if (t.status !== 'queued' || this.wsById(t.wsId)?.status !== 'running') continue;
        if (!t.dependsOn.every((d) => this.taskById(d)?.status === 'done')) continue;
        const spawnLimit = this.data.complexity === 'complex' ? this.cfg.teams[t.team]?.maxSubAgents ?? 0 : 0;
        const agent = this.team.tryAcquire(t.team, this.data.id, { allowLead: true, spawnLimit });
        if (!agent) continue;
        if (agent.kind === 'sub' && !agent.counted) {
          agent.counted = true;
          this.data.usage.subAgents += 1;
          this.message(this.team.lead(t.team)?.id ?? this.ceo.id, agent.id, 'spawn', `Ti ho creato per ${t.id} · ${t.title}`);
        }
        this.active.add(t.id);
        this.runTask(t, agent)
          .catch((err) => {
            if (this.abort.signal.aborted) return;
            t.status = 'failed';
            t.error = err.message;
            t.finishedAt = new Date().toISOString();
            this.note(t, agent, 'error', err.message);
            this.message(agent.id, this.team.lead(t.team)?.id ?? this.ceo.id, 'error', `Non riesco a completare "${t.title}": ${err.message}`);
            this.emitTask(t);
          })
          .finally(() => {
            this.active.delete(t.id);
            if (!this.abort.signal.aborted) this.team.release(agent.id);
            this.tick();
          });
      }
    }

    if (this.active.size === 0 && this.preparing.size === 0 && W.every((w) => TERMINAL.has(w.status))) {
      const done = this.finishSchedule;
      this.finishSchedule = null;
      done();
    }
  }

  // ---------- a lead organises one workstream ----------

  async prepare(ws, lead) {
    const { pacing } = this.cfg;
    const complex = this.data.complexity === 'complex';
    this.message(this.ceo.id, lead.id, 'brief', `${ws.id} · ${ws.title}\n${ws.objective}`);
    this.team.set(lead.id, { state: 'fetching', wsId: ws.id, runId: this.data.id, text: ws.title });
    await this.sleep(pacing.fetchMs);
    this.team.set(lead.id, { state: 'thinking', text: 'Divido il lavoro del team…' });

    let tasks = singleSubtask(ws);
    if (complex) {
      const upstream = ws.dependsOn.map((d) => this.wsById(d)).map((w) => `${w.id} ${w.title}: ${w.summary || 'done'} (files: ${w.deliverables.join(', ')})`);
      const raw = await this.chatJson(
        { role: ws.team, messages: leadPlanPrompt({ cfg: this.cfg, lead, team: ws.team, goal: this.data.goal, ws, upstream }), maxTokens: 4000, agent: lead },
        (o) => Array.isArray(o.subtasks),
      );
      if (raw) tasks = normalizeSubtasks(raw, ws, this.cfg);
    }

    await this.assignSkills(tasks, lead, complex);
    if (complex) await this.refineBriefs(tasks, lead);

    this.data.tasks.push(...tasks);
    this.ctx.bus.emit('subtasks', { runId: this.data.id, wsId: ws.id, leadId: lead.id, tasks });
    this.message(lead.id, this.ceo.id, 'split', tasks.length > 1 ? `${ws.id} diviso in ${tasks.length} sotto-task:\n${tasks.map((t) => `${t.id} · ${t.title}${t.dependsOn.length ? ` (dopo ${t.dependsOn.join(', ')})` : ''}`).join('\n')}` : `${ws.id}: lo affido al team così com'è.`);
    this.team.set(lead.id, { state: 'idle', text: `${tasks.length} sotto-task pronti` });
    this.emitRun(true);
  }

  async assignSkills(tasks, lead, complex) {
    const lib = this.ctx.skills;
    if (!lib.skills.length) return;
    const perTask = this.cfg.skills?.perTask ?? 3;
    const librarian = this.team.lead('skills') ?? this.team.ofTeam('skills')[0] ?? null;
    if (librarian) this.team.set(librarian.id, { state: 'tool', tool: 'search_skills', toolTarget: `${lib.skills.length} skill`, text: `Cerco le skill giuste per ${tasks.length} task`, runId: this.data.id });
    await Promise.all(
      tasks.map(async (t) => {
        const candidates = lib.search(`${t.title} ${t.description} ${this.cfg.teams[t.team]?.label ?? ''} ${t.team} ${t.outputs.join(' ')}`, 10);
        if (!candidates.length) return;
        let picks = null;
        if (complex && librarian && candidates.length > 1) {
          const obj = await this.chatJson(
            { role: 'skills', messages: librarianPrompt({ librarian, goal: this.data.goal, task: t, candidates, perTask }), maxTokens: 800, agent: librarian, task: t },
            (o) => Array.isArray(o.picks),
          );
          if (obj) picks = obj.picks.map((p) => candidates.find((c) => c.id === p.id || c.name === p.id)).filter(Boolean);
        }
        if (!picks) picks = candidates.filter((c) => c.score >= Math.max(1.2, candidates[0].score * 0.55));
        t.skills = [...new Map(picks.map((p) => [p.id, { id: p.id, name: p.name, source: p.source }])).values()].slice(0, perTask);
      }),
    );
    if (librarian) {
      const lines = tasks.filter((t) => t.skills.length).map((t) => `${t.id} → ${t.skills.map((s) => s.name).join(', ')}`);
      this.message(librarian.id, lead.id, 'skills', lines.length ? lines.join('\n') : 'Nessuna skill adatta: meglio niente che una sbagliata.');
      this.team.set(librarian.id, { state: 'idle', tool: null, text: '' });
    }
  }

  async refineBriefs(tasks, lead) {
    const pe = this.team.ofTeam('prompt').find((a) => !a.busy) ?? null;
    if (!pe) return;
    pe.busy = true;
    try {
      this.team.set(pe.id, { state: 'thinking', runId: this.data.id, text: `Riscrivo ${tasks.length} brief` });
      await Promise.all(
        tasks.map(async (t) => {
          const obj = await this.chatJson(
            { role: 'prompt', messages: promptEngPrompt({ pe, goal: this.data.goal, task: t, team: this.cfg.teams[t.team]?.label ?? t.team, skills: t.skills.map((s) => s.name) }), maxTokens: 1500, agent: pe, task: t },
            (o) => typeof o.brief === 'string',
          );
          if (!obj) return;
          t.brief = obj.brief.slice(0, 3000);
          t.acceptance = [...new Set([...t.acceptance, ...strings(obj.acceptance, 2)])].slice(0, 6);
          t.pitfalls = strings(obj.pitfalls, 4);
        }),
      );
      this.message(pe.id, lead.id, 'prompt', `Brief affinati per ${tasks.map((t) => t.id).join(', ')}`);
    } finally {
      pe.busy = false;
      this.team.set(pe.id, { state: 'idle', runId: null, text: '' });
    }
  }

  inputsFor(task) {
    const ws = this.wsById(task.wsId);
    const fromTasks = this.data.tasks.filter((t) => t.status === 'done' && (task.dependsOn.includes(t.id) || ws.dependsOn.includes(t.wsId)));
    return fromTasks.map((t) => ({ id: t.id, title: t.title, agent: this.team.get(t.agentId)?.name ?? t.team, summary: t.summary, files: t.files.length ? t.files : t.outputs }));
  }

  async skillsText(task) {
    const parts = [];
    let budget = 9000;
    for (const s of task.skills ?? []) {
      if (budget <= 0) break;
      try {
        const { text } = await this.ctx.skills.read(s.id, Math.min(4000, budget));
        budget -= text.length;
        parts.push(`### ${s.name}\n${text}`);
      } catch {
        // a skill that disappeared is skipped
      }
    }
    return parts.join('\n\n');
  }

  // ---------- one subtask ----------

  async runTask(task, agent) {
    const { limits, pacing, router } = this.cfg;
    const lead = this.team.lead(task.team);
    task.agentId = agent.id;
    task.status = 'assigned';
    task.startedAt = new Date().toISOString();
    this.emitTask(task);
    this.team.set(agent.id, { state: 'assigned', taskId: task.id, wsId: task.wsId, runId: this.data.id, text: task.title, target: lead && lead.id !== agent.id ? lead.id : null });
    if (lead && lead.id !== agent.id) this.message(lead.id, agent.id, 'assign', `${task.id} · ${task.title}\n${task.description}`);
    await this.sleep(pacing.pickupMs);

    task.status = 'working';
    this.emitTask(task);
    const tasker = new Tasker(this, task, agent);
    let feedback = null;
    let rescued = false;
    for (;;) {
      task.attempts += 1;
      const out = await tasker.work(feedback);
      const problems = out.stepLimit ? [`Hai esaurito i ${limits.maxSteps} passi disponibili senza chiamare finish. Concentrati sui file richiesti e consegna.`] : await this.machineCheck(task);

      if (problems.length === 0) {
        task.summary = out.summary;
        task.files = out.files?.length ? out.files : task.outputs;
        task.status = 'review';
        this.emitTask(task);
        this.team.set(agent.id, { state: 'waiting', tool: null, text: 'In attesa di revisione' });
        const verdict = await this.review(task, agent, out);
        if (verdict.verdict === 'pass') {
          task.status = 'done';
          task.finishedAt = new Date().toISOString();
          this.emitTask(task);
          this.team.set(agent.id, { state: 'delivering', text: 'Consegnato!' });
          if (lead && lead.id !== agent.id) this.message(agent.id, lead.id, 'deliver', `${task.id} consegnato: ${task.summary}`);
          await this.sleep(pacing.deliverMs);
          return;
        }
        feedback = verdict.feedback || 'Il revisore chiede di migliorare il lavoro rispetto ai criteri di accettazione.';
      } else {
        feedback = problems.join('\n');
        this.note(task, agent, 'check', feedback);
      }

      task.revisions += 1;
      if (task.revisions >= limits.escalateAfter && !tasker.use && this.cfg.combos[router.escalationCombo]) {
        tasker.use = router.escalationCombo;
        task.escalated = true;
        this.data.usage.escalations += 1;
        this.note(task, agent, 'escalate', `Escalation al modello "${router.escalationCombo}"`);
        this.message(lead?.id ?? this.ceo.id, agent.id, 'escalate', `Dopo ${task.revisions} revisioni passo ${task.id} al modello più forte (${router.escalationCombo}).`);
      }
      if (task.revisions > limits.maxRevisions) {
        if (rescued) throw new Error(`Ancora non approvato dopo l'aiuto del lead. Ultimo feedback: ${feedback.slice(0, 300)}`);
        const decision = await this.rescue(task, agent, feedback);
        if (decision.action === 'skip') throw new Error(`Il lead ha deciso di saltarlo: ${decision.guidance}`);
        rescued = true;
        feedback = `Indicazioni del lead: ${decision.guidance}\n\nUltimo feedback del revisore:\n${feedback}`;
      }
      task.status = 'revise';
      this.emitTask(task);
      this.team.set(agent.id, { state: 'thinking', tool: null, text: task.escalated ? 'Riprovo con un modello più forte…' : 'Correggo seguendo il feedback…', escalated: task.escalated });
    }
  }

  async missingOutputs(task) {
    const missing = [];
    for (const p of task.outputs) if ((await this.ws.size(p)) <= 0) missing.push(p);
    return missing;
  }

  async machineCheck(task) {
    const missing = await this.missingOutputs(task);
    return missing.length ? [`File mancanti o vuoti: ${missing.join(', ')}`] : [];
  }

  async fileDump(task) {
    const paths = [...new Set([...task.outputs, ...(task.files ?? [])].map(safeRelPath).filter(Boolean))];
    let budget = 26000;
    const parts = [];
    for (const p of paths) {
      if (budget <= 0) break;
      const size = await this.ws.size(p);
      if (size < 0) {
        parts.push(`=== ${p} ===\n(missing)`);
        continue;
      }
      if (!TEXT_EXT.has(extname(p).toLowerCase())) {
        parts.push(`=== ${p} ===\n(binary file, ${size} bytes — generated media; judge it by the task description and prompt used)`);
        continue;
      }
      const text = await this.ws.read(p, Math.min(9000, budget));
      budget -= text.length;
      parts.push(`=== ${p} ===\n${text}`);
    }
    return parts.join('\n\n');
  }

  async review(task, agent, out) {
    const { pacing } = this.cfg;
    const hasQa = this.team.ofTeam('qa').length > 0;
    const judge = hasQa ? await this.team.acquire('qa', this.data.id, this.abort.signal) : this.ceo;
    const security = task.team === 'dev' || task.outputs.some((p) => /\.(js|mjs|ts|tsx|jsx|py|html?|php|sh|sql)$/i.test(p));
    try {
      this.team.set(judge.id, { state: 'reviewing', target: agent.id, taskId: task.id, runId: this.data.id, text: `${security ? 'Qualità e sicurezza' : 'Controllo'}: "${task.title}"`, verdict: null });
      this.message(agent.id, judge.id, 'review', `Pronto per la revisione: ${task.title}`);
      await this.sleep(pacing.reviewWalkMs);
      const raw = (await this.chatJson(
        { role: 'qa', messages: judgePrompt({ judge, goal: this.data.goal, task, attempt: task.attempts, summary: out.summary, fileDump: await this.fileDump(task), checks: '', security }), maxTokens: 2000, agent: judge, task },
        (o) => o.verdict === 'pass' || o.verdict === 'revise',
      )) ?? { verdict: 'pass', score: null, feedback: '' };
      const feedback = typeof raw.feedback === 'string' ? raw.feedback : Array.isArray(raw.feedback) ? raw.feedback.join('\n') : '';
      const v = { verdict: raw.verdict, score: raw.score ?? null, feedback, judgeId: judge.id, attempt: task.attempts, security, ts: Date.now() };
      task.verdicts.push(v);
      if (typeof raw.lesson === 'string' && raw.lesson.trim()) {
        this.ctx.brain.add({ title: `Lezione · ${task.title}`, text: raw.lesson.trim(), team: task.team, agentId: judge.id, runId: this.data.id, kind: 'lesson', tags: [task.team, 'qa'] });
      }
      this.note(task, judge, 'verdict', v.verdict === 'pass' ? `Approvato (${v.score ?? '–'}/10)` : feedback);
      this.team.set(judge.id, { state: 'verdict', verdict: v.verdict, target: agent.id, text: v.verdict === 'pass' ? `Approvato! ${v.score ?? ''}/10` : 'Da rivedere' });
      this.message(judge.id, agent.id, v.verdict === 'pass' ? 'pass' : 'revise', v.verdict === 'pass' ? `Approvato (${v.score ?? '–'}/10)` : feedback);
      await this.sleep(pacing.verdictMs);
      return v;
    } finally {
      if (hasQa) this.team.release(judge.id);
      else this.team.set(judge.id, { state: 'idle', target: null });
    }
  }

  progressText(team) {
    return this.data.tasks.filter((t) => !team || t.team === team).map((t) => `- ${t.id} [${t.status}] ${t.title}${t.summary ? `: ${t.summary.slice(0, 200)}` : ''}`).join('\n') || '- (nothing yet)';
  }

  async advise(task, agent, question) {
    const lead = this.team.lead(task.team) ?? this.ceo;
    const responder = lead.id === agent.id ? this.ceo : lead;
    this.message(agent.id, responder.id, 'question', question);
    const res = await this.chat({
      role: responder.kind === 'ceo' ? 'ceo' : task.team,
      messages: advisorPrompt({ lead: responder, team: this.cfg.teams[task.team]?.label ?? task.team, goal: this.data.goal, ws: this.wsById(task.wsId), task, from: agent.name, question, progress: this.progressText(task.team) }),
      maxTokens: 800,
      agent: responder,
      task,
    });
    const answer = res.text.trim().slice(0, 1500);
    this.message(responder.id, agent.id, 'answer', answer);
    return `${responder.name} answers: ${answer}`;
  }

  async askUser(task, agent, question) {
    const item = this.addWaiting({ kind: 'question', from: agent.id, taskId: task.id, text: question });
    this.team.set(agent.id, { state: 'asking', text: question });
    this.message(agent.id, 'user', 'ask_user', question);
    const answer = await this.waitAnswer(item, this.cfg.limits.askUserTimeoutMs);
    if (this.abort.signal.aborted) throw this.abort.signal.reason;
    this.team.set(agent.id, { state: 'thinking', text: answer ? 'Ho la risposta, continuo' : 'Nessuna risposta, decido io' });
    return answer?.text ? `The owner answers: ${answer.text}` : 'No answer from the owner in time: make the most reasonable decision yourself and state it in your summary.';
  }

  async rescue(task, agent, feedback) {
    const lead = this.team.lead(task.team) ?? this.ceo;
    this.message(agent.id, lead.id, 'stuck', `Bloccato su "${task.title}" dopo ${task.revisions} revisioni.`);
    const d = (await this.chatJson(
      { role: lead.kind === 'ceo' ? 'ceo' : task.team, messages: rescuePrompt({ lead, goal: this.data.goal, task, feedback }), maxTokens: 1000, agent: lead, task },
      (o) => o.action === 'retry' || o.action === 'skip',
    )) ?? { action: 'retry', guidance: 'Riparti dai criteri di accettazione uno per uno.' };
    this.message(lead.id, agent.id, 'guidance', `${d.action === 'skip' ? 'Saltiamo questo task' : 'Riprova'}: ${d.guidance}`);
    return { action: d.action, guidance: String(d.guidance ?? '') };
  }

  async writeMedia(task, agent, kind, args) {
    const isImage = kind === 'image';
    const fallback = isImage ? `assets/${slugify(args.prompt ?? task.title, 30)}.png` : `audio/${slugify(task.title, 30)}.mp3`;
    let path = safeRelPath(args.path) ?? fallback;
    const ext = extname(path).slice(1).toLowerCase();
    const out = isImage
      ? await this.ctx.media.image({ prompt: String(args.prompt ?? ''), size: String(args.size ?? '1024x1024'), ext }, this.abort.signal)
      : await this.ctx.media.speech({ text: String(args.text ?? ''), voice: args.voice }, this.abort.signal);
    if (isImage && ext === 'svg' && out.ext !== 'svg') path = path.replace(/\.svg$/i, '.png');
    const r = await this.ws.writeBytes(path, out.bytes);
    this.ctx.bus.emit('file', { runId: this.data.id, agentId: agent.id, taskId: task.id, path: r.path, bytes: r.bytes, media: kind });
    return `Generated ${r.path} with ${out.target}${out.demo ? ' (demo generator)' : ''}, ${r.bytes} bytes${r.path !== args.path && args.path ? ` (saved as ${r.path})` : ''}.`;
  }

  async execTool(task, agent, action) {
    const { tool, args } = action;
    const { skills, brain } = this.ctx;
    try {
      switch (tool) {
        case 'list_files':
          return (await this.ws.listText(args.path ?? '.')) || '(empty folder)';
        case 'read_file':
          return await this.ws.read(args.path);
        case 'write_file': {
          if (typeof args.content !== 'string') return 'ERROR: "content" must be a string with the whole file.';
          const r = await this.ws.write(args.path, args.content);
          this.ctx.bus.emit('file', { runId: this.data.id, agentId: agent.id, taskId: task.id, path: r.path, bytes: r.bytes });
          return `Wrote ${r.path} (${r.bytes} bytes).`;
        }
        case 'web_search':
          return await webSearch(args.query, this.abort.signal);
        case 'web_fetch':
          return await webFetch(String(args.url ?? ''), this.abort.signal);
        case 'run_command': {
          if (!this.cfg.limits.allowShell) return 'ERROR: shell commands are disabled on this machine. Verify by reading files instead.';
          const r = await runCommand(String(args.cmd ?? ''), this.ws.root, this.cfg.limits.commandTimeoutMs, this.abort.signal);
          return `exit code ${r.code}\n${r.output}`;
        }
        case 'generate_image':
          return await this.writeMedia(task, agent, 'image', args);
        case 'generate_speech':
          return await this.writeMedia(task, agent, 'speech', args);
        case 'search_skills': {
          const hits = skills.search(String(args.query ?? task.title), 8);
          return hits.length ? hits.map((h) => `- ${h.name} (${h.source}): ${h.description.slice(0, 200)}`).join('\n') : 'No skill matches that query.';
        }
        case 'read_skill':
          return (await skills.read(String(args.name ?? args.id ?? ''))).text;
        case 'remember': {
          const n = brain.add({ title: args.title, text: args.text, tags: args.tags, team: task.team, agentId: agent.id, runId: this.data.id });
          return `Saved in the Brain as "${n.title}".`;
        }
        case 'recall': {
          const hits = brain.search(String(args.query ?? ''), 5, { agentId: agent.id });
          return hits.length ? hits.map((n) => `- ${n.title}: ${n.text.slice(0, 400)}`).join('\n') : 'The Brain has nothing on that yet.';
        }
        case 'ask_lead':
          return await this.advise(task, agent, String(args.question ?? ''));
        case 'ask_user':
          return await this.askUser(task, agent, String(args.question ?? ''));
        default:
          return `ERROR: unknown tool ${tool}`;
      }
    } catch (err) {
      if (this.abort.signal.aborted) throw err;
      return `ERROR: ${err.message}`;
    }
  }

  // ---------- wrap-up ----------

  async synthesize() {
    const ceo = this.ceo;
    this.team.set(ceo.id, { state: 'thinking', runId: this.data.id, text: 'Scrivo il report finale…' });
    const files = await this.ws.listText();
    const res = await this.chat({
      role: 'ceo',
      messages: synthPrompt({ ceo, goal: this.data.goal, planSummary: this.data.planSummary, workstreams: this.data.workstreams, tasks: this.data.tasks, files: files || '(none)' }),
      maxTokens: 3000,
      agent: ceo,
    });
    this.data.report = clip(res.text.trim(), 20000);
    await this.ws.write('REPORT.md', this.data.report);
    this.ctx.brain.add({
      title: `Missione · ${this.data.goal.slice(0, 90)}`,
      text: `${this.data.planSummary}\n${this.data.workstreams.map((w) => `${w.id} ${w.title} (${w.team}): ${w.status}`).join('\n')}`,
      kind: 'run',
      tags: ['missione', ...new Set(this.data.workstreams.map((w) => w.team))],
      agentId: ceo.id,
      runId: this.data.id,
    });
    this.message(ceo.id, '*', 'report', 'Report finale pronto: REPORT.md');
  }
}
