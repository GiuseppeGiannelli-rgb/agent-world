// Browser checks for specs 01 and 02. Starts a demo server of its own, drives a headless
// Edge or Chrome over the DevTools protocol, injects scripts/browser/*.js into the page
// and runs them; exits 1 if any check fails. No dependencies: Node's own fetch and
// WebSocket (Node 22+).
//
//   node scripts/browser-test.js                    every phase, a full demo mission included
//   node scripts/browser-test.js --skip-run         without the mission
//   node scripts/browser-test.js --shots DIR        also save JPEG screenshots in DIR
//   node scripts/browser-test.js --only views,cubes --root DIR --tag prima
//                                                   the same measures on another checkout
//   --json FILE   write every result to FILE        BROWSER=path   pick the browser
//   --spec NN     prefix of the screenshots (02)    --port N       port of the demo server
//
// Phases. Spec 01: views (A1 coverage, 3 viewports x 3 panel layouts), checks (A6, A7,
// A8 and the trap mutation), cubes (A9), input (A7 with real mouse events), run (A10).
// Spec 02: overlaps (P1-P5: the fixed UI over the matrix of inputs and states), labels
// (E1-E7 and the N4 variants of the room labels).
// Expected reds: a check that fails on today's code and is listed in
// scripts/browser/known-red.json, with the ticket that fixes it, is counted apart and
// does not fail the run; listed but passing, it does (its mark must go).
// The server never sees an API key: every key the config names is set to "" (present,
// so .env cannot fill it in), and a run that is not in demo mode is stopped at once.
// At the end no browser process may be left with this run's profile.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Node's WebSocket is global from Node 22 (package.json allows 20.10 for the app). Without
// it the runner would start the server and the browser, fail to reach DevTools, and could
// not close the browser either: on Windows its processes stayed behind. Stop before.
if (typeof WebSocket !== 'function') {
  console.error(`FAIL the browser checks need Node 22 or later (global WebSocket); this is Node ${process.versions.node}`);
  process.exit(1);
}

