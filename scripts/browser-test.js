// Browser checks for specs 01, 02 and 03. Starts a demo server of its own, drives a
// headless Edge or Chrome over the DevTools protocol, injects scripts/browser/*.js into
// the page and runs them; exits 1 if any check fails. No dependencies: Node's own fetch
// and WebSocket (Node 22+). The browser comes from scripts/browser/headless.js, the
// temp folders from scripts/lib/temp.js.
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
// (E1-E7 and the N4 variants of the room labels). Spec 03: hygiene (H1-H6: probes
// killed, interrupted and closed, and the sweep of what they leave).
// Expected reds: a check that fails on today's code and is listed in
// scripts/browser/known-red.json, with the ticket that fixes it, is counted apart and
// does not fail the run; listed but passing, it does (its mark must go).
// The server never sees an API key: every key the config names is set to "" (present,
// so .env cannot fill it in), and a run that is not in demo mode is stopped at once.
// At the end no browser process may be left with this run's profile, and no folder.
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { close, launch, profileProcesses, sweep } from './browser/headless.js';
import { launchCommand } from './lib/backend-launcher.js';
import { alive, onExit, ownedDir, ownerOf, removeDir } from './lib/temp.js';

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
const PHASES = (arg('--only') ?? 'hygiene,views,checks,cubes,input,overlaps,labels,run').split(',').filter((p) => !(flag('--skip-run') && p === 'run'));
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
  if (/^H\d$/.test(c)) return 'hygiene';
  return { A6: 'checks', A7: 'checks', A8: 'checks', A9: 'cubes', A10: 'run' }[c] ?? c;
};

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
  const { cmd, args, cwd } = launchCommand(ROOT);
  const server = spawn(cmd, args, { cwd, env, stdio: ['ignore', 'pipe', 'inherit'] });
  server.exited = new Promise((ok) => server.once('exit', ok));
  await new Promise((ok, fail) => {
    server.once('exit', (code) => fail(new Error(`server exited (${code})`)));
    server.stdout.on('data', (d) => d.toString().includes('Agent World') && ok());
  });
  return server;
}
const api = (path, body) => fetch(BASE + path, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {}).then((r) => r.json());

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
// before each action: a click on a room label is a room focus, and a wheel step there
// would reach the canvas only through the labels' hand-over (E7, checked apart). The
// idle agents' strolls are paused meanwhile, so their labels do not cross the point
// between the look-up and the event.
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
      // one wheel step: how much the picture grows, and how far the floor point that was
      // under the pointer ends from it (zoom to the cursor keeps it there)
      const wheel = async (at) => {
        const before = await viewState(cdp);
        const floor = await cdp.eval(`(() => { const f = __t.floorAt({ clientX: ${at[0]}, clientY: ${at[1]} }); return [f.x, f.y, f.z]; })()`);
        await cdp.send('Input.dispatchMouseEvent', { type: 'mouseWheel', x: at[0], y: at[1], deltaX: 0, deltaY: -120 });
        await settleView(cdp);
        const after = await viewState(cdp);
        const drift = await cdp.eval(`(() => { const r = __t.rect(); const [x, y] = __t.toScreen(new __t.V3(${floor.join(', ')})); return Math.hypot(r.left + x - ${at[0]}, r.top + y - ${at[1]}); })()`);
        return { ratio: +(after.scale / before.scale).toFixed(4), auto: after.auto, driftPx: +drift.toFixed(2) };
      };
      const over = await wheel(p);
      await homeView(cdp);
      const canvas = await wheel(await freeFloor(cdp));
      report('E7', name, Math.abs(over.ratio / canvas.ratio - 1) <= 0.02 && over.auto === false && over.driftPx <= canvas.driftPx + 2, { at: p.map(Math.round), overTheLabel: over, overTheCanvas: canvas });
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

// ---------- spec 03: the hygiene of the tools ----------

