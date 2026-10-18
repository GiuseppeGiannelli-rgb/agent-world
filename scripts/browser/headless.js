// The one place that starts and stops a headless Edge or Chrome for the checks (spec 03,
// N9): the runner and every probe go through launch() and close(). Node 22+ (global
// WebSocket). Not a page script: browser-test.js does not inject it.
//
// - launch() first sweeps the orphans of tools that were killed, then starts the browser
//   with a profile folder owned by this process (scripts/lib/temp.js);
// - close() asks the browser to close over DevTools, kills its tree only if it still
//   answers, waits for its processes to go and removes the profile;
// - Ctrl+C, Ctrl+Break, the console closed or an error nobody caught close it too.
//   A process killed from outside runs no handler on Windows: the next launch() or the
//   manual sweep cleans up after it.
//
//   node scripts/browser/headless.js --sweep [--legacy] [--dry-run]     (npm run sweep)
//     --legacy   also the folders named before the owner was in the name, if no browser
//                process uses them; --dry-run   only list what would go
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { alive, hardKill, onExit, ownedDir, ownerOf, removeDir, sizeMb, sweepDirs } from '../lib/temp.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export function findBrowser() {
  const candidates = [
    process.env.BROWSER,
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/microsoft-edge',
  ];
  return candidates.find((p) => p && existsSync(p));
}

// ---------- DevTools protocol ----------