const HERE = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback = null) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};
const flag = (name) => process.argv.includes(name);
const ROOT = resolve(arg('--root', join(HERE, '..')));
const PHASES = (arg('--only') ?? 'views,checks,cubes,input,overlaps,labels,run').split(',').filter((p) => !(flag('--skip-run') && p === 'run'));
const SHOTS = arg('--shots') && resolve(arg('--shots'));
const TAG = arg('--tag', 'dopo');
const SPEC = arg('--spec', '02');
const PORT = Number(arg('--port', 4397));
const BASE = `http://127.0.0.1:${PORT}`;
const MISSION = 'Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi';
const VIEWPORTS = [[1920, 1080], [2560, 1440], [1440, 900]];
const LAYOUTS = { LR: [true, true], '-R': [false, true], '--': [false, false] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The checks red on purpose until their ticket: { "<criterion> <name>": "T1", ... }.
// Another checkout (--tag prima) is only measured: no mark applies there.
const KNOWN_RED = TAG === 'prima' ? {} : JSON.parse(readFileSync(join(HERE, 'browser', 'known-red.json'), 'utf8'));
const results = { root: ROOT, tag: TAG, phases: PHASES, expectedReds: {} };
const reported = new Set();
let failures = 0;
const report = (phase, name, ok, data) => {
  const key = `${phase} ${name}`;
  const ticket = KNOWN_RED[key];
  reported.add(key);
  (results[phase] ??= {})[name] = { ok, ...(ticket ? { expectedRedUntil: ticket } : {}), ...data };
  if (ticket && !ok) {
    results.expectedReds[ticket] = (results.expectedReds[ticket] ?? 0) + 1;
    console.log(`red  ${phase.padEnd(6)} ${name}  (until ${ticket})`);
    return;
  }
  if (ticket) {
    failures++;
    console.log(`FAIL ${phase.padEnd(6)} ${name}  passes before ${ticket}: remove its mark from known-red.json`);
    return;
  }
  if (!ok) failures++;
  console.log(`${ok ? 'ok ' : 'FAIL'} ${phase.padEnd(6)} ${name}${ok ? '' : `  ${JSON.stringify(data)}`}`);
};
// which phase reports a criterion, to tell a mark whose check is gone from one whose
// phase did not run
const phaseOf = (key) => {
  const c = key.split(' ')[0];
  if (/^(P\d|walk|inputs)$/.test(c)) return 'overlaps';
  if (/^(E\d|model|D8)$/.test(c)) return 'labels';
  return { A6: 'checks', A7: 'checks', A8: 'checks', A9: 'cubes', A10: 'run' }[c] ?? c;
};

function findBrowser() {
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

// ---------- demo server ----------

function keyNames() {
  const names = new Set();
  const walk = (o) => {
    if (!o || typeof o !== 'object') return;
    for (const [k, v] of Object.entries(o)) {
      if (k === 'keyEnv' && typeof v === 'string') names.add(v);
      else walk(v);
    }
  };
  // local.json (this machine's settings) may add providers of its own
  for (const file of ['default.json', 'local.json']) {
    const path = join(ROOT, 'config', file);
    if (existsSync(path)) walk(JSON.parse(readFileSync(path, 'utf8')));
  }
  return names;
}

async function startServer(home) {
  const env = { ...process.env, PORT: String(PORT), AGENT_WORLD_HOME: home };
  delete env.AGENT_WORLD_FAST; // the mission at its normal pace, as in T0
  for (const k of Object.keys(env)) if (/_KEY$/.test(k)) env[k] = '';
  for (const k of keyNames()) env[k] = '';
  const server = spawn(process.execPath, ['server/index.js'], { cwd: ROOT, env, stdio: ['ignore', 'pipe', 'inherit'] });
  await new Promise((ok, fail) => {
    server.once('exit', (code) => fail(new Error(`server exited (${code})`)));
    server.stdout.on('data', (d) => d.toString().includes('Agent World') && ok());
  });
  return server;
}
const api = (path, body) => fetch(BASE + path, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {}).then((r) => r.json());

// ---------- DevTools protocol ----------

class Cdp {
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

// The browser process the runner owns; `connect()` waits for its DevTools endpoint.
function launchBrowser(profile) {
  const exe = findBrowser();
  if (!exe) throw new Error('no Edge or Chrome found: set BROWSER to its path');
  const proc = spawn(exe, ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check', '--disable-extensions', '--disable-breakpad', '--disable-crash-reporter', '--mute-audio', '--hide-scrollbars', 'about:blank'], { stdio: 'ignore' });
  const browser = { exe, proc, port: null, endpoint: null };
  browser.connect = async () => {
    const portFile = join(profile, 'DevToolsActivePort');
    for (let i = 0; i < 200 && !existsSync(portFile); i++) await sleep(150);
    if (!existsSync(portFile)) throw new Error('the headless browser did not start within 30 s');
    browser.port = readFileSync(portFile, 'utf8').split('\n')[0].trim();
    browser.endpoint = (await fetch(`http://127.0.0.1:${browser.port}/json/version`).then((r) => r.json())).webSocketDebuggerUrl;
    const page = (await fetch(`http://127.0.0.1:${browser.port}/json/list`).then((r) => r.json())).find((t) => t.type === 'page');
    return Cdp.open(page.webSocketDebuggerUrl);
  };
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
  const alive = endpoint ? await answering() : proc.exitCode === null && proc.signalCode === null;
  if (!alive) return;
  kill(pid);
}
function kill(pid) {
  if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
  else {
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      // gone already
    }
  }
}

// Browser processes of any run of these checks: their command line names a profile
// folder agent-world-profile-XXXXXX (retro of spec 01, action 6).
function profileProcesses() {
  const r =
    process.platform === 'win32'
      ? spawnSync('powershell', ['-NoProfile', '-NonInteractive', '-Command', "Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'msedge.exe', 'chrome.exe' } | ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.CommandLine }"], { encoding: 'utf8' })
      : spawnSync('ps', ['-eo', 'pid=,args='], { encoding: 'utf8' });
  return (r.stdout ?? '')
    .split(/\r?\n/)
    .map((l) => l.trim().match(/^(\d+)\s+(.*)$/))
    .filter((m) => m && m[2].includes('agent-world-profile-'))
    .map(([, pid, cmd]) => ({ pid: Number(pid), profile: cmd.match(/agent-world-profile-\w+/)[0] }));
}
// After the close: this run's processes get a few seconds to exit. Those of another run
// (an earlier one, or one in parallel on another --port) are only reported: failing on
// them would make two parallel runs fail each other.
async function leftovers(profile) {
  const mine = basename(profile);
  for (const end = Date.now() + 5000; ; await sleep(250)) {
    const all = profileProcesses();
    const left = all.filter((p) => p.profile === mine);
    if (!left.length || Date.now() > end) return { left, others: all.filter((p) => p.profile !== mine) };
  }
}

// ---------- the page ----------

const SCRIPTS = ['lib.js', 'coverage.js', 'framing.js', 'manual-mode.js', 'absolute-scale.js', 'cube-stress.js', 'run-probe.js', 'overlaps.js', 'labels.js'].map((f) => readFileSync(join(HERE, 'browser', f), 'utf8'));

// settle: the wait for the first insets and frames; the overlaps phase, which only reads
// the CSS layout, waits for real frames instead
async function load(cdp, [width, height], { settle = 800 } = {}) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: BASE });
  for (let i = 0; i < 200; i++) {
    await sleep(100);
    if (await cdp.eval('Boolean(window.agentWorld?.actors.size && window.agentWorld.layout)').catch(() => false)) break;
  }
  await sleep(settle);
  // a script's value is its last statement: void 0, not an object holding the World
  for (const src of SCRIPTS) await cdp.eval(`${src}\n;void 0`);
  await cdp.eval('__t.frames(3)');
}
async function viewport(cdp, [width, height]) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await sleep(600);
}
// A new window size for the CSS: a few real frames, for the ResizeObservers of main.js.
async function resizeTo(cdp, [width, height]) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await cdp.eval('__t.frames(3)');
}
// The real panel buttons, then real frames for the re-frame to finish.
async function layout(cdp, [left, right]) {
  await cdp.eval(`(() => { const t = window.__t; if (t.isOpen('#left') !== ${left}) t.$('#btn-left').click(); if (t.isOpen('#right') !== ${right}) t.$('#btn-right').click(); })()`);
  await sleep(900);
}
// tag: what the picture shows, the checkout measured (prima, dopo) unless told otherwise
async function shot(cdp, name, tag = TAG) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 72 });
  writeFileSync(join(SHOTS, `${SPEC}-${tag}-${name}.jpg`), Buffer.from(data, 'base64'));
}

