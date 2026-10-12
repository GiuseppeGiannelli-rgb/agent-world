// End-to-end check in demo mode: start the server on a spare port, run one
// goal through plan → loops → reviews → report, and verify the outcome.
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 4399;
const base = `http://127.0.0.1:${PORT}`;
const goal = process.argv[2] ?? 'Crea il sito completo per il lancio di una pizzeria napoletana a Milano, con immagini e brand';

const home = mkdtempSync(join(tmpdir(), 'agent-world-smoke-'));
const env = { ...process.env, PORT: String(PORT), AGENT_WORLD_FAST: '1', AGENT_WORLD_HOME: home };
for (const k of Object.keys(env)) if (k.endsWith('_API_KEY')) delete env[k];
const server = spawn(process.execPath, ['server/index.js'], { cwd: ROOT, env, stdio: ['ignore', 'pipe', 'inherit'] });
const fail = (msg) => {
  console.error(`FAIL: ${msg}`);
  server.kill();
  process.exit(1);
};

await new Promise((resolve) => server.stdout.on('data', (d) => d.toString().includes('Agent World') && resolve()));

const events = { agent: 0, message: 0, task: 0, plan: 0, file: 0, subtasks: 0, 'agent.spawn': 0, 'agent.despawn': 0, brain: 0 };
const sse = await fetch(`${base}/api/events`);
(async () => {
  const reader = sse.body.getReader();
  let buf = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += new TextDecoder().decode(value);
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (!frame.startsWith('data: ')) continue;
      const { type } = JSON.parse(frame.slice(6));
      if (type in events) events[type] += 1;
    }
  }
})().catch(() => {});

const created = await fetch(`${base}/api/runs`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ goal }) }).then((r) => r.json());
if (!created.id) fail(`could not start a run: ${JSON.stringify(created)}`);
console.log(`run ${created.id} started`);

let run;
const deadline = Date.now() + 120_000;
while (Date.now() < deadline) {
  await new Promise((r) => setTimeout(r, 500));
  run = await fetch(`${base}/api/runs/${created.id}`).then((r) => r.json());
  if (['completed', 'completed_with_failures', 'failed', 'stopped'].includes(run.status)) break;
}

const files = await fetch(`${base}/api/runs/${created.id}/files`).then((r) => r.json());
const gw = await fetch(`${base}/v1/chat/completions`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ model: 'combo:fast', messages: [{ role: 'user', content: 'ping' }] }) }).then((r) => r.json());
const models = await fetch(`${base}/v1/models`).then((r) => r.json());

console.log(`status: ${run.status}${run.error ? ` (${run.error})` : ""} · complexity: ${run.complexity}`);
for (const w of run.workstreams) console.log(`  ${w.id} ${w.status.padEnd(8)} ${w.team.padEnd(9)} ${w.title}`);
for (const t of run.tasks) console.log(`    ${t.id.padEnd(5)} ${t.status.padEnd(8)} ${String(t.agentId).padEnd(14)} att=${t.attempts} rev=${t.revisions}${t.escalated ? " ESC" : ""} skills=[${t.skills.map((x) => x.name).join(", ")}] ${t.title}`);
console.log(`files: ${files.map((f) => f.path).join(', ')}`);
console.log(`events: ${JSON.stringify(events)}`);
console.log(`usage: ${JSON.stringify(run.usage)}`);
console.log(`gateway: ${gw.model} → ${String(gw.choices?.[0]?.message?.content).slice(0, 60)}`);
console.log(`models: ${models.data.length}`);

server.kill();
if (run.status !== 'completed') fail(`run ended as ${run.status}`);
if (!files.some((f) => f.path === 'REPORT.md')) fail('REPORT.md missing');
if (!run.tasks.some((t) => t.revisions > 0)) console.warn('note: no task went through a revision in this run');
if (!files.some((f) => f.path.endsWith('.png'))) fail('no generated image');
if (events['agent.spawn'] === 0) console.warn('note: no sub-agent was spawned');
if (events['agent.spawn'] !== events['agent.despawn']) fail('sub-agents left behind');
if (events.agent === 0 || events.message === 0) fail('no live events received');
if (!gw.choices) fail('gateway did not answer');
console.log('OK');
process.exit(0);
