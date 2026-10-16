// Spec 03, C1-C3 (N7): the tests leave no temp folder, on every way out. The last
// script of npm test: the ones before it ran normally; this one makes them fail on
// purpose (AW_TEST_FAIL), kills one the way a shell time limit does, and checks what
// is left in the system temp folder each time.
import { spawn } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { alive, hardKill, ownedDir, ownerOf, removeDir, sweepDirs } from './lib/temp.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (name, ok, data = {}) => {
  if (!ok) failures++;
  console.log(`${ok ? 'ok ' : 'FAIL'} ${name}${ok ? '' : `  ${JSON.stringify(data)}`}`);
};

// the test folders in the temp folder now: every agent-world-* but the preview's home,
// and the old aw-* of router-test
const folders = () => new Set(readdirSync(tmpdir()).filter((n) => (n.startsWith('agent-world-') && n !== 'agent-world-preview') || /^aw-/.test(n)));
const added = (before) => [...folders()].filter((n) => !before.has(n));
// a node process with a time limit: past it, killed the way a shell time limit does
function runNode(nodeArgs, env = {}, timeoutMs = 120_000) {
  const child = spawn(process.execPath, nodeArgs, { cwd: ROOT, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
  let out = '';
  child.stdout.on('data', (d) => (out += d));
  child.stderr.on('data', (d) => (out += d));
  return new Promise((ok) => {
    const timer = setTimeout(() => {
      hardKill(child.pid, { tree: true });
      ok({ code: 'timed out', out, pid: child.pid });
    }, timeoutMs);
    child.once('exit', (code) => {
      clearTimeout(timer);
      ok({ code, out, pid: child.pid });
    });
  });
}
const runScript = (script, env = {}, timeoutMs = 120_000, args = []) => runNode([join(HERE, script), ...args], env, timeoutMs);
// N16: whether something answers on the port during the last part of a window after a
// kill. One look right after the kill is not enough: a server still starting does not
// answer yet, and it may well answer a second later (it did, on Linux, at +1.7 s).
async function answersLater(port, windowMs = 5000) {
  const end = Date.now() + windowMs;
  let answered = false;
  while (Date.now() < end) {
    const up = await fetch(`http://127.0.0.1:${port}/api/state`, { signal: AbortSignal.timeout(500) }).then(() => true, () => false);
    if (up && end - Date.now() < 2500) answered = true;
    await sleep(250);
  }
  return answered;
}

// C1: the scripts before this one (npm test runs it last) left nothing. A folder of a
// live owner may be a run in parallel; one without an owner in its name is a leftover.
const leftovers = [...folders()].filter((n) => {
  const owner = ownerOf(n);
  return !owner || !alive(owner.pid);
});
check('C1 the scripts before left no folder', !leftovers.length, { leftovers });

// C1: a failing test cleans up, whether it fails itself or its server dies
for (const script of ['smoke.js', 'flows-test.js']) {
  for (const mode of ['start', 'server']) {
    const before = folders();
    const r = await runScript(script, { AW_TEST_FAIL: mode });
    const left = added(before);
    check(`C1 ${script} failing at "${mode}" cleans up`, r.code === 1 && !left.length, { exit: r.code, left, tail: r.out.trim().split('\n').slice(-2) });
  }
}

// C3 (N16): a test past its time limit is really ended, on every system. Before, the
// kills here called taskkill everywhere: outside Windows it does not exist, spawnSync
// does not throw, and nothing was killed.
{
  const r = await runNode(['-e', 'setInterval(() => {}, 1000)'], {}, 1000);
  let dead = false;
  for (let i = 0; i < 20 && !dead; i++) {
    await sleep(250);
    dead = !alive(r.pid);
  }
  if (!dead) process.kill(r.pid, 'SIGKILL'); // not left behind by a red check
  check('C3 a test past its time limit is ended', r.code === 'timed out' && dead, { code: r.code, dead });
}

// C2, C3: a smoke killed the hard way (taskkill /F, SIGKILL) leaves its folder, named
// with its pid; the next tool that starts (`npm run sweep`, the quickest) removes it.
// It is killed while its server starts; C4 kills one whose server is ready.
// P7: this used to be router-test.js, deleted with the Node server.
async function killedSmoke({ whenReady }) {
  const before = folders();
  const child = spawn(process.execPath, [join(HERE, 'smoke.js')], { cwd: ROOT, stdio: 'ignore' });
  let made = [];
  for (let i = 0; i < 100 && !made.length; i++) {
    await sleep(100);
    made = added(before);
  }
  if (whenReady) {
    const up = () => fetch('http://127.0.0.1:4399/api/state', { signal: AbortSignal.timeout(500) }).then(() => true, () => false);
    for (let i = 0; i < 200 && !(await up()); i++) await sleep(100);
  }
  const exited = new Promise((ok) => (child.exitCode === null && child.signalCode === null ? child.once('exit', ok) : ok()));
  hardKill(child.pid);
  await Promise.race([exited, sleep(5000)]);
  const orphan = made[0];
  const named = Boolean(orphan) && ownerOf(orphan)?.tool === 'smoke' && ownerOf(orphan)?.pid === child.pid;
  const leftByTheKill = Boolean(orphan) && existsSync(join(tmpdir(), orphan));
  // its server must not outlive it: it would hold port 4399 and write into the folder
  const serverAnswers = await answersLater(4399);
  const next = await runScript(join('browser', 'headless.js'), {}, 30_000, ['--sweep']);
  const gone = Boolean(orphan) && !existsSync(join(tmpdir(), orphan));
  if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL'); // not left behind by a red check
  return { folder: orphan ?? null, pid: child.pid, named, leftByTheKill, serverAnswers, nextTestExit: next.code, gone };
}
{
  const r = await killedSmoke({ whenReady: false });
  check('C2 a test folder is named with its owner', r.named, { folder: r.folder, pid: r.pid });
  check('C3 a killed smoke leaves its folder, the next test removes it', r.leftByTheKill && !r.serverAnswers && r.nextTestExit === 0 && r.gone, r);
}
// C4 (N16): killed once its server is ready, the smoke left that server running: it
// had nothing more to write on its stdout, and nothing else tied it to the smoke.
{
  const r = await killedSmoke({ whenReady: true });
  check('C4 a smoke killed with its server ready leaves no server', r.leftByTheKill && !r.serverAnswers && r.nextTestExit === 0 && r.gone, r);
}

// C2: the folder of a live owner (this process) survives a sweep
{
  const mine = ownedDir('temptest');
  const swept = await sweepDirs();
  const kept = existsSync(mine);
  await removeDir(mine);
  check('C2 a live owner is left alone', kept && !swept.removed.some((r) => r.dir === mine), { kept });
}

console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
