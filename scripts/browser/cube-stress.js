// A9 (T0, T2): forces the cube races R1-R5 by calling World methods directly and
// checks for orphans 1-2 s later. Run it with no mission going. It needs nothing that
// spec 01 added, so it measures the code of any commit the same way.
// Orphans: an actor carrying a cube that is no longer in world.cubes, a cube attached
// to an actor that is not the one it carries, a carried cube away from the hand, a
// cube left in the scene outside world.cubes (deliveries and sinks end within 1.5 s).
window.__checks.cubeStress = async () => {
  const t = window.__t;
  const w = t.w;
  const render = w.renderer.render;
  w.renderer.setAnimationLoop(null);
  w.renderer.render = (scene, camera) => {
    scene.updateMatrixWorld();
    if (camera.parent === null) camera.updateMatrixWorld();
  };
  // userData.cube is T2's marker; older code is recognised by the cube's glow child
  const isCube = (o) => o?.isMesh && (o.userData.cube || (o.geometry?.type === 'BoxGeometry' && o.children.length === 1 && o.children[0].material?.blending === 2));
  const desks = [...w.layout.desks.entries()];
  const leadOf = (team) => desks.find(([, d]) => d.team === team && d.kind === 'lead')[0];
  const workersOf = (team) => desks.filter(([, d]) => d.team === team && d.kind === 'worker').map(([id]) => id);
  const HAND = [0, 0.86, 0.42];
  const check = () => {
    const live = new Set([...w.cubes.values()].map((c) => c.mesh));
    const r = { carryingStale: [], attachedNotCarried: [], strayInScene: 0, carriedOffHand: [] };
    for (const a of w.actors.values()) {
      if (a.carrying && !live.has(a.carrying)) r.carryingStale.push(a.id);
      for (const ch of a.root.children) if (isCube(ch) && ch !== a.carrying) r.attachedNotCarried.push(a.id);
      const m = a.carrying;
      if (m && m.parent === a.root && Math.hypot(...m.position.toArray().map((v, i) => v - HAND[i])) > 0.05) r.carriedOffHand.push(`${a.id}@${m.position.toArray().map((n) => n.toFixed(1)).join(',')}`);
    }
    for (const ch of w.scene.children) if (isCube(ch) && !live.has(ch)) r.strayInScene++;
    r.ok = !r.carryingStale.length && !r.attachedNotCarried.length && !r.strayInScene && !r.carriedOffHand.length;
    return r;
  };
  const clean = () => {
    for (const a of w.actors.values()) {
      for (const ch of [...a.root.children]) if (isCube(ch)) a.root.remove(ch);
      a.carrying = null;
    }
    for (const ch of [...w.scene.children]) if (isCube(ch)) w.scene.remove(ch);
    w.cubes.clear();
  };
  const out = {};
  try {
    clean();
    // R1: a split flight (6th task, 0.9 s) overtaken by a carry flight (0.45 s)
    {
      const lead = leadOf('dev');
      const [wk] = workersOf('dev');
      w.splitWs('r1', lead, Array.from({ length: 6 }, (_, i) => ({ id: `r1.${i}`, team: 'dev' })));
      t.pump(0.05);
      w.takeTaskCube(w.actors.get(wk), 'r1.5');
      t.pump(1.5);
      out['R1 split overtaken by a carry'] = check();
      clean();
    }
    // R2: the workstream pickup is still flying when the subtasks arrive
    {
      const lead = leadOf('content');
      const la = w.actors.get(lead);
      la.queue.length = 0;
      w.pickupWs(la, 'r2');
      t.pump(0.05);
      w.onSubtasks({ runId: w.runId, wsId: 'r2', leadId: lead, tasks: [{ id: 'r2.0', team: 'content', title: 'stress', status: 'queued' }] });
      t.pump(2);
      out['R2 pickup still flying at the split'] = check();
      clean();
      w.removeCard('r2.0');
      w.tasks.delete('r2.0');
    }
    // R3: delivered (a) and sunk (b) while the carry flight is still running
    {
      const [wa] = workersOf('design');
      const [wb] = workersOf('genai');
      w.takeTaskCube(w.actors.get(wa), 'r3a');
      t.pump(0.05);
      w.deliverCube('r3a');
      w.takeTaskCube(w.actors.get(wb), 'r3b');
      t.pump(0.05);
      w.sinkCube('r3b');
      t.pump(2);
      out['R3 delivered or sunk mid-carry'] = check();
      clean();
    }
    // R4: the run is reset while a carry flight is still running
    {
      const [wk] = workersOf('qa');
      w.takeTaskCube(w.actors.get(wk), 'r4');
      t.pump(0.05);
      w.resetRun(w.runId);
      t.pump(1);
      out['R4 run reset mid-carry'] = check();
      clean();
    }
    // R5: an actor takes a second cube while still holding the first one
    {
      const [wk] = workersOf('prompt');
      const a = w.actors.get(wk);
      w.takeTaskCube(a, 'r5a');
      t.pump(0.7);
      w.takeTaskCube(a, 'r5b');
      t.pump(1);
      const r = check();
      r.firstOnDesk = w.cubes.get('r5a')?.mesh.parent === w.scene;
      r.secondInHand = a.carrying === w.cubes.get('r5b')?.mesh && a.carrying?.parent === a.root;
      r.ok &&= r.firstOnDesk && r.secondInHand;
      out['R5 second cube while holding one'] = r;
      clean();
    }
  } finally {
    clean();
    delete w.clock.getDelta;
    w.renderer.render = render;
    w.renderer.setAnimationLoop(() => w.frame());
  }
  return out;
};
