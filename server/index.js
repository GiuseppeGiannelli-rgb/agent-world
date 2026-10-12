import { EventEmitter } from 'node:events';
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { dirname, extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Config } from './config.js';
import { loadEnv } from './env.js';
import { Brain } from './engine/brain.js';
import { Media } from './engine/media.js';
import { chatPrompt } from './engine/prompts.js';
import { Run } from './engine/run.js';
import { SkillLibrary } from './engine/skills.js';
import { Team } from './engine/team.js';
import { Workspace } from './engine/tools.js';
import { Router } from './router/index.js';
import { Store } from './store.js';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
loadEnv(join(ROOT, '.env'));

const config = new Config(join(ROOT, 'config'));
const bus = new EventEmitter();
bus.setMaxListeners(0);
// AGENT_WORLD_HOME moves runs, logs and workspaces elsewhere (the tests use it).
const home = process.env.AGENT_WORLD_HOME ? resolve(process.env.AGENT_WORLD_HOME) : ROOT;
const dataDir = join(home, 'data');
const store = new Store(dataDir);
const router = new Router({ config, dataDir, bus });
const team = new Team(bus);
team.load(config.get().staff);

const brain = new Brain(join(dataDir, 'brain.json'), bus);
const skills = new SkillLibrary({ root: ROOT, config, bus });
const media = new Media({ config, bus });
skills.reindex().then((n) => console.log(`Skill Hub    →  ${n} skill indicizzate`));

const ctx = { config, bus, store, router, team, brain, skills, media, workspaceRoot: join(home, 'workspace') };
const chats = new Map(); // agentId -> [{ from, text, ts }]
const live = new Map(); // runId -> Run while it is active
let seq = 0;

// ---------- helpers ----------

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
  '.wasm': 'application/wasm',
};

function send(res, status, body, headers = {}) {
  const isText = typeof body === 'string';
  res.writeHead(status, { 'content-type': isText ? 'text/plain; charset=utf-8' : 'application/json; charset=utf-8', 'cache-control': 'no-store', ...headers });
  res.end(isText ? body : JSON.stringify(body));
}

function serveFile(res, base, rel) {
  const root = resolve(base);
  const full = resolve(root, normalize(decodeURIComponent(rel)).replace(/^([/\\])+/, ''));
  if (full !== root && !full.startsWith(root + sep)) return send(res, 403, 'Forbidden');
  let target = full;
  if (existsSync(target) && statSync(target).isDirectory()) target = join(target, 'index.html');
  if (!existsSync(target)) return send(res, 404, 'Not found');
  res.writeHead(200, { 'content-type': MIME[extname(target).toLowerCase()] ?? 'application/octet-stream', 'cache-control': 'no-cache' });
  createReadStream(target).pipe(res);
}

async function readBody(req, limit = 2_000_000) {
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw Object.assign(new Error('Body too large'), { status: 413 });
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw Object.assign(new Error('Invalid JSON body'), { status: 400 });
  }
}

function publicConfig() {
  const c = config.get();
  return { ceo: c.ceo, teams: c.teams, staff: c.staff, limits: c.limits, pacing: c.pacing, router: c.router, combos: c.combos, providers: c.providers, media: c.media, skills: c.skills };
}

function runList() {
  return store.list().map((r) => ({
    id: r.id,
    goal: r.goal,
    status: r.status,
    mode: r.mode,
    createdAt: r.createdAt,
    finishedAt: r.finishedAt,
    complexity: r.complexity ?? null,
    workstreams: r.workstreams?.length ?? 0,
    tasks: r.tasks.length,
    done: r.tasks.filter((t) => t.status === 'done').length,
  }));
}

function activeRun() {
  return [...live.values()][0] ?? null;
}

function state() {
  const current = activeRun()?.data ?? store.list()[0] ?? null;
  return {
    mode: router.mode(),
    config: publicConfig(),
    agents: team.list(),
    run: current,
    runs: runList(),
    router: router.snapshot(),
    media: media.status(),
    skills: skills.summary(),
    brain: { count: brain.count, recent: brain.list(40) },
  };
}

// ---------- SSE ----------

const clients = new Set();
const FORWARD = ['chat', 'run', 'task', 'workstream', 'subtasks', 'agent', 'agent.spawn', 'agent.despawn', 'message', 'plan', 'file', 'waiting', 'brain', 'skills', 'run.done', 'router.call', 'config'];
for (const type of FORWARD) {
  bus.on(type, (payload) => {
    const frame = `data: ${JSON.stringify({ seq: ++seq, type, payload })}\n\n`;
    for (const res of clients) res.write(frame);
  });
}
setInterval(() => {
  for (const res of clients) res.write(': ping\n\n');
}, 15000).unref();