// ---------- phases ----------

async function views(cdp) {
  for (const vp of VIEWPORTS) {
    await viewport(cdp, vp);
    for (const [name, panels] of Object.entries(LAYOUTS)) {
      await layout(cdp, panels);
      const c = await cdp.eval('window.__checks.coverage()');
      // A1 is the new behaviour: on another checkout the numbers are the baseline
      report('views', `${vp.join('x')} ${name}: floor under the UI ${c.floorCoveredPct}%, office ${c.officeWidthPx} px`, TAG === 'prima' || (c.floorUnderObstaclesPct === 0 && c.envelopeUnderObstacles === 0), c);
      if (vp[0] === 1920) await shot(cdp, `${vp.join('x')}-${name === '--' ? 'nessun-pannello' : name === 'LR' ? 'due-pannelli' : 'pannello-destro'}`);
    }
  }
  await viewport(cdp, VIEWPORTS[0]);
  await layout(cdp, LAYOUTS.LR);
}

async function checks(cdp) {
  const each = (phase, out, prefix = '') => Object.entries(out).forEach(([k, v]) => report(phase, prefix + k, v.ok, v));
  each('A6', await cdp.eval('window.__checks.framing()'));
  each('A7', await cdp.eval('window.__checks.manualMode()'));
  for (const vp of VIEWPORTS) {
    await viewport(cdp, vp);
    each('A8', await cdp.eval('window.__checks.absoluteScale()'), `${vp.join('x')} `);
  }
  await viewport(cdp, VIEWPORTS[0]);
  // the trap put back on purpose must be caught, and only where expected
  const mutated = await cdp.eval('window.__checks.absoluteScale({ mutate: true })');
  const caught = Object.entries(mutated).filter(([, v]) => !v.ok).map(([k]) => k);
  const expected = ['⌂ from the closest view, LR → --', 'drag that interrupts ⌂ from the closest view'];
  report('A8', 'the zoom-limit trap, put back on purpose, is caught', expected.every((k) => caught.includes(k)), { caught });
}

async function cubes(cdp) {
  const out = await cdp.eval('window.__checks.cubeStress()');
  for (const [k, v] of Object.entries(out)) report('A9', k, TAG === 'prima' || v.ok, v);
}

// ---------- real input ----------

// The browser's own mouse events, pointer capture included.
const mouseEvent = (cdp, type, [x, y], o = {}) => cdp.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1, ...o });
const viewState = (cdp) => cdp.eval('({ auto: agentWorld.autoFrame, picture: __t.picture(), scale: __t.screenScale() })');
const moved = (a, b) => Math.max(...a.picture.map(([x, y], i) => Math.hypot(x - b.picture[i][0], y - b.picture[i][1])));
// until the picture is still: drag inertia decays by 0.92 a frame, so how long it
// lasts depends on how fast the browser draws (12 to 60 fps seen here)
async function settleView(cdp) {
  let last = await viewState(cdp);
  for (let i = 0; i < 40; i++) {
    await sleep(250);
    const now = await viewState(cdp);
    if (moved(last, now) < 0.02 && i >= 3) return;
    last = now;
  }
}
async function homeView(cdp) {
  await cdp.eval("document.querySelector('#btn-home').click()");
  await settleView(cdp);
}
// A floor point in the free area with no agent and no label over it, looked up just
// before each action: a click on a room label is a room focus, and a wheel over a
// label never reaches the canvas. The idle agents' strolls are paused meanwhile, so
// their labels do not cross the point between the look-up and the event.
const freeFloor = (cdp) =>
  cdp.eval(`(() => {
    const w = agentWorld, r = w.canvas.getBoundingClientRect();
    for (let fy = 0.42; fy < 0.7; fy += 0.02) for (let fx = 0.4; fx < 0.6; fx += 0.02) {
      const p = { clientX: r.left + r.width * fx, clientY: r.top + r.height * fy };
      if (!w.pick(p) && document.elementFromPoint(p.clientX, p.clientY) === w.canvas) return [p.clientX, p.clientY];
    }
  })()`);

