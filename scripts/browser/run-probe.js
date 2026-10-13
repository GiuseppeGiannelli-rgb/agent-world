// A10 (S6): watches a whole mission at real pace, the way T0 and T2 did.
// - the cube life cycle: pickups, splits, takes, deliveries, drops, sinks;
// - cube anomalies every 250 ms (the A9 orphan rules; a cube being delivered or sunk
//   may stay in the scene for 2 s of world time: frame() caps a step at 0.05 s, so a
//   browser drawing fewer than 20 fps runs the world slower than the clock);
// - every QA verdict: how far the reviewer stands from the agent reviewed when the
//   bubble shows, and how long after the event;
// - sub-agents: how far from their bay seat they go while busy;
// - effects left frozen in the scene once the run is over (N1);
// - the key moments of S6.2, so that the runner can take a screenshot of each.
// start() before the mission begins, report() once it is over.
window.__checks.runProbe = {
  start() {
    const w = window.agentWorld;
    const proto = Object.getPrototypeOf(w);
    const now = () => performance.now();
    const isCube = (o) => o?.isMesh && (o.userData.cube || (o.geometry?.type === 'BoxGeometry' && o.children.length === 1 && o.children[0].material?.blending === 2));
    const HAND = [0, 0.86, 0.42];
    const P = {
      counts: { pickup: 0, split: 0, take: 0, deliver: 0, drop: 0, sink: 0, spawn: 0, despawn: 0 },
      anomalies: new Map(), // kind:id -> first seen (s from start)
      verdicts: [],
      pending: new Map(), // reviewer -> [{ target, verdict, at }]
      subs: {}, // sub id -> { busyMax, workingMax }
      leaving: new Map(), // mesh being delivered or sunk -> since
      moments: [], // { name, at } due for a screenshot
      taken: new Set(),
      t0: now(),
      frames: 0,
      sim: 0, // world seconds, as Fx.update is stepped
    };
    const fxUpdate = w.fx.update;
    w.fx.update = function (dt) {
      P.sim += dt;
      return fxUpdate.call(this, dt);
    };
    const geometry = (type) => w.scene.children.filter((o) => o.isMesh && o.geometry?.type === type).length;
    P.before = { rings: geometry('RingGeometry'), sparkles: geometry('OctahedronGeometry') };
    window.__probe = P;
    const moment = (name, delayMs) => {
      if (P.taken.has(name) || P.moments.some((m) => m.name === name)) return;
      P.moments.push({ name, at: now() + delayMs });
    };
    const wrap = (name, before) => {
      w[name] = function (...args) {
        before(...args);
        return proto[name].apply(this, args);
      };
    };
    wrap('onPlan', () => moment('1-plan-on-the-board', 2600));
    wrap('pickupWs', () => P.counts.pickup++);
    wrap('splitWs', () => {
      P.counts.split++;
      moment('2-split-into-cubes', 900);
    });
    wrap('takeTaskCube', () => {
      P.counts.take++;
      moment('3-workers-take-cubes', 600);
    });
    wrap('dropCube', () => P.counts.drop++);
    wrap('deliverCube', (key) => {
      const c = w.cubes.get(key);
      if (!c) return;
      P.counts.deliver++;
      P.leaving.set(c.mesh, P.sim);
      moment('6-delivery', 500);
    });
    wrap('sinkCube', (key) => {
      const c = w.cubes.get(key);
      if (!c) return;
      P.counts.sink++;
      P.leaving.set(c.mesh, P.sim);
    });
    wrap('onSpawn', () => P.counts.spawn++);
    wrap('onDespawn', () => P.counts.despawn++);
    wrap('onRunDone', () => moment('7-run-over', 3000));
    wrap('applyState', (a, initial) => {
      if (initial || a.state !== 'verdict') return;
      if (!P.pending.has(a.id)) P.pending.set(a.id, []);
      P.pending.get(a.id).push({ target: a.target, verdict: a.verdict, at: now() });
    });
    wrap('bubble', (id, html) => {
      if (!/^(✔️|✖️)/.test(html)) return;
      const v = P.pending.get(id)?.shift();
      if (!v) return;
      const a = w.actors.get(id);
      const b = w.actors.get(v.target);
      P.verdicts.push({ reviewer: id, target: v.target, verdict: v.verdict, distance: a && b ? +Math.hypot(a.position.x - b.position.x, a.position.z - b.position.z).toFixed(2) : null, delayS: +((now() - v.at) / 1000).toFixed(2) });
      moment('5-qa-verdict', 250);
    });
    // frames drawn, to tell a slow browser (the client falls behind, N2) from a defect
    const frame = proto.frame;
    w.frame = function () {
      P.frames++;
      return frame.call(this);
    };
    w.renderer.setAnimationLoop(() => w.frame());

    P.timer = setInterval(() => {
      const s = +((now() - P.t0) / 1000).toFixed(1);
      const note = (kind, id) => P.anomalies.has(`${kind}:${id}`) || P.anomalies.set(`${kind}:${id}`, s);
      const live = new Set([...w.cubes.values()].map((c) => c.mesh));
      for (const a of w.actors.values()) {
        if (a.carrying && !live.has(a.carrying)) note('carrying a cube that is gone', a.id);
        for (const ch of a.root.children) if (isCube(ch) && ch !== a.carrying) note('cube attached, not carried', a.id);
        const m = a.carrying;
        if (m && m.parent === a.root && Math.hypot(...m.position.toArray().map((v, i) => v - HAND[i])) > 0.05) note('carried cube off the hand', a.id);
        if (a.kind === 'sub') {
          const r = (P.subs[a.id] ??= { busyMax: 0, workingMax: 0 });
          const d = Math.hypot(a.position.x - a.seat.x, a.position.z - a.seat.z);
          if (a.state && a.state !== 'idle') r.busyMax = Math.max(r.busyMax, +d.toFixed(2));
          if (a.state === 'thinking' || a.state === 'tool') {
            r.workingMax = Math.max(r.workingMax, +d.toFixed(2));
            if (d < 0.3) moment('4-sub-agent-in-the-bay', 400);
          }
        }
      }
      for (const ch of w.scene.children) {
        if (!isCube(ch) || live.has(ch)) continue;
        const since = P.leaving.get(ch);
        if (since === undefined) note('cube in the scene outside world.cubes', ch.uuid.slice(0, 8));
        else if (P.sim - since > 2) note(`cube still leaving after ${(P.sim - since).toFixed(1)} s of world time`, ch.uuid.slice(0, 8));
      }
    }, 250);
    return true;
  },
  // Screenshots whose moment has come; the runner takes them and calls back.
  due() {
    const P = window.__probe;
    const t = performance.now();
    const due = P.moments.filter((m) => m.at <= t && !P.taken.has(m.name)).map((m) => m.name);
    for (const name of due) P.taken.add(name);
    return due;
  },
  report() {
    const w = window.agentWorld;
    const P = window.__probe;
    clearInterval(P.timer);
    const geometry = (type) => w.scene.children.filter((o) => o.isMesh && o.geometry?.type === type).length;
    const isCube = (o) => o?.isMesh && o.userData.cube;
    const verdictDistances = P.verdicts.map((v) => v.distance).filter((d) => d !== null);
    const seconds = (performance.now() - P.t0) / 1000;
    return {
      seconds: +seconds.toFixed(1),
      fps: +(P.frames / seconds).toFixed(1),
      worldSpeed: +(P.sim / seconds).toFixed(2), // 1 when the browser keeps up with the clock
      counts: P.counts,
      anomalies: [...P.anomalies.entries()].map(([k, s]) => `${k} @${s}s`),
      cubesLeft: w.cubes.size + w.scene.children.filter(isCube).length,
      actorsCarrying: [...w.actors.values()].filter((a) => a.carrying).map((a) => a.id),
      activeEffects: w.fx.items.length,
      frozenRings: geometry('RingGeometry') - P.before.rings,
      frozenSparkles: geometry('OctahedronGeometry') - P.before.sparkles,
      verdicts: { total: P.verdicts.length, pass: P.verdicts.filter((v) => v.verdict === 'pass').length, notShown: [...P.pending.values()].reduce((n, l) => n + l.length, 0), distanceMin: Math.min(...verdictDistances), distanceMax: Math.max(...verdictDistances), delayMaxS: Math.max(...P.verdicts.map((v) => v.delayS)) },
      subs: P.subs,
    };
  },
};