// ---------- OpenAI-compatible gateway (/v1) ----------

function gatewayAuthorized(req) {
  const key = process.env.AGENT_WORLD_API_KEY;
  if (!key) return true;
  return (req.headers.authorization ?? '') === `Bearer ${key}`;
}

async function gateway(req, res, path) {
  if (!gatewayAuthorized(req)) return send(res, 401, { error: { message: 'Invalid API key' } });
  if (req.method === 'GET' && path === '/v1/models') {
    const c = config.get();
    const data = [
      ...Object.keys(c.combos).map((name) => ({ id: `combo:${name}`, object: 'model', owned_by: 'agent-world' })),
      ...Object.values(c.combos).flatMap((x) => x.models).map((id) => ({ id, object: 'model', owned_by: id.split('/')[0] })),
    ];
    return send(res, 200, { object: 'list', data: [...new Map(data.map((d) => [d.id, d])).values()] });
  }
  if (req.method === 'POST' && path === '/v1/chat/completions') {
    const body = await readBody(req);
    if (!Array.isArray(body.messages)) return send(res, 400, { error: { message: '"messages" is required' } });
    const use = String(body.model ?? `combo:${config.get().router.defaultCombo}`);
    const controller = new AbortController();
    res.on('close', () => controller.abort());
    try {
      const out = await router.chat({
        use,
        messages: body.messages,
        json: body.response_format?.type === 'json_object',
        maxTokens: body.max_tokens ?? body.max_completion_tokens,
        temperature: body.temperature,
        signal: controller.signal,
        meta: { agentId: 'gateway' },
      });
      const id = `chatcmpl-aw-${out.callId.slice(0, 12)}`;
      const created = Math.floor(Date.now() / 1000);
      const usage = { prompt_tokens: out.usage.in, completion_tokens: out.usage.out, total_tokens: out.usage.in + out.usage.out };
      if (body.stream) {
        res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
        const chunk = (delta, finish) => ({ id, object: 'chat.completion.chunk', created, model: out.target, choices: [{ index: 0, delta, finish_reason: finish }] });
        res.write(`data: ${JSON.stringify(chunk({ role: 'assistant', content: out.text }, null))}\n\n`);
        res.write(`data: ${JSON.stringify({ ...chunk({}, 'stop'), usage })}\n\n`);
        res.end('data: [DONE]\n\n');
        return;
      }
      return send(res, 200, {
        id,
        object: 'chat.completion',
        created,
        model: out.target,
        choices: [{ index: 0, message: { role: 'assistant', content: out.text }, finish_reason: 'stop' }],
        usage,
      });
    } catch (err) {
      if (controller.signal.aborted) return;
      return send(res, 502, { error: { message: err.message, type: 'upstream_error' } });
    }
  }
  return send(res, 404, { error: { message: 'Unknown endpoint' } });
}

// ---------- chat with an agent ----------

function describeAgent(a) {
  const c = config.get();
  if (a.kind === 'ceo') return 'the CEO of the company, who plans missions and coordinates every team lead';
  const t = c.teams[a.team];
  if (a.kind === 'lead') return `lead (task manager) of the ${t?.label ?? a.team} team: ${t?.brief ?? ''}`;
  if (a.kind === 'sub') return `a temporary sub-agent of the ${t?.label ?? a.team} team`;
  return `a ${t?.title ?? 'worker'} in the ${t?.label ?? a.team} team: ${t?.brief ?? ''}`;
}

// The owner talks to an agent. During a run the message also steers the work:
// to the CEO it reaches everybody, to a lead the whole team, to a worker only them.
async function talk(agent, text) {
  const history = chats.get(agent.id) ?? [];
  const run = activeRun();
  let context = 'No mission is running right now.';
  if (run) {
    const scope = agent.kind === 'ceo' ? 'all' : agent.kind === 'lead' ? `team:${agent.team}` : `agent:${agent.id}`;
    run.steer(scope, text);
    run.message('user', agent.id, 'chat', text);
    const task = agent.taskId ? run.taskById(agent.taskId) : null;
    context = `Mission: ${run.data.goal}\nStatus: ${run.data.status}\nYour state: ${agent.state}${task ? `\nYour task: ${task.id} ${task.title}` : ''}\nTeam progress:\n${run.progressText(agent.kind === 'ceo' ? null : agent.team)}`;
  }
  let reply;
  try {
    const out = await router.chat({ role: agent.kind === 'ceo' ? 'ceo' : agent.team, messages: chatPrompt({ agent, who: describeAgent(agent), context, history: history.slice(-10), text }), maxTokens: 600, meta: { agentId: agent.id } });
    reply = out.text.trim();
  } catch (err) {
    reply = `(Non riesco a rispondere ora: ${err.message.split('\n')[0]})`;
  }
  history.push({ from: 'user', text, ts: Date.now() }, { from: agent.id, text: reply, ts: Date.now() });
  chats.set(agent.id, history.slice(-60));
  if (run) run.message(agent.id, 'user', 'chat', reply);
  bus.emit('chat', { agentId: agent.id, reply });
  return { reply, steered: Boolean(run) };
}