// A7 with real input.
async function input(cdp) {
  const mouse = (...a) => mouseEvent(cdp, ...a);
  const state = () => viewState(cdp);
  const settle = () => settleView(cdp);
  const home = () => homeView(cdp);
  await cdp.eval('agentWorld.wander = () => {}');
  try {
    await home();

    let p = await freeFloor(cdp);
    await mouse('mousePressed', p);
    await mouse('mouseReleased', p);
    await sleep(300);
    report('input', 'a real click on the floor keeps the view automatic', (await state()).auto === true, {});

    p = await freeFloor(cdp);
    for (let i = 0; i <= 10; i++) await mouse(i ? 'mouseMoved' : 'mousePressed', [p[0] + 8 * i, p[1] + 3 * i]);
    await mouse('mouseReleased', [p[0] + 80, p[1] + 30]);
    await settle();
    const dragged = await state();
    await cdp.eval("document.querySelector('#btn-right').click()");
    await settle();
    const after = await state();
    report('input', 'a real drag takes the view; a panel then moves nothing', dragged.auto === false && moved(dragged, after) < 0.5, { autoFrame: dragged.auto, pxMovedByPanel: +moved(dragged, after).toFixed(2) });
    await cdp.eval("document.querySelector('#btn-right').click()");
    await settle();

    await home();
    const fitted = await state();
    p = await freeFloor(cdp);
    await cdp.eval("window.__wheelSeen = []; window.addEventListener('wheel', (e) => __wheelSeen.push({ onCanvas: e.target === agentWorld.canvas, usedByControls: e.defaultPrevented }), { once: true })");
    await cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: p[0], y: p[1], deltaX: 0, deltaY: -120 });
    await settle();
    const wheeled = await state();
    const [seen] = await cdp.eval('window.__wheelSeen');
    report('input', 'a real wheel step takes the view, ⌂ gives it back', fitted.auto === true && wheeled.auto === false && wheeled.scale < fitted.scale, { afterAuto: wheeled.auto, ...seen, sizeOnScreen: [+fitted.scale.toFixed(5), +wheeled.scale.toFixed(5)] });

    await home();
    const agent = await cdp.eval(`(() => {
      const w = agentWorld, r = w.canvas.getBoundingClientRect();
      for (const a of w.actors.values()) {
        const [x, y] = __t.toScreen(a.position.clone().setY(0.7));
        const p = { clientX: r.left + x, clientY: r.top + y };
        if (w.pick(p) === a.id && document.elementFromPoint(p.clientX, p.clientY) === w.canvas) return [p.clientX, p.clientY];
      }
    })()`);
    await mouse('mousePressed', agent);
    await mouse('mouseReleased', agent);
    await settle();
    const focused = await state();
    const ratio = await cdp.eval('__t.screenScale() / ((62 / 1920) / 2.2)');
    report('input', 'a real click on an agent focuses it at the old size, manual', focused.auto === false && Math.abs(ratio - 1) < 0.02, { autoFrame: focused.auto, sizeRatio: +ratio.toFixed(4) });
    await home();
    report('input', '⌂ after all that: automatic again', (await state()).auto === true, {});
  } finally {
    await cdp.eval('delete agentWorld.wander');
  }
}

// ---------- spec 02: the fixed UI ----------

// Window sizes: the matrix of §3.1 (with fresh-page references for P4) and the edges of
// the media queries at 1250 and 900 px.
const MATRIX = ['1920x1080', '1280x800', '1200x800', '1000x800', '800x600'];
const EDGES = ['1251x800', '1250x800', '901x800', '900x800'];
const size = (key) => key.split('x').map(Number);
const isNarrow = (key) => size(key)[0] <= 900;
const WIDE_LAYOUTS = ['LR', 'L-', '-R', '--'];

// P4's reference: for each size and panel state, a fresh page brought to it with the
// panel buttons, as a user would. Narrow, the state is the overlay open.
async function references(cdp) {
  const refs = {};
  for (const key of MATRIX) {
    refs[key] = {};
    const states = isNarrow(key) ? { none: [], L: ['#btn-left'], R: ['#btn-right'] } : { LR: [], 'L-': ['#btn-right'], '-R': ['#btn-left'], '--': ['#btn-left', '#btn-right'] };
    for (const [state, presses] of Object.entries(states)) {
      await load(cdp, size(key), { settle: 0 });
      const snap = await cdp.eval(`(async () => {
        for (const s of ${JSON.stringify(presses)}) document.querySelector(s).click();
        await __t.frames(3);
        return { state: __checks.overlaps.state(), snapshot: __checks.overlaps.snapshot() };
      })()`);
      if (snap.state !== state) throw new Error(`reference ${key} ${state}: the page is in ${snap.state}`);
      refs[key][state] = snap.snapshot;
    }
  }
  return refs;
}