const PROBE = join(HERE, 'browser', 'probe.js');
// A probe of its own: ready gives its JSON line once its browser answers. Its stdin
// stays open, so it lives until "close" or until this runner goes.
function startProbe(args = []) {
  const child = spawn(process.execPath, [PROBE, ...args], { cwd: ROOT, stdio: ['pipe', 'pipe', 'inherit'] });
  const exited = new Promise((ok) => child.once('exit', (code) => ok(code)));
  const ready = new Promise((ok, fail) => {
    let out = '';
    child.stdout.on('data', (d) => {
      out += d;
      const line = out.split('\n').find((l) => l.startsWith('{') && l.trim().endsWith('}'));
      if (line) ok(JSON.parse(line));
    });
    exited.then((code) => fail(new Error(`a probe exited (${code}) before its browser answered`)));
  });
  return { child, ready, exited };
}
const within = (promise, ms, otherwise) => Promise.race([promise, sleep(ms).then(() => otherwise)]);
// the way a shell time limit or taskkill ends a process: no handler runs (spec 03, §1.2)
function hardKill(pid) {
  if (process.platform === 'win32') spawnSync('taskkill', ['/PID', String(pid), '/F'], { stdio: 'ignore' });
  else process.kill(pid, 'SIGKILL');
}
const processesOf = (profile) => profileProcesses().filter((p) => p.profile === basename(profile));
const deadOwner = (profile) => {
  const owner = ownerOf(profile);
  return Boolean(owner) && !alive(owner.pid);
};
// files under scripts/ that start a browser themselves (H1)
function launchers(dir = HERE) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = join(dir, e.name);
    if (e.isDirectory()) return launchers(p);
    return e.name.endsWith('.js') && readFileSync(p, 'utf8').includes('--remote-debugging-' + 'port') ? [p.slice(HERE.length + 1).replace(/\\/g, '/')] : [];
  });
}

