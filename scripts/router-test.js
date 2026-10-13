// Checks the real provider adapters and the fallback logic against fake
// upstream servers: no network, no keys. The router's data folder is a temp folder
// owned by this process (scripts/lib/temp.js): removed at the end, and by the exit
// handler when an assertion fails.
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createServer } from 'node:http';
import { extractJson } from '../server/engine/json.js';
import { parseAction } from '../server/engine/tasker.js';
import { normalizePlan, normalizeSubtasks } from '../server/engine/run.js';
import { Router } from '../server/router/index.js';
import { ownedDir, removeDir, sweepDirs } from './lib/temp.js';

await sweepDirs();
const dataDir = ownedDir('router');

const seen = [];
const upstream = createServer(async (req, res) => {
  let body = '';
  for await (const c of req) body += c;
  const json = JSON.parse(body || '{}');
  seen.push({ url: req.url, headers: req.headers, body: json });
  const reply = (status, obj) => {
    res.writeHead(status, { 'content-type': 'application/json' });
    res.end(JSON.stringify(obj));
  };
  if (req.url.startsWith('/busy')) return reply(429, { error: 'rate limited' });
  if (req.url.startsWith('/denied')) return reply(401, { error: 'bad key' });
  if (req.url.startsWith('/strict') && json.response_format) return reply(400, { error: 'response_format not supported' });
  if (req.url.endsWith('/messages')) {
    return reply(200, { model: json.model, content: [{ type: 'text', text: '{"ok": true, "via": "anthropic"}' }], usage: { input_tokens: 11, output_tokens: 7 } });
  }
  return reply(200, { model: json.model, choices: [{ message: { content: '<think>scratch</think>```json\n{"ok": true, "via": "openai"}\n```' } }], usage: { prompt_tokens: 5, completion_tokens: 3 } });
});
await new Promise((r) => upstream.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${upstream.address().port}`;

process.env.T_KEY = 'secret';
const value = {
  router: { defaultCombo: 'main', demoFallback: true, cooldownBaseMs: 60000, cooldownMaxMs: 60000, authCooldownMs: 60000, logCalls: false },
  providers: {
    mock: { kind: 'mock', latencyMs: [1, 2] },
    busy: { kind: 'openai', baseUrl: `${base}/busy`, keyEnv: 'T_KEY' },
    denied: { kind: 'openai', baseUrl: `${base}/denied`, keyEnv: 'T_KEY' },
    nokey: { kind: 'openai', baseUrl: `${base}/ok`, keyEnv: 'T_MISSING' },
    strict: { kind: 'openai', baseUrl: `${base}/strict`, keyEnv: 'T_KEY' },
    good: { kind: 'openai', baseUrl: `${base}/ok`, keyEnv: 'T_KEY' },
    claude: { kind: 'anthropic', baseUrl: `${base}/anthropic`, keyEnv: 'T_KEY' },
  },
  combos: {
    main: { strategy: 'fallback', models: ['nokey/m', 'busy/m', 'denied/m', 'good/m1'] },
    strict: { strategy: 'fallback', models: ['strict/m'] },
    claude: { strategy: 'fallback', models: ['claude/claude-sonnet-5-5'] },
    empty: { strategy: 'fallback', models: ['nokey/m'] },
    rr: { strategy: 'round-robin', models: ['good/a', 'good/b'] },
  },
  roles: { builder: { combo: 'main' } },
};
const bus = new EventEmitter();
const router = new Router({ config: { get: () => value }, dataDir, bus });
const messages = [{ role: 'system', content: 'sys' }, { role: 'user', content: 'hi' }, { role: 'user', content: 'again' }];

// 1. fallback: skips the provider with no key, survives 429 and 401, lands on "good"
const r1 = await router.chat({ role: 'builder', messages, json: true });
assert.equal(r1.target, 'good/m1');
assert.deepEqual(extractJson(r1.text), { ok: true, via: 'openai' });
assert.equal(r1.usage.in, 5);
assert.ok(!seen.some((s) => s.url.startsWith('/ok') && s.body.model === 'm'), 'provider without key must be skipped');
const okCall = seen.find((s) => s.url === '/ok/chat/completions');
assert.equal(okCall.headers.authorization, 'Bearer secret');
assert.deepEqual(okCall.body.response_format, { type: 'json_object' });
console.log('ok  fallback skips missing keys, 429 and 401');

// 2. cooldown: the failed targets now go last, so the next call hits "good" first
seen.length = 0;
await router.chat({ role: 'builder', messages });
assert.equal(seen[0].url, '/ok/chat/completions');
console.log('ok  cooling targets are tried last');

// 3. response_format refused with 400 -> retried without it
seen.length = 0;
const r3 = await router.chat({ use: 'strict', messages, json: true });
assert.equal(seen.length, 2);
assert.equal(seen[1].body.response_format, undefined);
assert.ok(r3.text.includes('"ok"'));
console.log('ok  json mode falls back when unsupported');

// 4. anthropic: system split out, consecutive user turns merged, headers set
seen.length = 0;
const r4 = await router.chat({ use: 'claude', messages });
const a = seen[0];
assert.equal(a.url, '/anthropic/messages');
assert.equal(a.headers['x-api-key'], 'secret');
assert.equal(a.headers['anthropic-version'], '2023-06-01');
assert.equal(a.body.system, 'sys');
assert.deepEqual(a.body.messages, [{ role: 'user', content: 'hi\n\nagain' }]);
assert.equal(r4.usage.out, 7);
console.log('ok  anthropic adapter');

// 5. no provider ready -> demo fallback
const r5 = await router.chat({ use: 'empty', messages: [{ role: 'system', content: '[[role:advisor]]' }, { role: 'user', content: 'q' }] });
assert.equal(r5.provider, 'mock');
assert.equal(r5.demo, true);
console.log('ok  demo fallback when nothing is configured');

// 6. round robin alternates
const t1 = (await router.chat({ use: 'rr', messages })).target;
const t2 = (await router.chat({ use: 'rr', messages })).target;
assert.notEqual(t1, t2);
console.log('ok  round-robin rotates');

// 7. messy model output still parses
assert.deepEqual(parseAction('Sure! {"thought":"x","tool":"write_file","args":{"path":"a.md","content":"line1\nline2"}} done'), { thought: 'x', tool: 'write_file', args: { path: 'a.md', content: 'line1\nline2' } });
assert.deepEqual(extractJson('{"a": [1,2,],}'), { a: [1, 2] });
assert.equal(parseAction('{"tool":"rm_rf","args":{}}'), null);
console.log('ok  JSON repair and tool validation');

// 8. plan normalisation: unknown teams mapped, cycles broken, unsafe paths dropped
const cfg = { teams: { research: { kind: 'work', lead: {} }, dev: { kind: 'work', lead: {} }, content: { kind: 'work', lead: {} }, qa: { kind: 'service', lead: {} } }, limits: { maxWorkstreams: 8, maxSubtasks: 5 } };
const plan = normalizePlan({ complexity: 'complex', summary: 's', workstreams: [
  { id: 'a', title: 'A', team: 'developer', deliverables: ['../evil.txt', 'ok/file.md', 'C:/x'], dependsOn: ['b'] },
  { id: 'b', title: 'B', team: 'copywriter', dependsOn: ['a'] },
  { id: 'c', title: 'C', team: 'qa', dependsOn: ['a', 'zzz'] },
] }, cfg);
assert.equal(plan.complexity, 'complex');
assert.equal(plan.workstreams[0].team, 'dev');
assert.equal(plan.workstreams[1].team, 'content');
assert.equal(plan.workstreams[2].team, 'dev', 'service teams cannot own workstreams');
assert.deepEqual(plan.workstreams[0].deliverables, ['ok/file.md']);
const ids = new Map(plan.workstreams.map((t) => [t.id, t]));
const visiting = new Set();
const acyclic = (id) => {
  if (visiting.has(id)) return false;
  visiting.add(id);
  const ok = ids.get(id).dependsOn.every(acyclic);
  visiting.delete(id);
  return ok;
};
assert.ok(plan.workstreams.every((t) => acyclic(t.id)));
const subs = normalizeSubtasks({ subtasks: [{ id: 'x', title: 'X', outputs: ['a.md'] }, { id: 'y', title: 'Y', dependsOn: ['x'] }] }, { id: 'w1', team: 'dev', deliverables: ['a.md', 'b.md'] }, cfg);
assert.deepEqual(subs.map((t) => t.id), ['w1.1', 'w1.2']);
assert.deepEqual(subs[1].dependsOn, ['w1.1']);
assert.ok(subs[1].outputs.includes('b.md'), 'orphan deliverables go to the last subtask');
console.log('ok  plan and subtask normalisation');

// 9. skill search ranks by relevance
const { Bm25 } = await import('../server/engine/search.js');
const idx = new Bm25();
idx.add('img', [{ text: 'image prompting', weight: 4 }, { text: 'write prompts for image generation models' }]);
idx.add('sec', [{ text: 'security review', weight: 4 }, { text: 'find XSS and injection in web code' }]);
assert.equal(idx.search('generate a hero image')[0].id, 'img');
assert.equal(idx.search('controlla XSS injection')[0].id, 'sec');
console.log('ok  BM25 search');

// 10. demo media are real files
const { demoPng, demoWav } = await import('../server/engine/media.js');
const png = demoPng('test', 64);
assert.deepEqual([...png.subarray(1, 4)], [80, 78, 71]);
assert.equal(demoWav('x').subarray(0, 4).toString(), 'RIFF');
console.log('ok  demo PNG and WAV');

// 11. default skill repos: a clone already there is kept, a half clone is never indexed
{
  const { mkdirSync, readFileSync, writeFileSync } = await import('node:fs');
  const { join } = await import('node:path');
  const { SkillLibrary } = await import('../server/engine/skills.js');
  const skillMd = (dir, name) => {
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, 'SKILL.md'), `---\nname: ${name}\ndescription: ${name} test skill\n---\n# ${name}\n`);
  };
  const root = join(dataDir, 'skill-root');
  skillMd(join(root, 'skills', 'vendor', 'acme-present', 'tool'), 'present-skill');
  skillMd(join(root, 'skills', 'vendor', '.incoming', 'acme-half', 'tool'), 'half-skill');
  const config = { get: () => ({ skills: { sources: ['skills'], repos: ['https://github.com/acme/present', 'not a github url'] } }) };
  const lib = new SkillLibrary({ root, config, bus: new EventEmitter() });
  assert.equal(lib.repo('https://github.com/vercel-labs/skills.git/')?.dir, join(root, 'skills', 'vendor', 'vercel-labs-skills'));
  assert.equal(lib.repo('https://gitlab.com/acme/present'), null);
  const warn = console.warn;
  const warnings = [];
  console.warn = (msg) => warnings.push(msg);
  try {
    assert.deepEqual(await lib.ensureRepos(), [], 'nothing to clone: the repo is there, the bad url is skipped');
  } finally {
    console.warn = warn;
  }
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /not a github url/);
  await lib.reindex();
  assert.deepEqual(lib.skills.map((s) => s.name), ['present-skill'], 'a clone in .incoming is not installed yet');
  const shipped = JSON.parse(readFileSync(new URL('../config/default.json', import.meta.url), 'utf8')).skills.repos;
  assert.ok(shipped.length > 0 && shipped.every((u) => lib.repo(u)), 'every default repo is a GitHub url');
}
console.log('ok  default skill repos');

upstream.close();
await removeDir(dataDir);
console.log('ALL OK');
