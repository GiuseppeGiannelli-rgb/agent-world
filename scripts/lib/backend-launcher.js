// H1: a single place that decides how to launch the backend for tests.
//
// P7: the Node server is gone (Spec 04 closed); there is exactly one backend
// now, the FastAPI one in backend/.
//
// Measured on Windows (T1): `uv run python -m backend` adds an extra process
// hop. Node's child.kill('SIGINT') on Windows does not deliver a real signal
// at all (Node emulates it by forcefully terminating the *direct* child only
// -- see Node's own docs on Windows signal emulation); the grandchild
// (uvicorn, spawned by `uv`) is then left orphaned, still listening on its
// port. Launching the venv's own python.exe directly removes that hop: the
// forceful kill then lands on the one process that actually holds the
// socket, so no orphan survives. A real human pressing Ctrl+C in their own
// terminal is unaffected by any of this: Windows delivers a genuine
// CTRL_C_EVENT to the whole console process group, which Python's signal
// handling receives normally.
import { spawn } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const BACKEND_DIR = (root) => join(root, 'backend');
// N16: uv makes .venv/Scripts/python.exe on Windows and .venv/bin/python elsewhere
const VENV_PYTHON = (root) => (process.platform === 'win32' ? join(BACKEND_DIR(root), '.venv', 'Scripts', 'python.exe') : join(BACKEND_DIR(root), '.venv', 'bin', 'python'));

// { cmd, args, cwd } ready for child_process.spawn.
export function launchCommand(root) {
  const py = VENV_PYTHON(root);
  if (!existsSync(py)) {
    throw new Error(`${py} not found. Run "uv sync" in backend/ first.`);
  }
  return { cmd: py, args: ['-m', 'backend'], cwd: BACKEND_DIR(root) };
}

// N16: how every test script starts its server. A script killed from outside (a shell
// time limit, taskkill /F, SIGKILL) runs no handler, and a child does not die with its
// parent on any system: its server kept its port and wrote into a folder the next test
// removes. The server gets a stdin pipe and AGENT_WORLD_EXIT_WITH_PARENT=1 together,
// and stops when the pipe closes: the OS closes it when the script dies. stdout is a
// pipe, for the ready line; stderr is the caller's choice.
export function spawnBackend(root, env, { stderr = 'inherit' } = {}) {
  const { cmd, args, cwd } = launchCommand(root);
  return spawn(cmd, args, { cwd, env: { ...env, AGENT_WORLD_EXIT_WITH_PARENT: '1' }, stdio: ['pipe', 'pipe', stderr] });
}

// Every env var a config file can name as a provider key (keyEnv), whether or
// not it is currently set.
function keyEnvNames(root) {
  const names = new Set();
  const walk = (o) => {
    if (!o || typeof o !== 'object') return;
    for (const [k, v] of Object.entries(o)) {
      if (k === 'keyEnv' && typeof v === 'string') names.add(v);
      else walk(v);
    }
  };
  for (const file of ['default.json', 'local.json']) {
    const path = join(root, 'config', file);
    if (existsSync(path)) walk(JSON.parse(readFileSync(path, 'utf8')));
  }
  return names;
}

// Environment for a DEMO run: every provider key blanked, including the ones
// that exist only in .env (load_env fills keys ABSENT from the environment,
// so merely deleting them from process.env lets .env resurrect them and the
// "demo" run silently goes live -- measured in P7 QA).
// N15: the server gets the caller's temp home (AGENT_WORLD_HOME, required), a
// preferences file inside it instead of the user's config/local.json, and no
// clone of skills.repos at startup: a test server neither reads nor writes the
// user's state.
export function demoEnv(root, overrides = {}) {
  const home = overrides.AGENT_WORLD_HOME;
  if (!home) throw new Error('demoEnv needs AGENT_WORLD_HOME (a temp folder): without it the server would use the user files');
  // AGENT_WORLD_SKILLER=0: no background scouting of GitHub during tests (Spec 05)
  const env = { ...process.env, AGENT_WORLD_SKILLER: '0', AGENT_WORLD_SKILL_REPOS: '0', AGENT_WORLD_LOCAL_CONFIG: join(home, 'local.json'), ...overrides };
  for (const k of Object.keys(env)) if (k.endsWith('_KEY')) env[k] = '';
  for (const k of keyEnvNames(root)) env[k] = '';
  return env;
}

// Substring of the ready line the backend prints on boot: scripts waiting
// for "ready" don't need to know anything else.
export const READY_MARKER = 'Agent World';
