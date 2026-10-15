// A10 (N12): sub-agents work at their bay seat. The backend starts the work a fixed
// pickupMs (1.8 s) after the assignment, but the trip to the lead and back to the bay
// lasts as long as the path says, and longer when the browser draws under 20 fps
// (frame() caps a step at 0.05 s). The working states that arrive while the sub is
// still on its way must wait for its arrival, as a verdict waits for the reviewer.
// Drives World methods on a fixed 60 fps clock: the same measure on any machine, in
// seconds instead of the three minutes of a real mission. Run it with no mission going.
window.__checks.subSeat = () => {
  const t = window.__t;
  const w = t.w;
  const render = w.renderer.render;
  w.renderer.setAnimationLoop(null);
  w.renderer.render = (scene, camera) => {
    scene.updateMatrixWorld();
    if (camera.parent === null) camera.updateMatrixWorld();
  };
  const team = 'research';
  const lead = [...w.layout.desks.entries()].find(([, d]) => d.team === team && d.kind === 'lead')[0];
  const bays = w.layout.bays.get(team);
  const WORKING = ['thinking', 'tool'];
  let n = 0;
  const sub = (slot) => ({ id: `${team}-subseat${++n}`, name: `Sub ${slot + 1}`, team, kind: 'sub', slot, busy: true, taskId: `ss.${n}`, text: 'Seat check' });
  const dist = (a) => Math.hypot(a.position.x - a.seat.x, a.position.z - a.seat.z);
  // runs the world until the actor has nothing left to do, or 30 s of world time
  const follow = (actor) => {
    const r = { furthest: 0, workingAway: 0, seconds: 0 };
    for (let i = 0; i < 60 * 30 && actor.queue.length; i++) {
      t.pump(1 / 60);
      const d = dist(actor);
      r.furthest = Math.max(r.furthest, +d.toFixed(2));
      if (WORKING.includes(actor.state)) r.workingAway = Math.max(r.workingAway, +d.toFixed(2));
      r.seconds = +((i + 1) / 60).toFixed(2);
    }
    return r;
  };
  const made = [];
  const out = {};
  try {
    // S1: thinking, then a tool step, both while the sub is still walking: the farthest
    // bay seat, as in the reds of N12 (research-sub3)
    {
      const a = sub(bays.length - 1);
      made.push(a);
      w.applyState({ ...a, state: 'idle' }, true);
      const actor = w.actors.get(a.id);
      w.applyState({ ...a, state: 'assigned', target: lead });
      w.applyState({ ...a, state: 'thinking', text: 'Reading the brief' });
      w.applyState({ ...a, state: 'tool', tool: 'read_file', toolTarget: 'brief.md', text: 'Reading the brief' });
      const right = actor.state;
      const r = follow(actor);
      Object.assign(r, { stateRightAfter: right, finalState: actor.state, atSeat: actor.atSeat() });
      // the trip must be real (a sub that never left would prove nothing), the working
      // states must wait for the seat, and the latest one wins
      r.ok = r.furthest > 3 && r.stateRightAfter === 'assigned' && r.workingAway <= 0.5 && r.finalState === 'tool' && r.atSeat;
      out['S1 the working states wait for the sub to reach its bay seat'] = r;
    }
    // S2: a pause during the trip shows at once and drops the working state put aside
    {
      const a = sub(0);
      made.push(a);
      w.applyState({ ...a, state: 'idle' }, true);
      const actor = w.actors.get(a.id);
      w.applyState({ ...a, state: 'assigned', target: lead });
      w.applyState({ ...a, state: 'thinking', text: 'Planning' });
      w.applyState({ ...a, state: 'paused' });
      const right = actor.state;
      const r = follow(actor);
      Object.assign(r, { stateRightAfter: right, finalState: actor.state, atSeat: actor.atSeat() });
      r.ok = r.stateRightAfter === 'paused' && r.finalState === 'paused' && r.atSeat;
      out['S2 a pause during the trip shows at once and drops the waiting state'] = r;
    }
    // S3: once seated, the working states apply at once (nothing waits for nothing)
    {
      const a = made[0];
      const actor = w.actors.get(a.id);
      w.applyState({ ...a, state: 'thinking', text: 'Next step' });
      const r = { state: actor.state, atSeat: actor.atSeat(), queue: actor.queue.length };
      r.ok = r.state === 'thinking' && r.atSeat && r.queue === 0;
      out['S3 a seated sub starts working at once'] = r;
    }
  } finally {
    for (const a of made) {
      w.removeActor(a.id);
      const cube = w.cubes.get(a.taskId);
      if (cube) {
        cube.mesh.parent?.remove(cube.mesh);
        w.cubes.delete(a.taskId);
      }
    }
    w.renderer.render = render;
    w.renderer.setAnimationLoop(() => w.frame());
  }
  return out;
};