export class Cdp {
  static async open(url) {
    const ws = new WebSocket(url);
    await new Promise((ok, fail) => {
      ws.onopen = ok;
      ws.onerror = () => fail(new Error(`cannot reach ${url}`));
    });
    return new Cdp(ws);
  }

  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      const p = m.id && this.pending.get(m.id);
      if (!p) return;
      this.pending.delete(m.id);
      if (m.error) p.fail(new Error(`${p.method}: ${m.error.message}`));
      else p.ok(m.result);
    };
  }

  send(method, params = {}) {
    return new Promise((ok, fail) => {
      const id = ++this.seq;
      this.pending.set(id, { ok, fail, method });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
  }
}

// ---------- processes ----------

// a profile folder in a command line: agent-world-profile-<pid>-XXXXXX, or the
// name used before spec 03, without the pid
const PROFILE = /agent-world-profile-(?:\d+-)?[A-Za-z0-9]{6}/;

// Browser processes of any run of these checks, with the profile their command line
// names; main is the browser process itself (the others have a --type=).
export function profileProcesses() {
  const r =
    process.platform === 'win32'
      ? spawnSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', "Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'msedge.exe', 'chrome.exe' } | ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.CommandLine }"], { encoding: 'utf8' })
      : spawnSync('ps', ['-eo', 'pid=,args='], { encoding: 'utf8' });
  return (r.stdout ?? '')
    .split(/\r?\n/)
    .map((l) => l.trim().match(/^(\d+)\s+(.*)$/))
    .filter((m) => m && PROFILE.test(m[2]))
    .map(([, pid, cmd]) => ({ pid: Number(pid), profile: cmd.match(PROFILE)[0], main: !/--type=/.test(cmd) }));
}

// One process or several, each with its tree: one taskkill call on Windows.
export const kill = (pids) => hardKill(pids, { tree: true });

// After the close: this run's processes get a few seconds to exit. Those of another run
// (an earlier one, or one in parallel on another --port) are only reported: failing on
// them would make two parallel runs fail each other.
export async function leftovers(profile) {
  const mine = basename(profile);
  for (const end = Date.now() + 5000; ; await sleep(250)) {
    const all = profileProcesses();
    const left = all.filter((p) => p.profile === mine);
    if (!left.length || Date.now() > end) return { left, others: all.filter((p) => p.profile !== mine) };
  }
}

// ---------- the sweep ----------

// Closes the browser processes and removes the folders of tools whose owner is dead.
// Never a process without agent-world-profile- in its command line, never a profile
// whose owner is alive (a run in parallel), never a process naming an old profile
// (its owner is unknown); with legacy, the old folders that no process names.
export async function sweep({ legacy = false, dryRun = false } = {}) {
  const t0 = Date.now();
  const orphan = (name) => {
    const owner = ownerOf(name);
    return Boolean(owner) && !alive(owner.pid);
  };
  const procs = profileProcesses();
  const profiles = new Set(procs.filter((p) => orphan(p.profile)).map((p) => p.profile));
  for (const name of readdirSync(tmpdir())) if (ownerOf(name)?.tool === 'profile' && orphan(name)) profiles.add(name);
  const killed = procs.filter((p) => profiles.has(p.profile));
  // one taskkill for all of them, from the one look-up: a second look-up after the kill
  // would cost about a second (H6); the removal of the profile below retries while the
  // last processes exit, and holds them to account if they do not
  if (!dryRun && killed.length) kill(killed.map((p) => p.pid));
  const removed = [];
  const failed = [];
  for (const name of profiles) {
    const dir = join(tmpdir(), name);
    if (!existsSync(dir)) continue;
    const mb = sizeMb(dir);
    const code = dryRun ? null : await removeDir(dir, { tries: 10, wait: 300 });
    (code ? failed : removed).push(code ? { dir, code } : { dir, mb });
  }
  const inUse = (name) => procs.some((p) => p.profile === name);
  const others = await sweepDirs({ legacy, dryRun, inUse });
  removed.push(...others.removed);
  failed.push(...others.failed);
  return { killed: killed.map(({ pid, profile }) => ({ pid, profile })), removed, failed, ms: Date.now() - t0, dryRun };
}

export function describeSweep(s) {
  const mb = s.removed.reduce((n, r) => n + (r.mb ?? 0), 0);
  const lines = [`sweep${s.dryRun ? ' (dry run)' : ''}: ${s.killed.length} browser processes closed, ${s.removed.length} folders removed (${mb.toFixed(1)} MB), ${s.failed.length} failed, in ${(s.ms / 1000).toFixed(1)} s`];
  for (const p of s.killed) lines.push(`  closed ${p.pid} (${p.profile})`);
  for (const r of s.removed) lines.push(`  removed ${r.dir} (${r.mb} MB)`);
  for (const f of s.failed) lines.push(`  could not remove ${f.dir}: ${f.code}`);
  return lines.join('\n');
}

// ---------- the browser ----------

// Starts the browser; connect() waits for its DevTools endpoint and returns the page.
export async function launch() {
  const swept = await sweep();
  if (swept.killed.length || swept.removed.length || swept.failed.length) console.log(describeSweep(swept));
  const exe = findBrowser();
  if (!exe) throw new Error('no Edge or Chrome found: set BROWSER to its path');
  const profile = ownedDir('profile');
  const proc = spawn(exe, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-breakpad', '--disable-crash-reporter', '--mute-audio', '--hide-scrollbars', ...(process.env.BROWSER_FLAGS ?? '').split(' ').filter(Boolean), 'about:blank'], { stdio: 'ignore' });
  const browser = { exe, proc, profile, port: null, endpoint: null, swept };
  browser.connect = async () => {
    const portFile = join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 200 && !existsSync(portFile); i++) await sleep(150);
    if (!existsSync(portFile)) throw new Error('the headless browser did not start within 30 s');
    browser.port = readFileSync(portFile, 'utf8').split('\n')[0].trim();
    browser.endpoint = (await fetch(`http://127.0.0.1:${browser.port}/json/version`).then((r) => r.json())).webSocketDebuggerUrl;
    const page = (await fetch(`http://127.0.0.1:${browser.port}/json/list`).then((r) => r.json())).find((t) => t.type === 'page');
    return Cdp.open(page.webSocketDebuggerUrl);
  };
  browser.untrack = onExit(() => close(browser));
  return browser;
}

// Closes the whole browser. The process spawned is not the browser on Windows: Edge
// hands over to another process and that one exits, so killing it, or waiting for it,
// leaves the browser, GPU, renderer and utility processes running with the profile
// locked. The browser is asked to close over DevTools; its tree is killed if it stays.
async function closeBrowser({ proc, port, endpoint }) {
  const answering = () => fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(500) }).then(() => true, () => false);
  let pid = proc.pid;
  if (endpoint) {
    try {
      const b = await Cdp.open(endpoint);
      const info = await Promise.race([b.send('SystemInfo.getProcessInfo'), sleep(2000)]);
      pid = info?.processInfo?.find((p) => p.type === 'browser')?.id ?? pid;
      await Promise.race([b.send('Browser.close'), sleep(3000)]);
    } catch {
      // not answering: the tree is killed below
    }
    for (let i = 0; i < 50 && (await answering()); i++) await sleep(100);
  }
  // only a browser still answering is killed: a closed one's PID may belong to
  // another process by now
  const stillUp = endpoint ? await answering() : proc.exitCode === null && proc.signalCode === null;
  if (stillUp) kill(pid);
}

// Closes the browser, then kills what is left with its profile and removes the profile.
// left: this browser's processes still there after 5 s (killed now); others: processes
// of other runs, only to report.
export async function close(browser) {
  if (browser.closed) return browser.closed;
  browser.closed = (async () => {
    await closeBrowser(browser);
    const { left, others } = await leftovers(browser.profile);
    for (const p of left) kill(p.pid);
    browser.untrack?.();
    const removeError = await removeDir(browser.profile);
    return { left, others, removeError };
  })();
  return browser.closed;
}

// ---------- command line ----------

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const flag = (f) => process.argv.includes(f);
  if (!flag('--sweep')) {
    console.log('usage: node scripts/browser/headless.js --sweep [--legacy] [--dry-run]');
    process.exit(0);
  }
  console.log(describeSweep(await sweep({ legacy: flag('--legacy'), dryRun: flag('--dry-run') })));
}
