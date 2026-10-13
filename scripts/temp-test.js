// Spec 03, C1-C3 (N7): the tests leave no temp folder, on every way out. The last
// script of npm test: the ones before it ran normally; this one makes them fail on
// purpose (AW_TEST_FAIL), kills one the way a shell time limit does, and checks what
// is left in the system temp folder each time.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { alive, ownedDir, ownerOf, removeDir, sweepDirs } from './lib/temp.js';

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
function runScript(script, env = {}, timeoutMs = 120_000) {
  const child = spawn(process.execPath, [join(HERE, script)], { cwd: ROOT, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
  let out = '';
  child.stdout.on('data', (d) => (out += d));
  child.stderr.on('data', (d) => (out += d));
  return new Promise((ok) => {
    const timer = setTimeout(() => {
      spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
      ok({ code: 'timed out', out });
    }, timeoutMs);
    child.once('exit', (code) => {
      clearTimeout(timer);
      ok({ code, out });
    });
  });
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

// C2, C3: a smoke killed with taskkill /F leaves its folder, named with its pid; the
// next test that starts (router-test, the quickest) removes it
{
  const before = folders();
  const child = spawn(process.execPath, [join(HERE, 'smoke.js')], { cwd: ROOT, stdio: 'ignore' });
  let made = [];
  for (let i = 0; i < 100 && !made.length; i++) {
    await sleep(100);
    made = added(before);
  }
  spawnSync('taskkill', ['/PID', String(child.pid), '/F'], { stdio: 'ignore' });
  await new Promise((ok) => (child.exitCode === null ? child.once('exit', ok) : ok()));
  await sleep(500);
  const orphan = made[0];
  const named = Boolean(orphan) && ownerOf(orphan)?.tool === 'smoke' && ownerOf(orphan)?.pid === child.pid;
  const leftByTheKill = Boolean(orphan) && existsSync(join(tmpdir(), orphan));
  // its server must not outlive it: it would hold port 4399 and the folder
  const serverAnswers = await fetch('http://127.0.0.1:4399/api/state', { signal: AbortSignal.timeout(1000) }).then(() => true, () => false);
  const next = await runScript('router-test.js');
  const gone = Boolean(orphan) && !existsSync(join(tmpdir(), orphan));
  check('C2 a test folder is named with its owner', named, { folder: orphan ?? null, pid: child.pid });
  check('C3 a killed smoke leaves its folder, the next test removes it', leftByTheKill && !serverAnswers && next.code === 0 && gone, { folder: orphan ?? null, leftByTheKill, serverAnswers, nextTestExit: next.code, gone });
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
