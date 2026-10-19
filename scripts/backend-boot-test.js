// T1: the Python backend boots, prints a recognizable "ready" line, answers
// HTTP, and exits cleanly on SIGINT, with no orphaned process left behind
// (measured risk R1: `uv run` as a wrapper orphans its grandchild on
// Windows -- see scripts/lib/backend-launcher.js). No application routes yet.
//
// N19: the server is a test server like the others: it keeps its data in a temp home
// and never touches the checkout (data/, skills/vendor/, config/local.json).
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { demoEnv, READY_MARKER, spawnBackend } from './lib/backend-launcher.js';
import { ownedDir, removeDir } from './lib/temp.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 4398;
const base = `http://127.0.0.1:${PORT}`;

let failed = false;
const fail = (msg) => {
  console.error(`FAIL: ${msg}`);
  failed = true;
};

// what the user keeps next to the code: the folders that exist, the preferences file
const LOCAL_JSON = join(ROOT, 'config', 'local.json');
const checkout = () => ({
  folders: ['data', 'skills/vendor'].filter((d) => existsSync(join(ROOT, d))),
  local: existsSync(LOCAL_JSON) ? { mtime: statSync(LOCAL_JSON).mtimeMs, bytes: readFileSync(LOCAL_JSON, 'utf8') } : null,
});
const before = checkout();
const home = ownedDir('boot');

// demoEnv: every key blanked, no .env, its own preferences file in the temp home
const env = demoEnv(ROOT, { PORT: String(PORT), AGENT_WORLD_HOME: home });
const server = spawnBackend(ROOT, env, { stderr: 'pipe' });
let out = '';
server.stdout.on('data', (d) => (out += d.toString()));
server.stderr.on('data', (d) => (out += d.toString()));
const exited = new Promise((resolve) => server.once('exit', (code, signal) => resolve({ code, signal })));

let ready = false;
await Promise.race([
  new Promise((resolve) => {
    const check = () => {
      if (out.includes(READY_MARKER)) resolve();
    };
    server.stdout.on('data', check);
  }).then(() => (ready = true)),
  exited.then(() => {}),
  new Promise((r) => setTimeout(r, 8000)),
]);

if (!ready) {
  fail(`server did not print "${READY_MARKER}" within 8s. Output so far:\n${out}`);
} else {
  console.log('ready line seen');
  let res;
  let lastErr;
  for (let i = 0; i < 20 && !res; i++) {
    try {
      res = await fetch(base + '/');
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  if (res) console.log(`GET / -> ${res.status}`);
  else fail(`could not reach the server: ${lastErr?.message}`);
  if (res) {
    const st = await fetch(base + '/api/state').then((r) => r.json()).catch(() => null);
    if (st?.mode !== 'demo') fail(`the server is not in demo (mode ${st?.mode}): it saw an API key`);
    if (!existsSync(join(home, 'data', 'runs'))) fail(`the server did not keep its data in its temp home (${home})`);
  }

  const t0 = Date.now();
  server.kill('SIGINT');
  const { signal } = await Promise.race([exited, new Promise((r) => setTimeout(() => r({ signal: 'TIMEOUT' }), 5000))]);
  const ms = Date.now() - t0;
  console.log(`exit after kill: signal=${signal} in ${ms}ms`);
  if (signal === 'TIMEOUT') {
    fail('process did not exit within 5s of kill');
    server.kill();
  }
}

// Orphan check (H6): on Windows, nothing should still be listening on PORT.
await new Promise((r) => setTimeout(r, 300));
try {
  await fetch(base + '/', { signal: AbortSignal.timeout(500) });
  fail(`port ${PORT} is still answering after the server was killed (orphan process)`);
} catch {
  // Connection refused/aborted is the expected outcome: nothing is listening.
}

const after = checkout();
if (JSON.stringify(after.folders) !== JSON.stringify(before.folders)) fail(`the checkout changed: folders ${JSON.stringify(before.folders)} -> ${JSON.stringify(after.folders)}`);
if (JSON.stringify(after.local) !== JSON.stringify(before.local)) fail('the checkout changed: config/local.json was written');
await removeDir(home);

if (failed) {
  console.log(`--- server output ---\n${out}`);
  process.exit(1);
}
console.log('OK');
process.exit(0);
