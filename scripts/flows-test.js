// Human-in-the-loop flows on a demo server: plan approval, rejection,
// pause/resume/stop, a second run refused while busy, chat steering.
// The server's home is a temp folder owned by this process (scripts/lib/temp.js): it
// goes on every way out, and a killed run's folder goes at the next start.
// AW_TEST_FAIL=start|server (only for scripts/temp-test.js): fail on purpose right after
// the server starts, or kill the server then, as a crash would.
import assert from 'node:assert/strict';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { demoEnv, spawnBackend } from './lib/backend-launcher.js';
import { onExit, ownedDir, removeDir, sweepDirs } from './lib/temp.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 4398;
const base = `http://127.0.0.1:${PORT}`;
await sweepDirs();
const home = ownedDir('flows');
const env = demoEnv(ROOT, { PORT: String(PORT), AGENT_WORLD_FAST: '1', AGENT_WORLD_HOME: home });
const server = spawnBackend(ROOT, env);
const serverExited = new Promise((resolve) => server.once('exit', resolve));
// the server is stopped and gone before its home is removed
const cleanUp = async () => {
  server.kill();
  await Promise.race([serverExited, new Promise((r) => setTimeout(r, 5000))]);
  await removeDir(home);
};
onExit(cleanUp); // Ctrl+C, or an error nobody caught

const j = (p, body) => fetch(base + p, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {}).then((r) => r.json());
const until = async (fn, ms = 60000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = await fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error('timed out');
};
const finished = (s) => ['completed', 'completed_with_failures', 'failed', 'stopped'].includes(s);

try {
  await Promise.race([
    new Promise((resolve) => server.stdout.on('data', (d) => d.toString().includes('Agent World') && resolve())),
    serverExited.then(() => {
      throw new Error('the server exited before it was ready');
    }),
  ]);
  if (process.env.AW_TEST_FAIL === 'start') throw new Error('AW_TEST_FAIL=start: failing on purpose');
  if (process.env.AW_TEST_FAIL === 'server') server.kill();

  // 1. approval: the run waits, then goes on after "approve"
  const a = await j('/api/runs', { goal: 'Una landing page per una libreria indipendente', approvePlan: true });
  const item = await until(async () => (await j(`/api/runs/${a.id}`)).waiting?.find((w) => w.kind === 'plan' && w.status === 'open'));
  assert.equal((await j(`/api/runs/${a.id}`)).status, 'awaiting_approval');
  const busy = await j('/api/runs', { goal: 'un altro run' });
  assert.match(busy.error, /già lavorando/);
  const chat = await j('/api/chat/ada', { text: 'Mi raccomando, testi brevi' });
  assert.ok(chat.reply && chat.steered);
  assert.ok((await j(`/api/runs/${a.id}/answer`, { itemId: item.id, decision: 'approve', text: 'Ok, colori caldi' })).ok);
  const doneA = await until(async () => {
    const r = await j(`/api/runs/${a.id}`);
    return finished(r.status) && r;
  });
  assert.equal(doneA.status, 'completed');
  console.log('ok  plan approval, busy refusal, chat steering');

  // 2. rejection stops the run before any work
  // spec 06: the language is explicit, so the run's messages do not depend on config/local.json
  const b = await j('/api/runs', { goal: 'Una ricerca sul compostaggio', approvePlan: true, language: 'en' });
  const itemB = await until(async () => (await j(`/api/runs/${b.id}`)).waiting?.find((w) => w.status === 'open'));
  await j(`/api/runs/${b.id}/answer`, { itemId: itemB.id, decision: 'reject', text: 'non ora' });
  const doneB = await until(async () => {
    const r = await j(`/api/runs/${b.id}`);
    return finished(r.status) && r;
  });
  assert.equal(doneB.status, 'stopped');
  assert.equal(doneB.tasks.length, 0);
  assert.match(doneB.error, /Plan rejected/);
  console.log('ok  plan rejection');

  // 3. pause / resume / stop
  const c = await j('/api/runs', { goal: 'Il sito completo per il lancio di una gelateria, con immagini e brand' });
  await until(async () => (await j(`/api/runs/${c.id}`)).tasks.some((t) => t.status === 'working'));
  await j(`/api/runs/${c.id}/pause`, {});
  await new Promise((r) => setTimeout(r, 600));
  const steps = (r) => r.tasks.reduce((n, t) => n + t.history.length, 0);
  const p1 = steps(await j(`/api/runs/${c.id}`));
  await new Promise((r) => setTimeout(r, 800));
  const p2 = steps(await j(`/api/runs/${c.id}`));
  assert.ok(p2 - p1 <= 1, 'no new work while paused');
  await j(`/api/runs/${c.id}/resume`, {});
  await until(async () => steps(await j(`/api/runs/${c.id}`)) > p2);
  await j(`/api/runs/${c.id}/stop`, {});
  const doneC = await until(async () => {
    const r = await j(`/api/runs/${c.id}`);
    return finished(r.status) && r;
  });
  assert.equal(doneC.status, 'stopped');
  const st = await j('/api/state');
  const busyNow = st.agents.filter((x) => x.busy);
  assert.equal(busyNow.length, 0, `everyone released (busy: ${busyNow.map((x) => `${x.id}:${x.kind}:${x.team}:${x.state}:run=${x.runId}`).join(', ')})`);
  const subsLeft = st.agents.filter((x) => x.kind === 'sub');
  assert.equal(subsLeft.length, 0, `no sub-agent left (${subsLeft.map((x) => x.id).join(', ')})`);
  console.log('ok  pause, resume, stop');
  console.log('ALL OK');
} catch (err) {
  console.error(`FAIL: ${err.stack ?? err.message}`);
  process.exitCode = 1;
} finally {
  await cleanUp();
}