// A small seeded generator: the random walks are the same at every run.
function mulberry32(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let r = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    r = (r + Math.imul(r ^ (r >>> 7), 61 | r)) ^ r;
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

async function overlaps(cdp) {
  const started = Date.now();
  const refs = await references(cdp);
  await load(cdp, size('1920x1080'), { settle: 0 });
  const ref = (key) => JSON.stringify(refs[key] ?? null);
  // one check per criterion and size, with the worst cases in its data
  const agg = {};
  const add = (crit, name, ok, where, detail) => {
    const a = (agg[`${crit}\t${name}`] ??= { cases: 0, failed: 0, first: [] });
    a.cases++;
    if (ok) return;
    a.failed++;
    if (a.first.length < 4) a.first.push(`${where}: ${detail}`);
  };
  const record = (key, where, r) => {
    add('P1', key, !r.P1.length, where, r.P1.join('; '));
    if (r.inspector) add('P1', `${key} inspector`, !r.P1i.length, where, r.P1i.join('; '));
    add('P2', key, !r.P2, where, r.P2);
    if (r.inspector) add('P2', `${key} inspector`, !r.P2i, where, r.P2i);
    add('P3', key, !r.P3, where, r.P3);
    if ('P4' in r) add('P4', key, !r.P4, where, r.P4);
  };
  const problems = (r) => [...r.P1, ...r.P1i, r.P2, r.P2i, r.P3, r.P4].filter(Boolean);

  // 1. every input of the matrix from every start state. Narrow, the start states are
  // the closed classes each wide layout leaves behind (Q2), every overlay closed.
  for (const key of [...MATRIX, ...EDGES]) {
    for (const lay of WIDE_LAYOUTS) {
      if (isNarrow(key)) {
        await resizeTo(cdp, size('1920x1080'));
        await cdp.eval(`__checks.overlaps.reset(${JSON.stringify(lay)})`);
      }
      await resizeTo(cdp, size(key));
      const out = await cdp.eval(`__checks.overlaps.each(${isNarrow(key) ? 'null' : JSON.stringify(lay)}, ${ref(key)})`);
      for (const [input, r] of Object.entries(out)) {
        const where = `${isNarrow(key) ? `${lay} at 1920, then ${key}` : lay} + ${input}`;
        record(key, where, r);
        // every input of the matrix is prepared so that it applies: one that does not
        // would leave its cases unchecked without a word
        add('inputs', key, r.applied !== false, where, 'the input could not be applied');
      }
    }
  }

  // 2. resizes across 1250 and 900 px, both ways, with the inspector closed and open
  const SEQS = [['1920x1080', '1200x800', '1920x1080'], ['1200x800', '800x600', '1200x800'], ['1920x1080', '800x600', '1920x1080']];
  for (const lay of WIDE_LAYOUTS) {
    for (const inspector of [false, true]) {
      for (const seq of SEQS) {
        await resizeTo(cdp, size(seq[0]));
        await cdp.eval(`__checks.overlaps.reset(${JSON.stringify(lay)})`);
        if (inspector) await cdp.eval("__checks.overlaps.press('member')");
        for (const [i, key] of seq.entries()) {
          if (i) await resizeTo(cdp, size(key));
          record(key, `${lay}${inspector ? ' + inspector' : ''}: ${seq.slice(0, i + 1).join(' → ')}`, await cdp.eval(`__checks.overlaps.check(${ref(key)})`));
        }
      }
    }
  }

  // 3. P5: the automatic view re-frames for every input that opens or closes a panel
  for (const key of MATRIX.filter((k) => !isNarrow(k))) {
    await resizeTo(cdp, size(key));
    const steps = await cdp.eval('__checks.overlaps.reframe()');
    report('P5', key, Object.values(steps).every((s) => s.ok && s.auto), { steps });
  }
  await resizeTo(cdp, size('1920x1080'));
  const frozen = await cdp.eval('__checks.overlaps.reframe({ mutate: true })');
  report('P5', 'the frozen insets, put on purpose, are caught', !Object.values(frozen).at(-1).ok, { steps: frozen });

  // 4. random walks: inputs and resizes in an order nobody planned, P1-P4 at each step
  const WALK = ['left', 'right', 'tab', 'room', 'goroom', 'member', 'close', 'resize'];
  for (let n = 1; n <= 3; n++) {
    await load(cdp, size('1920x1080'), { settle: 0 });
    const rnd = mulberry32(n * 7919);
    let key = '1920x1080';
    const steps = [];
    const bad = [];
    for (let i = 1; i <= 25; i++) {
      const choice = WALK[Math.floor(rnd() * WALK.length)];
      if (choice === 'resize') {
        const others = MATRIX.filter((k) => k !== key);
        key = others[Math.floor(rnd() * others.length)];
        await resizeTo(cdp, size(key));
        steps.push(`→ ${key}`);
      } else steps.push((await cdp.eval(`__checks.overlaps.press(${JSON.stringify(choice)})`)) ? choice : `${choice} (n/a)`);
      const r = await cdp.eval(`__checks.overlaps.check(${ref(key)})`);
      if (problems(r).length) bad.push({ step: i, size: key, state: r.state, problems: problems(r) });
    }
    report('walk', String(n), !bad.length, { steps: steps.join(', '), failedSteps: bad.map((b) => b.step), failures: bad });
  }

  // 5. the inspector open over a sweep of window widths, both panels open: the narrowest
  // columns (901-1047 and 1251-1333 px), the edges of each band, and narrow windows
  // down to a phone's. P1, P2 (the inspector never scrolls sideways) at every width.
  const sweep = [360, 600, 800, 900, 1047, 1048, 1250, 1251, 1321, 1322, 1333, 1334, 1440, 1920];
  for (let x = 901; x <= 1340; x += 7) sweep.push(x);
  await resizeTo(cdp, size('1920x1080'));
  await cdp.eval("__checks.overlaps.reset('LR')");
  await cdp.eval("__checks.overlaps.press('member')");
  for (const x of [...new Set(sweep)].sort((a, b) => a - b)) {
    await resizeTo(cdp, [x, 800]);
    const r = await cdp.eval('__checks.overlaps.check()');
    add('P1', 'sweep 360-1920 inspector', r.inspector && !r.P1.length && !r.P1i.length, `${x}x800`, r.inspector ? [...r.P1, ...r.P1i].join('; ') : 'the inspector closed');
    add('P2', 'sweep 360-1920 inspector', r.inspector && !r.P2 && !r.P2i, `${x}x800`, [r.P2, r.P2i].filter(Boolean).join('; '));
  }

  for (const [k, a] of Object.entries(agg)) {
    const [crit, name] = k.split('\t');
    report(crit, name, a.failed === 0, { cases: a.cases, failed: a.failed, first: a.first });
  }

  // the cases of the spec, on screen
  if (SHOTS) {
    const scene = async (key, lay, presses, name, then = null) => {
      await resizeTo(cdp, size(key));
      await cdp.eval(`__checks.overlaps.reset(${JSON.stringify(lay)})`);
      for (const p of presses) await cdp.eval(`__checks.overlaps.press(${JSON.stringify(p)})`);
      if (then) await resizeTo(cdp, size(then));
      await homeView(cdp); // the whole office, not the room an earlier input focused
      await cdp.eval('__t.tallInspector()');
      await shot(cdp, name);
    };
    await scene('1920x1080', 'L-', ['tab'], 'n6-1920x1080-scheda-dopo-pannello-chiuso');
    await scene('1200x800', 'L-', [], 'q1-1200x800-pannello-destro-chiuso');
    await scene('1920x1080', '--', [], 'q2-800x600-dopo-pannelli-chiusi', '800x600');
    await scene('1000x800', 'LR', ['member'], 'q3-1000x800-inspector');
    await scene('1280x800', 'LR', ['member'], 'q4-1280x800-inspector');
  }
  await load(cdp, VIEWPORTS[0]); // the next phases start from a fresh page
  results.overlapsSeconds = Math.round((Date.now() - started) / 1000);
  console.log(`       overlaps in ${results.overlapsSeconds} s`);
}

// ---------- spec 02: the labels ----------

const LABEL_SIZES = ['1920x1080', '1440x900', '2560x1440'];

async function labels(cdp) {
  const started = Date.now();
  const runs = {};
  // the bays filled once, after every size has been measured with them empty
  for (const bays of ['vuote', 'piene']) {
    for (const key of LABEL_SIZES) {
      await viewport(cdp, size(key));
      runs[`${key} ${bays}`] = await cdp.eval(`__checks.labels.run({ bays: '${bays}' })`);
    }
  }
  const all = {};
  const merge = (into, worst, key = null) => {
    for (const [k, v] of Object.entries(worst)) if (!into[k] || v.value > into[k].value) into[k] = key ? { ...v, where: `${key}, ${v.where}` } : v;
  };
  for (const key of LABEL_SIZES) {
    const w = {};
    for (const bays of ['vuote', 'piene']) merge(w, runs[`${key} ${bays}`].worst, key);
    merge(all, w);
    const zero = (k) => (w[k]?.value ?? 0) === 0;
    report('E1', key, zero('prod E1'), w['prod E1']);
    report('E2', key, zero('prod E2'), w['prod E2']);
    report('E3', key, zero('prod E3'), w['prod E3']);
    report('E4', key, zero('prod E4'), w['prod E4']);
    // E5 without the feet of the sub-agents, which D8 accepts up to 3 (checked below)
    report('E5', key, zero('prod E5') && zero('prod E5 nomi') && (w['prod E5 piedi']?.value ?? 0) <= 3, { agentsUnderARoomLabel: w['prod E5'], subAgentFeet: w['prod E5 piedi'], roomNamesNotClickable: w['prod E5 nomi'] });
    if (w['prod E6']) report('E6', key, zero('prod E6'), w['prod E6']);
  }
  const counts = {};
  for (const r of Object.values(runs)) for (const [k, [n, of]] of Object.entries(r.counts)) counts[k] = [(counts[k]?.[0] ?? 0) + n, (counts[k]?.[1] ?? 0) + of];
  // the exceptions accepted with D8 (spec §3.2), over the whole matrix
  const feet = all['prod E5 piedi'] ?? { value: 0 };
  report('D8', 'the feet of at most 3 sub-agents under their room label, in at most 2 states', feet.value <= 3 && (counts['prod E5 piedi']?.[0] ?? 0) <= 2, { ...feet, statesNotZero: counts['prod E5 piedi'] });
  report('D8', 'the painted bay text covered at most 27%', (all['prod scritta della bay']?.value ?? 0) <= 27, all['prod scritta della bay']);
  // the variant the labels are drawn as, recognised by the model
  const drawnAs = [...new Set(Object.values(runs).flatMap((r) => Object.keys(r.drawn)))];
  results.drawnVariant = drawnAs.join(', ');
  report('model', 'the drawn room labels match a variant of the model within 1 px', all['model check'].value <= 1, all['model check']);
  report('model', 'the app draws variant B (D8)', drawnAs.length === 1 && drawnAs[0] === 'B', { drawnAs });
  const s01 = runs['1920x1080 vuote'].spec01;
  report('model', 'spec 01 numbers: 7/7 workers under their room label, full view LR', s01?.workers === 7 && s01.covered === 7, s01);
  const subs = runs[`${LABEL_SIZES[0]} piene`].subAgents;
  report('model', 'every bay seat taken', subs === 14, { subAgents: subs });
  await viewport(cdp, size('1920x1080'));
  const byCss = await cdp.eval('__checks.labels.checkVariants()');
  report('model', 'every variant computed within 1 px of the same variant drawn by CSS', Object.values(byCss).every((d) => d.worstPx <= 1), byCss);
  const trap = await cdp.eval('__checks.labels.orderTrap()');
  report('E1', 'the order put back on purpose (rooms over agents) is caught', trap.value > 0, trap);

  // the table for D8: the worst case over the whole matrix, per variant and measure
  const MEASURES = ["E1 ordine dell'app", 'E1 agenti sopra', 'E2', 'E3', 'E4', 'E5', 'scritta della bay'];
  const variants = {};
  for (const v of ['oggi', 'A', 'B', 'C']) variants[v] = Object.fromEntries(MEASURES.map((m) => [m, all[`${v} ${m}`] ? { ...all[`${v} ${m}`], statesNotZero: counts[`${v} ${m}`] } : null]));
  results.variants = variants;
  results.labelStates = Object.values(runs).reduce((n, r) => n + r.states, 0);
  console.log(`       labels: ${results.labelStates} states measured; worst case per variant, and in how many states it is not 0 (E1 %, E2 px², E3 and E4 count, E5 agents, bay text %):`);
  for (const [v, m] of Object.entries(variants)) console.log(`       ${v.padEnd(5)} ${MEASURES.map((k) => `${k} ${m[k]?.value ?? '—'} (${m[k]?.statesNotZero?.join('/') ?? '—'})`).join(' | ')}`);

  // E7 with real input: a wheel step over a label zooms as it does over the canvas
  await viewport(cdp, size('1920x1080'));
  await layout(cdp, LAYOUTS.LR);
  await cdp.eval('__checks.labels.still()');
  try {
    // the variants drawn, with every bay seat taken, for the choice of D8
    if (SHOTS) {
      await cdp.eval('__checks.overlaps.reset(null)'); // no inspector left open by an earlier phase
      for (const [lay, panels] of [['LR', LAYOUTS.LR], ['--', LAYOUTS['--']]]) {
        await layout(cdp, panels);
        for (const v of ['oggi', 'A', 'B', 'C']) {
          // the variant the app draws is the app itself; the others are proposals
          const own = drawnAs[0] === v;
          await cdp.eval(own ? '__checks.labels.preview(null)' : `__checks.labels.preview('${v}')`);
          await homeView(cdp);
          await shot(cdp, `n4-${v}-1920x1080-${lay === 'LR' ? 'due-pannelli' : 'nessun-pannello'}`, own ? TAG : 'variante');
        }
      }
      await cdp.eval('__checks.labels.preview(null)');
      await layout(cdp, LAYOUTS.LR);
    }
    for (const [kind, name] of [['room', 'wheel over a room label'], ['tag', 'wheel over an agent label']]) {
      await homeView(cdp);
      const p = (await cdp.eval('__checks.labels.targets()'))[kind];
      if (!p) {
        report('E7', name, false, { error: 'no label of this kind is free under the pointer' });
        continue;
      }
      const wheel = async (at) => {
        const before = await viewState(cdp);
        await cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: at[0], y: at[1], deltaX: 0, deltaY: -120 });
        await settleView(cdp);
        const after = await viewState(cdp);
        return { ratio: after.scale / before.scale, auto: after.auto };
      };
      const over = await wheel(p);
      await homeView(cdp);
      const canvas = await wheel(await freeFloor(cdp));
      report('E7', name, Math.abs(over.ratio / canvas.ratio - 1) <= 0.02 && over.auto === false, { at: p.map(Math.round), overTheLabel: { ratio: +over.ratio.toFixed(4), auto: over.auto }, overTheCanvas: { ratio: +canvas.ratio.toFixed(4) } });
    }
  } finally {
    await homeView(cdp);
    await cdp.eval('__checks.labels.done()');
  }
  results.labelsSeconds = Math.round((Date.now() - started) / 1000);
  console.log(`       labels in ${results.labelsSeconds} s`);
}

