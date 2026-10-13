// A1 as T0 measured it: how much of the office ends up under the UI in the view on
// screen now. It only reads the camera and the DOM, so it measures the code of any
// commit the same way (spec 01, report "Prima" and "Dopo").
// - floor: a grid at 0.5 over the floor (y 0); a point is covered when it falls under
//   .topbar, #left, #right, #roster or #minimap, or off the canvas;
// - zones: the same over each team room at y 1, the topbar not counted;
// - envelope: the 11 points of the diorama's outer box (office.js ENVELOPE) under the
//   UI or off the canvas, and the office width on screen.
// The *Obstacles figures leave the minimap out: it is not an obstacle for the framing
// (S1.2), A1 is measured on them; the others count it, as T0 did.
window.__checks.coverage = () => {
  const w = window.agentWorld;
  const camera = w.camera;
  camera.updateMatrixWorld();
  const cr = w.canvas.getBoundingClientRect();
  const ui = {};
  for (const [name, sel] of Object.entries({ topbar: '.topbar', left: '#left', right: '#right', roster: '#roster', minimap: '#minimap' })) {
    const r = document.querySelector(sel)?.getBoundingClientRect();
    if (r && r.width > 0 && r.height > 0) ui[name] = r;
  }
  const v = new w.controls.target.constructor();
  const project = (x, y, z) => {
    v.set(x, y, z).project(camera);
    return [cr.left + ((v.x + 1) / 2) * cr.width, cr.top + ((1 - v.y) / 2) * cr.height];
  };
  const under = ([x, y], names) => {
    if (x < cr.left || x > cr.right || y < cr.top || y > cr.bottom) return 'offscreen';
    return names.find((n) => ui[n] && x >= ui[n].left && x <= ui[n].right && y >= ui[n].top && y <= ui[n].bottom) ?? null;
  };
  const pct = (n, of) => +((100 * n) / of).toFixed(1);
  const all = Object.keys(ui);
  const grid = (x0, x1, z0, z1, y, names) => {
    const by = {};
    let n = 0;
    let covered = 0;
    for (let x = x0; x <= x1 + 1e-9; x += 0.5) {
      for (let z = z0; z <= z1 + 1e-9; z += 0.5) {
        n++;
        const hit = under(project(x, y, z), names);
        if (hit) {
          covered++;
          by[hit] = (by[hit] ?? 0) + 1;
        }
      }
    }
    return { pct: pct(covered, n), by: Object.fromEntries(Object.entries(by).map(([k, c]) => [k, pct(c, n)])) };
  };
  const floor = grid(-24, 24, -17, 17, 0, all);
  const obstacles = all.filter((n) => n !== 'minimap');
  const zones = {};
  for (const r of w.layout.rooms) {
    const z = grid(r.x - r.w / 2, r.x + r.w / 2, r.z - r.d / 2, r.z + r.d / 2, 1, all.filter((n) => n !== 'topbar'));
    if (z.pct > 0) zones[r.team] = z.pct;
  }
  // office.js ENVELOPE, copied so that commits without it are measured alike
  const envelope = [];
  for (const x of [-24.65, 24.65]) for (const z of [-17.65, 17.65]) for (const y of [-1.66, 0]) envelope.push([x, y, z]);
  envelope.push([-24.45, 5.14, -17.45], [24.45, 5.14, -17.45], [-24.45, 5.14, 17.45]);
  const px = envelope.map((p) => project(...p));
  return {
    floorCoveredPct: floor.pct,
    floorBy: floor.by,
    floorUnderObstaclesPct: grid(-24, 24, -17, 17, 0, obstacles).pct,
    zonesCoveredPct: zones,
    envelopeUnderUi: px.filter((p) => under(p, all)).length,
    envelopeUnderObstacles: px.filter((p) => under(p, obstacles)).length,
    officeWidthPx: Math.round(Math.max(...px.map(([x]) => x)) - Math.min(...px.map(([x]) => x))),
  };
};
