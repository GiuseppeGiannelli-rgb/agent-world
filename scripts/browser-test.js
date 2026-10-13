// Browser checks for spec 01 (A1, A6-A10). Starts a demo server of its own, drives a
// headless Edge or Chrome over the DevTools protocol, injects scripts/browser/*.js into
// the page and runs them; exits 1 if any check fails. No dependencies: Node's own fetch
// and WebSocket (Node 22+).
//
//   node scripts/browser-test.js                    every phase, a full demo mission included
//   node scripts/browser-test.js --skip-run         without the mission (about a minute)
//   node scripts/browser-test.js --shots DIR        also save JPEG screenshots in DIR
//   node scripts/browser-test.js --only views,cubes --root DIR --tag prima
//                                                   the same measures on another checkout
//   --json FILE   write every result to FILE        BROWSER=path   pick the browser
//
// Phases: views (A1 coverage, 3 viewports x 3 panel layouts), checks (A6, A7, A8 and
// the trap mutation), cubes (A9), input (A7 with real mouse events), run (A10).
// The server never sees an API key: every key the config names is set to "" (present,
// so .env cannot fill it in), and a run that is not in demo mode is stopped at once.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
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
const PHASES = (arg('--only') ?? 'views,checks,cubes,input,run').split(',').filter((p) => !(flag('--skip-run') && p === 'run'));
const SHOTS = arg('--shots') && resolve(arg('--shots'));
const TAG = arg('--tag', 'dopo');
const PORT = Number(arg('--port', 4397));
const BASE = `http://127.0.0.1:${PORT}`;
const MISSION = 'Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi';
const VIEWPORTS = [[1920, 1080], [2560, 1440], [1440, 900]];
const LAYOUTS = { LR: [true, true], '-R': [false, true], '--': [false, false] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const results = { root: ROOT, tag: TAG, phases: PHASES };
let failures = 0;
const report = (phase, name, ok, data) => {
  if (!ok) failures++;
  (results[phase] ??= {})[name] = { ok, ...data };
  console.log(`${ok ? 'ok ' : 'FAIL'} ${phase.padEnd(6)} ${name}${ok ? '' : `  ${JSON.stringify(data)}`}`);
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
  if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
  else process.kill(pid, 'SIGKILL');
}

// ---------- the page ----------

const SCRIPTS = ['lib.js', 'coverage.js', 'framing.js', 'manual-mode.js', 'absolute-scale.js', 'cube-stress.js', 'run-probe.js'].map((f) => readFileSync(join(HERE, 'browser', f), 'utf8'));

async function load(cdp, [width, height]) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: BASE });
  for (let i = 0; i < 100; i++) {
    await sleep(200);
    if (await cdp.eval('Boolean(window.agentWorld?.actors.size && window.agentWorld.layout)').catch(() => false)) break;
  }
  await sleep(800); // first insets, first frames
  // a script's value is its last statement: void 0, not an object holding the World
  for (const src of SCRIPTS) await cdp.eval(`${src}\n;void 0`);
}
async function viewport(cdp, [width, height]) {
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
  await sleep(600);
}
// The real panel buttons, then real frames for the re-frame to finish.
async function layout(cdp, [left, right]) {
  await cdp.eval(`(() => { const t = window.__t; if (t.isOpen('#left') !== ${left}) t.$('#btn-left').click(); if (t.isOpen('#right') !== ${right}) t.$('#btn-right').click(); })()`);
  await sleep(900);
}
async function shot(cdp, name) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 72 });
  writeFileSync(join(SHOTS, `01-${TAG}-${name}.jpg`), Buffer.from(data, 'base64'));
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

// A7 with real input: the browser's own mouse events, pointer capture included.
async function input(cdp) {
  const mouse = (type, [x, y], o = {}) => cdp.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1, ...o });
  const state = () => cdp.eval('({ auto: agentWorld.autoFrame, picture: __t.picture(), scale: __t.screenScale() })');
  const moved = (a, b) => Math.max(...a.picture.map(([x, y], i) => Math.hypot(x - b.picture[i][0], y - b.picture[i][1])));
  // until the picture is still: drag inertia decays by 0.92 a frame, so how long it
  // lasts depends on how fast the browser draws (12 to 60 fps seen here)
  const settle = async () => {
    let last = await state();
    for (let i = 0; i < 40; i++) {
      await sleep(250);
      const now = await state();
      if (moved(last, now) < 0.02 && i >= 3) return;
      last = now;
    }
  };
  const home = async () => {
    await cdp.eval("document.querySelector('#btn-home').click()");
    await settle();
  };
  // A floor point in the free area with no agent and no label over it, looked up just
  // before each action: a click on a room label is a room focus, and a wheel over a
  // label never reaches the canvas. The idle agents' strolls are paused meanwhile, so
  // their labels do not cross the point between the look-up and the event.
  const freeFloor = () =>
    cdp.eval(`(() => {
      const w = agentWorld, r = w.canvas.getBoundingClientRect();
      for (let fy = 0.42; fy < 0.7; fy += 0.02) for (let fx = 0.4; fx < 0.6; fx += 0.02) {
        const p = { clientX: r.left + r.width * fx, clientY: r.top + r.height * fy };
        if (!w.pick(p) && document.elementFromPoint(p.clientX, p.clientY) === w.canvas) return [p.clientX, p.clientY];
      }
    })()`);
  await cdp.eval('agentWorld.wander = () => {}');
  try {
    await home();

    let p = await freeFloor();
    await mouse('mousePressed', p);
    await mouse('mouseReleased', p);
    await sleep(300);
    report('input', 'a real click on the floor keeps the view automatic', (await state()).auto === true, {});

    p = await freeFloor();
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
    p = await freeFloor();
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
  if (PHASES.includes('run')) await run(cdp);
} catch (e) {
  failures++;
  console.error(`FAIL ${e.stack ?? e}`);
} finally {
  if (browser) await closeBrowser(browser);
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
console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