async function run(cdp) {
  await load(cdp, VIEWPORTS[0]); // a fresh page, as a user would start a mission: no state left by the checks
  await layout(cdp, LAYOUTS.LR);
  await cdp.eval("agentWorld.resetView(); window.__checks.runProbe.start()");
  const created = await api('/api/runs', { goal: MISSION });
  if (!created.id) throw new Error(`the mission did not start: ${JSON.stringify(created)}`);
  let r = await api(`/api/runs/${created.id}`);
  if (r.mode !== 'demo') {
    await api(`/api/runs/${created.id}/stop`, {});
    throw new Error(`run in mode "${r.mode}", not demo: stopped`);
  }
  const done = ['completed', 'completed_with_failures', 'failed', 'stopped'];
  const deadline = Date.now() + 15 * 60_000;
  let over = 0;
  while (Date.now() < deadline) {
    for (const name of await cdp.eval('window.__checks.runProbe.due()')) await shot(cdp, `run-${name}`);
    if (!over) {
      r = await api(`/api/runs/${created.id}`);
      if (done.includes(r.status)) over = Date.now();
    } else if (Date.now() - over > 4000 && (await cdp.eval('agentWorld.fx.items.length')) === 0) break; // last flights, sinks, confetti
    else if (Date.now() - over > 60_000) break;
    await sleep(250);
  }
  for (const name of await cdp.eval('window.__checks.runProbe.due()')) await shot(cdp, `run-${name}`);
  const p = await cdp.eval('window.__checks.runProbe.report()');
  const tasks = r.tasks ?? [];
  const summary = { status: r.status, workstreams: r.workstreams?.length, tasksDone: `${tasks.filter((x) => x.status === 'done').length}/${tasks.length}`, ...p };
  results.run = summary;
  console.log(`       run    ${r.status} in ${p.seconds} s at ${p.fps} fps (world at ${p.worldSpeed}x the clock): ${JSON.stringify(p.counts)}`);
  report('A10', 'the mission completes', r.status === 'completed', { status: r.status, tasksDone: summary.tasksDone, workstreams: summary.workstreams });
  report('A10', 'no cube anomaly during the run', p.anomalies.length === 0, { anomalies: p.anomalies });
  report('A10', 'no cube left, nobody carrying at the end', p.cubesLeft === 0 && p.actorsCarrying.length === 0, { cubesLeft: p.cubesLeft, carrying: p.actorsCarrying });
  report('A10', 'no frozen effect at the end (N1)', p.activeEffects === 0 && p.frozenRings === 0 && p.frozenSparkles === 0, { active: p.activeEffects, rings: p.frozenRings, sparkles: p.frozenSparkles });
  report('A10', 'every verdict shown with the reviewer at the desk', p.verdicts.total > 0 && p.verdicts.notShown === 0 && p.verdicts.distanceMax <= 1.2, p.verdicts);
  report('A10', 'sub-agents work at their bay seat', p.counts.spawn > 0 && p.counts.spawn === p.counts.despawn && Object.values(p.subs).every((s) => s.workingMax <= 0.5), { spawned: p.counts.spawn, removed: p.counts.despawn, subs: p.subs });
}