// ---------- API ----------

async function api(req, res, url) {
  const path = url.pathname;
  const m = path.match(/^\/api\/runs\/([a-z0-9]+)(?:\/(\w+))?$/);

  if (req.method === 'GET' && path === '/api/state') return send(res, 200, state());

  if (req.method === 'GET' && path === '/api/events') {
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
    res.write(`retry: 2000\n\n`);
    clients.add(res);
    req.on('close', () => clients.delete(res));
    return;
  }

  if (req.method === 'GET' && path === '/api/runs') return send(res, 200, runList());

  if (req.method === 'POST' && path === '/api/runs') {
    const body = await readBody(req);
    const goal = String(body.goal ?? '').trim();
    if (goal.length < 4) return send(res, 400, { error: 'Scrivi un obiettivo per la squadra.' });
    if (activeRun()) return send(res, 409, { error: 'La squadra sta già lavorando a un run. Fermalo o aspetta che finisca.' });
    team.load(config.get().staff);
    const run = new Run({ goal: goal.slice(0, 4000), ctx, options: { approvePlan: body.approvePlan } });
    live.set(run.data.id, run);
    run.emitRun(true);
    run.start().finally(() => live.delete(run.data.id));
    return send(res, 201, { id: run.data.id });
  }

  if (m) {
    const [, id, action] = m;
    const run = live.get(id);
    const data = run?.data ?? store.get(id);
    if (!data) return send(res, 404, { error: 'Run non trovato' });
    if (req.method === 'GET' && !action) return send(res, 200, data);
    if (req.method === 'POST' && action === 'answer') {
      if (!run) return send(res, 409, { error: 'Questo run non è attivo' });
      const body = await readBody(req);
      const ok = run.answer(String(body.itemId ?? ''), { text: body.text ?? '', decision: body.decision === 'approve' || body.decision === 'reject' ? body.decision : null });
      return ok ? send(res, 200, { ok: true }) : send(res, 409, { error: 'Questa richiesta non è più aperta' });
    }
    if (req.method === 'POST' && ['pause', 'resume', 'stop'].includes(action)) {
      if (!run) return send(res, 409, { error: 'Questo run non è attivo' });
      run[action]();
      return send(res, 200, { ok: true });
    }
    if (req.method === 'GET' && action === 'files') {
      const ws = new Workspace(data.workspace);
      return send(res, 200, await ws.list('.', 500));
    }
    if (req.method === 'GET' && action === 'file') {
      const ws = new Workspace(data.workspace);
      try {
        return send(res, 200, { path: url.searchParams.get('path'), content: await ws.read(url.searchParams.get('path'), 400_000) });
      } catch (err) {
        return send(res, 404, { error: err.message });
      }
    }
  }

  if (req.method === 'GET' && path === '/api/config') return send(res, 200, publicConfig());

  if (req.method === 'POST' && path === '/api/config') {
    const body = await readBody(req);
    if (body.combos) {
      for (const [name, c] of Object.entries(body.combos)) {
        if (!Array.isArray(c?.models) || c.models.some((x) => typeof x !== 'string' || !x.includes('/'))) {
          return send(res, 400, { error: `Combo "${name}": "models" deve essere una lista di "provider/modello"` });
        }
      }
    }
    config.update(body);
    bus.emit('config', publicConfig());
    return send(res, 200, publicConfig());
  }

  if (req.method === 'GET' && path === '/api/router') return send(res, 200, router.snapshot());

  // ----- Skill Hub -----
  if (req.method === 'GET' && path === '/api/skills') {
    const q = url.searchParams.get('q');
    const list = q ? skills.search(q, 40) : skills.skills.slice(0, 400);
    return send(res, 200, { ...skills.summary(), results: list.map(({ id, name, description, source, rel, score }) => ({ id, name, description, source, rel, score })) });
  }
  if (req.method === 'GET' && path === '/api/skills/read') {
    try {
      const r = await skills.read(url.searchParams.get('id'), 60000);
      return send(res, 200, { name: r.skill.name, source: r.skill.source, path: r.skill.path, content: r.text });
    } catch (err) {
      return send(res, 404, { error: err.message });
    }
  }
  if (req.method === 'POST' && path === '/api/skills/reindex') return send(res, 200, { count: await skills.reindex(), ...skills.summary() });
  if (req.method === 'POST' && path === '/api/skills/repo') {
    const body = await readBody(req);
    try {
      return send(res, 200, await skills.addRepo(body.url));
    } catch (err) {
      return send(res, 400, { error: err.message });
    }
  }

  // ----- Brain -----
  if (req.method === 'GET' && path === '/api/brain') {
    const q = url.searchParams.get('q');
    return send(res, 200, { count: brain.count, notes: q ? brain.search(q, 50, { quiet: true }) : brain.list(200) });
  }
  if (req.method === 'POST' && path === '/api/brain') {
    const body = await readBody(req);
    if (!String(body.text ?? '').trim()) return send(res, 400, { error: 'Scrivi il contenuto della nota' });
    return send(res, 201, brain.add({ title: body.title, text: body.text, tags: body.tags ?? ['utente'], kind: 'user', agentId: 'user' }));
  }

  // ----- talk to an agent -----
  const chatMatch = path.match(/^\/api\/chat\/([\w-]+)$/);
  if (req.method === 'GET' && chatMatch) return send(res, 200, chats.get(chatMatch[1]) ?? []);
  if (req.method === 'POST' && chatMatch) {
    const agent = team.get(chatMatch[1]);
    if (!agent) return send(res, 404, { error: 'Agente non trovato' });
    const body = await readBody(req);
    const text = String(body.text ?? '').trim().slice(0, 2000);
    if (!text) return send(res, 400, { error: 'Messaggio vuoto' });
    return send(res, 200, await talk(agent, text));
  }

  if (req.method === 'GET' && path === '/api/media') return send(res, 200, media.status());

  if (req.method === 'POST' && path === '/api/router/test') {
    const body = await readBody(req);
    try {
      const out = await router.chat({ use: String(body.use ?? 'fast'), messages: [{ role: 'user', content: 'Reply with the single word: pong' }], maxTokens: 20, meta: { agentId: 'test' } });
      return send(res, 200, { ok: true, target: out.target, ms: out.ms, text: out.text.slice(0, 200), demo: out.demo });
    } catch (err) {
      return send(res, 200, { ok: false, error: err.message });
    }
  }

  return send(res, 404, { error: 'Endpoint sconosciuto' });
}

