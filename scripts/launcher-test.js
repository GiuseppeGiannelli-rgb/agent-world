// N15: the servers the test scripts start (smoke, flows, browser, screenshots) run on
// the repo's own config/, so a preference saved through them landed in the user's
// config/local.json, and the user's saved preferences changed what they tested.
// demoEnv() now gives each of them a preferences file inside its owned temp home,
// and no clone of skills.repos at startup. Checked on the environment and on a real
// server: a preference saved through it must leave config/local.json untouched.
import assert from 'node:assert/strict';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { demoEnv, launchCommand, READY_MARKER, spawnBackend } from './lib/backend-launcher.js';
import { onExit, ownedDir, removeDir, sweepDirs } from './lib/temp.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const LOCAL_JSON = join(ROOT, 'config', 'local.json');
const PORT = 4393;
const TIED_PORT = 4392;
let failures = 0;
const check = async (name, fn) => {
  try {
    await fn();
    console.log(`ok   ${name}`);
  } catch (err) {
    failures++;
    console.log(`FAIL ${name}\n     ${String(err.message).split('\n').join('\n     ')}`);
  }
};
// what a write would change: the bytes, and the time even when the bytes are the same
const userFile = () => (existsSync(LOCAL_JSON) ? { mtime: statSync(LOCAL_JSON).mtimeMs, bytes: readFileSync(LOCAL_JSON, 'utf8') } : null);

await sweepDirs();
const home = ownedDir('launcher');

await check('demoEnv puts the preferences in the temp home and turns the repo clone off', () => {
  const env = demoEnv(ROOT, { AGENT_WORLD_HOME: home });
  assert.equal(env.AGENT_WORLD_LOCAL_CONFIG, join(home, 'local.json'));
  assert.equal(env.AGENT_WORLD_SKILL_REPOS, '0');
  assert.equal(env.AGENT_WORLD_SKILLER, '0');
  assert.equal(env.AGENT_WORLD_DISCOVER, '0'); // spec 08: no /models asked by a test server
});

await check('an explicit AGENT_WORLD_LOCAL_CONFIG wins', () => {
  const env = demoEnv(ROOT, { AGENT_WORLD_HOME: home, AGENT_WORLD_LOCAL_CONFIG: join(home, 'mine.json') });
  assert.equal(env.AGENT_WORLD_LOCAL_CONFIG, join(home, 'mine.json'));
});

await check('demoEnv without a temp home is refused: it would use the user files', () => {
  assert.throws(() => demoEnv(ROOT, {}), /AGENT_WORLD_HOME/);
});

// N16: the venv's own python of this system. uv makes .venv/Scripts/python.exe on
// Windows and .venv/bin/python elsewhere; only the first was looked for, so outside
// Windows npm test did not start at all.
await check('the launcher runs the venv python of this system', () => {
  const want = process.platform === 'win32' ? join(ROOT, 'backend', '.venv', 'Scripts', 'python.exe') : join(ROOT, 'backend', '.venv', 'bin', 'python');
  assert.equal(launchCommand(ROOT).cmd, want);
});

// N16: a test server ends with its script. spawnBackend() gives it a stdin pipe and
// AGENT_WORLD_EXIT_WITH_PARENT=1: when the script dies, on any system and however it
// is killed, the OS closes the pipe and the server stops instead of keeping its port.
await check('spawnBackend ties the server to its script: closing its stdin stops it', async () => {
  const tiedHome = ownedDir('launcher');
  const s = spawnBackend(ROOT, demoEnv(ROOT, { PORT: String(TIED_PORT), AGENT_WORLD_FAST: '1', AGENT_WORLD_HOME: tiedHome }));
  const gone = new Promise((r) => s.once('exit', (code) => r(code)));
  try {
    await Promise.race([
      new Promise((r) => s.stdout.on('data', (d) => d.toString().includes(READY_MARKER) && r())),
      gone.then((code) => {
        throw new Error(`the server exited (${code}) before it was ready`);
      }),
    ]);
    s.stdin.end();
    const code = await Promise.race([gone, new Promise((r) => setTimeout(() => r('still running after 15 s'), 15_000))]);
    assert.equal(code, 0);
  } finally {
    s.kill();
    await Promise.race([gone, new Promise((r) => setTimeout(r, 5000))]);
    await removeDir(tiedHome);
  }
});

// a real server, as smoke.js and the others start it
const before = userFile();
let server = null;
let exited = Promise.resolve();
const cleanUp = async () => {
  server?.kill();
  await Promise.race([exited, new Promise((r) => setTimeout(r, 5000))]);
  await removeDir(home);
};
onExit(cleanUp);
await check('a preference saved through a test server stays in its temp home', async () => {
  server = spawnBackend(ROOT, demoEnv(ROOT, { PORT: String(PORT), AGENT_WORLD_FAST: '1', AGENT_WORLD_HOME: home }));
  exited = new Promise((r) => server.once('exit', r));
  await Promise.race([
    new Promise((r) => server.stdout.on('data', (d) => d.toString().includes(READY_MARKER) && r())),
    exited.then(() => {
      throw new Error('the server exited before it was ready');
    }),
  ]);
  const res = await fetch(`http://127.0.0.1:${PORT}/api/config`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ limits: { maxParallel: 7 } }) });
  assert.equal(res.status, 200);
  assert.deepEqual(userFile(), before, 'config/local.json was written');
  assert.equal(JSON.parse(readFileSync(join(home, 'local.json'), 'utf8')).limits.maxParallel, 7);
});

await cleanUp();
console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
