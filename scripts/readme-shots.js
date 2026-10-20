// The screenshots of README.md (docs/assets/*.png): 1920x1080, demo mode, real missions,
// the app in Italian like the README. Same server, browser module and moment probe as
// scripts/browser-test.js; the server gets a throwaway home folder (USERPROFILE/HOME),
// so the Skill tab lists only the app's own skills, not the plugins installed on this
// machine, and the language setting stays there.
// Two missions: a build (the pizzeria site) and, from spec 11, a deconstruct_and_build
// mission on the demo sample (todo-board): the reverse team, the clean-room rebuild,
// the blueprint and the parity QA.
// Usage: npm run screenshots   (about 8 minutes: two whole demo missions at normal pace)
//        node scripts/readme-shots.js [output dir]   default docs/assets
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { close, launch } from './browser/headless.js';
import { demoEnv, spawnBackend } from './lib/backend-launcher.js';
import { ownedDir, removeDir } from './lib/temp.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const out = resolve(process.argv[2] ?? join(root, 'docs', 'assets'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const PORT = 4396;
const BASE = `http://127.0.0.1:${PORT}`;
const MISSION = 'Il sito completo per il lancio di una pizzeria napoletana a Milano, con brand, immagini e testi';
const REVERSE = "Decodifica l'applicazione esistente e ricostruiscila da zero in clean-room";
const home = ownedDir('shots');
const user = join(home, 'user');
mkdirSync(user);
const env = demoEnv(root, { PORT: String(PORT), AGENT_WORLD_HOME: home, USERPROFILE: user, HOME: user });
delete env.AGENT_WORLD_FAST; // normal pace, as a user sees it
const server = spawnBackend(root, env);
const exited = new Promise((ok) => server.once('exit', ok));
await new Promise((ok, fail) => {
  server.once('exit', (c) => fail(new Error(`server exited (${c})`)));
  server.stdout.on('data', (d) => d.toString().includes('Agent World') && ok());
});
const api = (path, body) => fetch(BASE + path, body ? { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) } : {}).then((r) => r.json());

await api('/api/config', { ui: { language: 'it' } }); // in the throwaway home, before the page loads