// ---------- main ----------

const home = mkdtempSync(join(tmpdir(), 'agent-world-browser-'));
const profile = mkdtempSync(join(tmpdir(), 'agent-world-profile-'));
let server;
let browser;
try {
  server = await startServer(home);
  browser = launchBrowser(profile);
  const cdp = await browser.connect();
  results.browser = browser.exe;
  console.log(`browser checks on ${ROOT} (${TAG}) with ${browser.exe}`);
  await load(cdp, VIEWPORTS[0]);
  const webgl = await cdp.eval('Boolean(agentWorld.renderer.getContext())');
  if (!webgl) throw new Error('no WebGL in the headless browser');
  if (PHASES.includes('views')) await views(cdp);
  if (PHASES.includes('cubes')) await cubes(cdp);
  if (PHASES.includes('checks')) await checks(cdp);
  if (PHASES.includes('input')) await input(cdp);
  if (PHASES.includes('overlaps')) await overlaps(cdp);
  if (PHASES.includes('labels')) await labels(cdp);
  if (PHASES.includes('run')) await run(cdp);
  // a mark whose check is no longer reported would hide nothing and stay forever
  for (const key of Object.keys(KNOWN_RED)) if (PHASES.includes(phaseOf(key)) && !reported.has(key)) report('runner', `the mark "${key}" matches a check of this run`, false, { ticket: KNOWN_RED[key] });
} catch (e) {
  failures++;
  console.error(`FAIL ${e.stack ?? e}`);
} finally {
  if (browser) {
    await closeBrowser(browser);
    const { left, others } = await leftovers(profile);
    report('runner', "no browser process left with this run's profile", !left.length, { left: left.map((p) => p.pid) });
    for (const p of left) kill(p.pid);
    for (const p of others) console.log(`note: browser process ${p.pid} of another run is still there (${p.profile})`);
  }
  server?.kill();
  await sleep(300);
  // the browser, or a virus scanner, holds the profile a moment after it closes
  for (const dir of [home, profile]) {
    for (let i = 0; existsSync(dir); i++) {
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch (e) {
        if (i === 40) {
          console.warn(`note: could not remove ${dir}: ${e.code}`);
          break;
        }
        await sleep(500);
      }
    }
  }
}
if (arg('--json')) writeFileSync(arg('--json'), JSON.stringify(results, null, 2));
const reds = Object.entries(results.expectedReds).map(([k, n]) => `${k}: ${n}`).join(', ');
console.log(`${failures ? `${failures} FAILED` : 'ALL OK'}${reds ? `, expected reds (${reds})` : ''}`);
process.exit(failures ? 1 : 0);
