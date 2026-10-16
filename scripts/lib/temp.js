// Temp folders with an owner, for the tests and the browser checks (spec 03, N7 and N9).
//
// A folder is named agent-world-<tool>-<pid>-XXXXXX in the system temp folder: the pid
// is the node process that made it. On Windows a process killed from outside (taskkill,
// a shell time limit) runs no handler at all, so it cannot clean up; the next tool that
// starts can, because a folder whose owner is dead is an orphan. A folder whose owner is
// alive is never touched: it may be a run in parallel.
//
// The exit handlers (Ctrl+C, Ctrl+Break, the console closed, an error nobody caught) run
// the clean-ups registered with onExit(), then remove the folders made here, then exit.
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const OWNED = /^agent-world-([a-z]+)-(\d+)-[A-Za-z0-9]{6}$/;
// names from before the owner was in them: only the manual sweep removes these
const LEGACY = /^(agent-world-(profile|browser|smoke|flows)-[A-Za-z0-9]{6}|aw-[A-Za-z0-9]{6})$/;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const dirs = new Set();
const cleanups = new Set();

// The owner of a temp folder, from its name; null for a name with no owner in it
// (agent-world-preview, the legacy names).
export function ownerOf(name) {
  const m = name.match(OWNED);
  return m ? { tool: m[1], pid: Number(m[2]) } : null;
}

export function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM'; // there, but not ours to signal
  }
}

// The way a shell time limit or taskkill ends a process: at once, no handler runs
// (spec 03, §1.2). N16: one helper for every script, on every system. taskkill /F on
// Windows (with /T, the whole tree); SIGKILL elsewhere, where a child does not die with
// its parent either: a test server watches its stdin instead (spawnBackend).
export function hardKill(pids, { tree = false } = {}) {
  const list = [].concat(pids);
  if (process.platform === 'win32') {
    spawnSync('taskkill', [...list.flatMap((pid) => ['/PID', String(pid)]), ...(tree ? ['/T'] : []), '/F'], { stdio: 'ignore' });
    return;
  }
  for (const pid of list) {
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      // gone already
    }
  }
}

export function ownedDir(tool) {
  if (!/^[a-z]+$/.test(tool)) throw new Error(`tool name "${tool}": lower-case letters only`);
  installExitHandlers();
  const dir = mkdtempSync(join(tmpdir(), `agent-world-${tool}-${process.pid}-`));
  dirs.add(dir);
  return dir;
}

export function sizeMb(dir) {
  let bytes = 0;
  const walk = (d) => {
    let entries = [];
    try {
      entries = readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = join(d, e.name);
      try {
        if (e.isDirectory()) walk(p);
        else bytes += statSync(p).size;
      } catch {
        // gone meanwhile, or locked
      }
    }
  };
  walk(dir);
  return +(bytes / 1048576).toFixed(1);
}

// The browser, or a virus scanner, holds a folder a moment after its process ends.
export async function removeDir(dir, { tries = 40, wait = 500 } = {}) {
  for (let i = 0; existsSync(dir); i++) {
    try {
      rmSync(dir, { recursive: true, force: true });
    } catch (e) {
      if (i >= tries) return e.code;
      await sleep(wait);
    }
  }
  dirs.delete(dir);
  return null;
}

function removeDirSync(dir) {
  try {
    rmSync(dir, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
    dirs.delete(dir);
  } catch (e) {
    console.error(`note: could not remove ${dir}: ${e.code}`);
  }
}

// Folders whose owner is dead. Browser profiles are left to the browser's sweep
// (scripts/browser/headless.js), which first closes the processes that hold them.
// legacy: also the old names, when inUse(name) says no process names them.
export function orphanDirs({ legacy = false, inUse = () => false, tools = null } = {}) {
  const found = [];
  for (const name of readdirSync(tmpdir())) {
    const owner = ownerOf(name);
    if (owner) {
      if ((tools ? tools.includes(owner.tool) : owner.tool !== 'profile') && !alive(owner.pid)) found.push({ dir: join(tmpdir(), name), ...owner });
    } else if (legacy && LEGACY.test(name) && !inUse(name)) found.push({ dir: join(tmpdir(), name), tool: 'legacy', pid: null });
  }
  return found;
}

export async function sweepDirs(options = {}) {
  const removed = [];
  const failed = [];
  for (const o of orphanDirs(options)) {
    const mb = sizeMb(o.dir);
    if (options.dryRun) {
      removed.push({ ...o, mb });
      continue;
    }
    const code = await removeDir(o.dir, { tries: 6, wait: 250 });
    (code ? failed : removed).push(code ? { ...o, code } : { ...o, mb });
  }
  return { removed, failed };
}

// A clean-up for the exit handlers, run newest first (the browser before the folders).
// Returns a function that takes it back, for when the work ends normally.
export function onExit(fn) {
  installExitHandlers();
  cleanups.add(fn);
  return () => cleanups.delete(fn);
}

let installed = false;
let exiting = false;
function installExitHandlers() {
  if (installed) return;
  installed = true;
  const run = async (code, why, error) => {
    if (error) console.error(error?.stack ?? error);
    if (exiting) return; // a second Ctrl+C does not cut the clean-up short
    exiting = true;
    console.error(`${why}: cleaning up before exit`);
    for (const fn of [...cleanups].reverse()) {
      try {
        await Promise.race([fn(), sleep(10_000)]);
      } catch (e) {
        console.error(`note: a clean-up failed: ${e?.message ?? e}`);
      }
    }
    for (const dir of dirs) removeDirSync(dir);
    process.exit(code);
  };
  // SIGTERM is never delivered on Windows (spec 03, §1.2), elsewhere it is
  for (const signal of ['SIGINT', 'SIGBREAK', 'SIGHUP', 'SIGTERM']) process.on(signal, () => run(130, signal));
  process.on('uncaughtException', (e) => run(1, 'uncaught exception', e));
  process.on('unhandledRejection', (e) => run(1, 'unhandled rejection', e));
}