// H1-H6 with real probes: one killed with taskkill /F, then swept by the next start;
// a sweep while runs are alive; a probe closed normally; the Ctrl+C handler; the
// manual sweep. This runner's own browser is one of the live runs.
async function hygiene(ownProfile) {
  const started = Date.now();
  const preview = join(tmpdir(), 'agent-world-preview');
  const previewThere = existsSync(preview);
  const closedBySweeps = [];
  const probes = [];
  const probe = (args) => {
    const p = startProbe(args);
    probes.push(p);
    return p;
  };
  try {
    // H4
    const a = probe();
    const infoA = await a.ready;
    const before = processesOf(infoA.profile).length;
    hardKill(infoA.pid);
    await a.exited;
    await sleep(1000);
    const leftAfterTheKill = processesOf(infoA.profile).length;
    const b = probe(); // the next start: launch() sweeps before its browser starts
    const infoB = await b.ready;
    closedBySweeps.push(...infoB.swept.killed);
    const leftAfterTheNextStart = processesOf(infoA.profile).length;
    report('H4', 'a probe killed with taskkill /F is swept at the next start', before > 0 && leftAfterTheNextStart === 0 && !existsSync(infoA.profile), { browserProcesses: before, leftAfterTheKill, leftAfterTheNextStart, profileLeft: existsSync(infoA.profile), closedByTheNextStart: infoB.swept.killed.length });
    report('H6', 'the sweep at a start takes at most 2 s', infoB.swept.ms <= 2000, { ms: infoB.swept.ms, closed: infoB.swept.killed.length, removed: infoB.swept.removed.length });

    // H5: probe B and this runner are alive while a sweep runs
    const live = new Set([...processesOf(ownProfile), ...processesOf(infoB.profile)].map((p) => p.pid));
    const s = await sweep();
    closedBySweeps.push(...s.killed);
    const touched = s.killed.filter((p) => live.has(p.pid)).map((p) => p.pid);
    const still = { runner: processesOf(ownProfile).length, probe: processesOf(infoB.profile).length };
    report('H5', 'a sweep leaves live runs alone', live.size > 0 && !touched.length && still.runner > 0 && still.probe > 0 && existsSync(ownProfile) && existsSync(infoB.profile) && (!previewThere || existsSync(preview)), { liveProcesses: live.size, closedAmongThem: touched, stillThere: still, previewKept: !previewThere || existsSync(preview) });

    // H2 for a probe: closed normally, it leaves nothing
    b.child.stdin.write('close\n');
    const codeB = await within(b.exited, 20000, 'still running after 20 s');
    report('H2', 'a probe closed normally leaves nothing', codeB === 0 && !processesOf(infoB.profile).length && !existsSync(infoB.profile), { exit: codeB, left: processesOf(infoB.profile).length, profileLeft: existsSync(infoB.profile) });

    // H3: the Ctrl+C handler (the real Ctrl+C is the user's QA: a script cannot send one)
    const c = probe(['--emit', 'SIGINT', '--after', '1500']);
    const infoC = await c.ready;
    const codeC = await within(c.exited, 20000, 'still running after 20 s');
    await sleep(500);
    report('H3', 'the Ctrl+C handler closes the browser and removes the profile', codeC === 130 && !processesOf(infoC.profile).length && !existsSync(infoC.profile), { exit: codeC, left: processesOf(infoC.profile).length, profileLeft: existsSync(infoC.profile) });

    report('H5', 'the sweeps closed only processes of dead owners', closedBySweeps.every((p) => deadOwner(p.profile)), { closed: closedBySweeps });
    const manual = spawnSync(process.execPath, [join(HERE, 'browser', 'headless.js'), '--sweep', '--dry-run'], { cwd: ROOT, encoding: 'utf8' });
    report('H6', 'npm run sweep reports what it would do and exits 0', manual.status === 0 && /^sweep \(dry run\): /.test(manual.stdout), { exit: manual.status, firstLine: manual.stdout.split('\n')[0] });
    const found = launchers();
    report('H1', 'only headless.js starts a browser', found.length === 1 && found[0] === 'browser/headless.js', { found });
  } finally {
    // a probe still there after a failure: stdin closed asks it to close its browser
    for (const p of probes) {
      if (p.child.exitCode !== null || p.child.signalCode !== null) continue;
      p.child.stdin.end();
      if ((await within(p.exited, 15000, 'stuck')) === 'stuck') hardKill(p.child.pid);
    }
  }
  results.hygieneSeconds = Math.round((Date.now() - started) / 1000);
  console.log(`       hygiene in ${results.hygieneSeconds} s`);
}

// ---------- main ----------

const home = ownedDir('browser');
let server;
let browser;
try {
  server = await startServer(home);
  onExit(async () => {
    server.kill();
    await within(server.exited, 5000);
  });
  browser = await launch();
  const cdp = await browser.connect();
  results.browser = browser.exe;
  console.log(`browser checks on ${ROOT} (${TAG}) with ${browser.exe}`);
  if (PHASES.includes('hygiene')) await hygiene(browser.profile);
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
    const { left, others } = await close(browser);
    report('runner', "no browser process left with this run's profile", !left.length, { left: left.map((p) => p.pid) });
    for (const p of others) console.log(`note: browser process ${p.pid} of another run is still there (${p.profile})`);
  }
  if (server) {
    server.kill();
    await within(server.exited, 5000);
  }
  await removeDir(home);
  const leftDirs = [home, browser?.profile].filter((d) => d && existsSync(d));
  report('runner', 'no folder left by this run', !leftDirs.length, { left: leftDirs });
}
if (arg('--json')) writeFileSync(arg('--json'), JSON.stringify(results, null, 2));
const reds = Object.entries(results.expectedReds).map(([k, n]) => `${k}: ${n}`).join(', ');
console.log(`${failures ? `${failures} FAILED` : 'ALL OK'}${reds ? `, expected reds (${reds})` : ''}`);
process.exit(failures ? 1 : 0);