// ---------- server ----------

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  try {
    if (url.pathname.startsWith('/api/')) return await api(req, res, url);
    if (url.pathname.startsWith('/v1/')) return await gateway(req, res, url.pathname);
    if (url.pathname.startsWith('/vendor/three/')) return serveFile(res, join(ROOT, 'node_modules/three/build'), url.pathname.slice('/vendor/three/'.length));
    if (url.pathname.startsWith('/vendor/three-addons/')) return serveFile(res, join(ROOT, 'node_modules/three/examples/jsm'), url.pathname.slice('/vendor/three-addons/'.length));
    const preview = url.pathname.match(/^\/preview\/([a-z0-9]+)(\/.*)?$/);
    if (preview) {
      const data = store.get(preview[1]) ?? live.get(preview[1])?.data;
      if (!data) return send(res, 404, 'Run non trovato');
      if (!preview[2]) return send(res, 302, '', { location: `/preview/${preview[1]}/` });
      return serveFile(res, data.workspace, preview[2]);
    }
    return serveFile(res, join(ROOT, 'public'), url.pathname === '/' ? 'index.html' : url.pathname);
  } catch (err) {
    if (!res.headersSent) send(res, err.status ?? 500, { error: err.message });
    else res.end();
  }
});

const { host, port } = config.get().server;
server.listen(port, host, () => {
  console.log(`Agent World  →  http://${host}:${port}   (mode: ${router.mode()})`);
  console.log(`Gateway      →  http://${host}:${port}/v1/chat/completions`);
});

function shutdown() {
  for (const run of live.values()) run.stop();
  for (const r of store.list()) store.save(r, true);
  process.exit(0);
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
