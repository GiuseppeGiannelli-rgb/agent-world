// End-to-end check in demo mode: start the server on a spare port, run one
// goal through plan → loops → reviews → report, and verify the outcome.
// The server's home is a temp folder owned by this process (scripts/lib/temp.js): it
// goes on every way out, and a killed run's folder goes at the next start.
// AW_TEST_FAIL=start|server (only for scripts/temp-test.js): fail on purpose right after
// the server starts, or kill the server then, as a crash would.
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { demoEnv, launchCommand } from './lib/backend-launcher.js';
import { onExit, ownedDir, removeDir, sweepDirs } from './lib/temp.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 4399;
const base = `http://127.0.0.1:${PORT}`;
const goal = process.argv[2] ?? 'Crea il sito completo per il lancio di una pizzeria napoletana a Milano, con immagini e brand';

await sweepDirs();
const home = ownedDir('smoke');
const env = demoEnv(ROOT, { PORT: String(PORT), AGENT_WORLD_FAST: '1', AGENT_WORLD_HOME: home });
const { cmd, args, cwd } = launchCommand(ROOT);
const server = spawn(cmd, args, { cwd, env, stdio: ['ignore', 'pipe', 'inherit'] });
const serverExited = new Promise((resolve) => server.once('exit', resolve));
// the server is stopped and gone before its home is removed
const cleanUp = async () => {
  server.kill();
  await Promise.race([serverExited, new Promise((r) => setTimeout(r, 5000))]);
  await removeDir(home);
};
onExit(cleanUp); // Ctrl+C, or an error nobody caught
const fail = async (msg) => {
  console.error(`FAIL: ${msg}`);
  await cleanUp();
  process.exit(1);
};

let ready = false;
await Promise.race([
  new Promise((resolve) => server.stdout.on('data', (d) => d.toString().includes('Agent World') && resolve())).then(() => (ready = true)),
  serverExited.then(() => !ready && fail('the server exited before it was ready')),
]);
if (process.env.AW_TEST_FAIL === 'start') await fail('AW_TEST_FAIL=start: failing on purpose');
if (process.env.AW_TEST_FAIL === 'server') server.kill();

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
if (!created.id) await fail(`could not start a run: ${JSON.stringify(created)}`);
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

if (run.status !== 'completed') await fail(`run ended as ${run.status}`);
if (!files.some((f) => f.path === 'REPORT.md')) await fail('REPORT.md missing');
if (!run.tasks.some((t) => t.revisions > 0)) console.warn('note: no task went through a revision in this run');
if (!files.some((f) => f.path.endsWith('.png'))) await fail('no generated image');
if (events['agent.spawn'] === 0) console.warn('note: no sub-agent was spawned');
if (events['agent.spawn'] !== events['agent.despawn']) await fail('sub-agents left behind');
if (events.agent === 0 || events.message === 0) await fail('no live events received');
if (!gw.choices) await fail('gateway did not answer');
await cleanUp();
console.log('OK');
process.exit(0);
