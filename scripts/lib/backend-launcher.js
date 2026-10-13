// H1: a single place that decides how to launch either backend for tests.
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
import { existsSync } from 'node:fs';
import { join } from 'node:path';

const BACKEND_DIR = (root) => join(root, 'backend');
const VENV_PYTHON = (root) => join(BACKEND_DIR(root), '.venv', 'Scripts', 'python.exe');

// { cmd, args, cwd } ready for child_process.spawn.
export function launchCommand(server, root) {
  if (server === 'node') return { cmd: process.execPath, args: ['server/index.js'], cwd: root };
  if (server === 'python') {
    const py = VENV_PYTHON(root);
    if (!existsSync(py)) {
      throw new Error(`${py} not found. Run "uv sync" in backend/ first.`);
    }
    return { cmd: py, args: ['-m', 'backend'], cwd: BACKEND_DIR(root) };
  }
  throw new Error(`Unknown AGENT_WORLD_SERVER="${server}" (expected "node" or "python")`);
}

export function serverKind() {
  return process.env.AGENT_WORLD_SERVER === 'python' ? 'python' : 'node';
}

// Same substring for both backends (H2): scripts waiting for "ready" don't
// need to know which one they launched.
export const READY_MARKER = 'Agent World';