const browser = await launch();
mkdirSync(out, { recursive: true });
try {
  const cdp = await browser.connect();
  const shoot = async (name) => {
    const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(out, `${name}.png`), Buffer.from(data, 'base64'));
    console.log('shot', name);
  };
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  await cdp.send('Page.navigate', { url: BASE });
  for (let i = 0; i < 200; i++) {
    await sleep(100);
    if (await cdp.eval('Boolean(window.agentWorld?.actors.size && window.agentWorld.layout)').catch(() => false)) break;
  }
  await sleep(800);
  for (const f of ['lib.js', 'run-probe.js']) await cdp.eval(`${readFileSync(join(root, 'scripts', 'browser', f), 'utf8')}\n;void 0`);
  await cdp.eval('agentWorld.resetView(); window.__checks.runProbe.start()');

  const created = await api('/api/runs', { goal: MISSION });
  if ((await api(`/api/runs/${created.id}`)).mode !== 'demo') throw new Error('not in demo mode: stopped');
  const want = { '3-workers-take-cubes': 'office-3d', '6-delivery': 'mission-tasks' };
  let qa = false;
  const done = ['completed', 'completed_with_failures', 'failed', 'stopped'];
  let over = 0;
  let bay = false;
  const deadline = Date.now() + 12 * 60_000;
  while (Date.now() < deadline) {
    for (const name of await cdp.eval('window.__checks.runProbe.due()')) {
      if (want[name]) await shoot(want[name]);
      if (name === '5-qa-verdict' && !qa) {
        // close-up on the reviewer giving the verdict at the worker's desk
        const id = await cdp.eval("[...agentWorld.actors.values()].find((a) => a.team === 'qa' && a.state && a.state !== 'idle')?.id ?? null");
        if (id) {
          await cdp.eval(`agentWorld.focus(${JSON.stringify(id)})`);
          await sleep(1400);
          await shoot('qa-review');
          await cdp.eval('agentWorld.resetView({ animate: false })');
          qa = true;
        }
      }
      if (name === '4-sub-agent-in-the-bay' && !bay) {
        // close-up: follow a sub-agent working at its seat, then back to the full view
        const id = await cdp.eval("[...agentWorld.actors.values()].find((a) => a.kind === 'sub' && (a.state === 'thinking' || a.state === 'tool'))?.id ?? null");
        if (id) {
          await cdp.eval(`agentWorld.focus(${JSON.stringify(id)})`);
          await sleep(1600);
          await shoot('sub-agents');
          await cdp.eval('agentWorld.resetView({ animate: false })');
          bay = true;
        }
      }
    }
    if (!over) {
      const r = await api(`/api/runs/${created.id}`);
      if (done.includes(r.status)) over = Date.now();
    } else if (Date.now() - over > 5000) break;
    await sleep(250);
  }
  // the tabs, on the finished mission
  for (const [tab, name] of [['skills', 'skill-hub'], ['brain', 'brain'], ['router', 'router']]) {
    await cdp.eval(`document.querySelector('[data-tab="${tab}"]').click()`);
    await sleep(1500);
    await shoot(name);
  }
  await cdp.eval(`document.querySelector('[data-tab="output"]').click()`);
  await sleep(1500);
  await cdp.eval(`document.querySelector('[data-file="REPORT.md"]')?.click()`);
  await sleep(1500);
  await shoot('final-report');
  const closeViewer = () => cdp.eval(`document.querySelector('#viewer [data-act="close-modal"]')?.click()`);
  await closeViewer();

  // spec 11: deconstruct_and_build on the demo sample, phases A-D
  await cdp.eval(`document.querySelector('[data-tab="board"]').click()`);
  await cdp.eval('agentWorld.resetView({ animate: false })');
  const rev = await api('/api/runs', { goal: REVERSE });
  const busy = (test) => cdp.eval(`[...agentWorld.actors.values()].filter((a) => (${test}) && a.state && a.state !== 'idle').length`);
  const taken = new Set();
  let built = 0;
  over = 0;
  const until = Date.now() + 15 * 60_000;
  while (Date.now() < until) {
    const r = await api(`/api/runs/${rev.id}`);
    if (r.phase === 'deconstruct' && !taken.has('reverse-team') && (await busy("a.team === 'reverse'")) >= 1) {
      await cdp.eval("agentWorld.focusRoom('reverse')"); // Kira and Zero at their desks, the scanner
      await sleep(1800);
      await shoot('reverse-team');
      await cdp.eval('agentWorld.resetView({ animate: false })');
      taken.add('reverse-team');
    }
    if (r.phase === 'build' && !taken.has('clean-room-build')) {
      built ||= Date.now();
      if (Date.now() - built > 6000 && (await busy("a.team !== 'reverse' && a.kind !== 'ceo'")) >= 2) {
        await shoot('clean-room-build'); // the badge: deconstruct & rebuild · rebuild
        taken.add('clean-room-build');
      }
    }
    if (r.phase === 'done' && !taken.has('clean-room-messages')) {
      await cdp.eval(`document.querySelector('[data-tab="comms"]').click()`);
      await sleep(1500);
      await shoot('clean-room-messages'); // intent, handover and parity in the messages
      await cdp.eval(`document.querySelector('[data-tab="board"]').click()`);
      taken.add('clean-room-messages');
    }
    if (!over) {
      if (done.includes(r.status)) over = Date.now();
    } else if (Date.now() - over > 5000) break;
    await sleep(250);
  }
  await cdp.eval(`document.querySelector('[data-tab="output"]').click()`);
  for (const [file, name] of [['blueprint.md', 'blueprint'], ['PARITY.md', 'parity-qa']]) {
    await sleep(1500);
    await cdp.eval(`document.querySelector('[data-file="${file}"]')?.click()`);
    await sleep(1500);
    await shoot(name);
    await closeViewer();
  }
  const missing = ['reverse-team', 'clean-room-build', 'clean-room-messages'].filter((n) => !taken.has(n));
  if (missing.length) throw new Error(`moments not seen: ${missing.join(', ')}`);
} finally {
  await close(browser);
  server.kill();
  await exited;
  await removeDir(home);
}
