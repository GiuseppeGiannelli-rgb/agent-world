// Checks the parts of the 3D world that run without a browser: the effect loop
// (one tracked motion per object, nested effects) and the camera framing math.
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { applyFrustum, CLOSEST_UNITS_PER_PX, fitOffice, GAP, MARGIN, maxZoomFor, MIN_ZOOM, REF_UNITS_PER_PX, safeRect, scaleAt, VIEW_OFFSET, zoomFor } from '../public/js/world/framing.js';
import { Fx } from '../public/js/world/fx.js';
import { ENVELOPE } from '../public/js/world/office.js';

const v = (x, y, z) => new THREE.Vector3(x, y, z);
const step = (fx, seconds, dt = 1 / 60) => {
  for (let t = 0; t < seconds; t += dt) fx.update(dt);
};
const near = (obj, p) => obj.position.distanceTo(p) < 1e-6;

// 1. a fly lands once at its destination and leaves nothing behind
{
  const fx = new Fx(new THREE.Scene());
  const obj = new THREE.Object3D();
  let done = 0;
  fx.fly(obj, () => v(4, 0, 0), { duration: 0.5, done: () => done++ });
  step(fx, 1);
  assert.equal(done, 1);
  assert.ok(near(obj, v(4, 0, 0)));
  assert.equal(fx.items.length, 0);
  assert.equal(fx.tracks.has(obj), false);
  console.log('ok  fly lands once');
}

// 2. a second fly on the same object takes over: the first never calls done
{
  const fx = new Fx(new THREE.Scene());
  const obj = new THREE.Object3D();
  let first = 0;
  let second = 0;
  fx.fly(obj, () => v(4, 0, 0), { duration: 0.5, done: () => first++ });
  step(fx, 0.2);
  fx.fly(obj, () => v(0, 0, 4), { duration: 0.5, done: () => second++ });
  step(fx, 1);
  assert.equal(first, 0);
  assert.equal(second, 1);
  assert.ok(near(obj, v(0, 0, 4)));
  assert.equal(fx.items.length, 0);
  console.log('ok  a newer fly cancels the older one');
}

// 3. stop cancels for good: no more updates, no done, dispose exactly once
{
  const fx = new Fx(new THREE.Scene());
  const obj = new THREE.Object3D();
  let updates = 0;
  let disposed = 0;
  const item = fx.track(obj, { update: () => (updates++, true), dispose: () => disposed++ });
  step(fx, 0.1);
  assert.equal(fx.active(obj), item);
  const seen = updates;
  fx.stop(obj);
  assert.equal(fx.active(obj), undefined);
  fx.stop(obj);
  step(fx, 0.1);
  assert.equal(updates, seen);
  assert.equal(disposed, 1);
  assert.equal(fx.items.length, 0);

  let done = 0;
  fx.fly(obj, () => v(1, 0, 0), { duration: 0.5, done: () => done++ });
  step(fx, 0.1);
  fx.stop(obj);
  step(fx, 1);
  assert.equal(done, 0);
  console.log('ok  stop cancels without done');
}

// 4. objects do not cancel each other; stopping a finished motion is harmless
{
  const fx = new Fx(new THREE.Scene());
  const a = new THREE.Object3D();
  const b = new THREE.Object3D();
  let landed = 0;
  fx.fly(a, () => v(1, 0, 0), { duration: 0.3, done: () => landed++ });
  fx.fly(b, () => v(2, 0, 0), { duration: 0.3, done: () => landed++ });
  fx.stop(a);
  step(fx, 0.5);
  assert.equal(landed, 1);
  assert.ok(near(b, v(2, 0, 0)));
  fx.stop(b);
  fx.fly(b, () => v(3, 0, 0), { duration: 0.3, done: () => landed++ });
  step(fx, 0.5);
  assert.equal(landed, 2);
  assert.ok(near(b, v(3, 0, 0)));
  console.log('ok  motions are per object');
}

// 5. effects started while the loop runs are kept, start on the next frame and clean up
{
  const scene = new THREE.Scene();
  const fx = new Fx(scene);
  let nested = 0;
  fx.add({
    update: () => {
      fx.add({ update: () => (nested++, nested < 3) });
      return false;
    },
  });
  fx.update(1 / 60);
  assert.equal(nested, 0, 'a nested effect waits for the next frame');
  step(fx, 0.1);
  assert.equal(nested, 3);

  // the real cases: a beam's arrival ring and the sparkle in a delivery's done
  fx.beam(() => v(0, 1, 0), () => v(3, 1, 0), '#ffffff', { duration: 0.2 });
  const cube = new THREE.Object3D();
  fx.fly(cube, () => v(0, 2, -5), { duration: 0.2, done: () => fx.sparkle(cube.position, '#3fbf6f') });
  step(fx, 3);
  assert.equal(fx.items.length, 0);
  assert.equal(scene.children.length, 0, 'nested effects remove their meshes');
  console.log('ok  nested effects run and clean up');
}

// 6. a fly started in the done of a fly on the same object really starts
{
  const fx = new Fx(new THREE.Scene());
  const obj = new THREE.Object3D();
  let hops = 0;
  fx.fly(obj, () => v(1, 0, 0), {
    duration: 0.2,
    done: () => fx.fly(obj, () => v(2, 0, 0), { duration: 0.2, done: () => hops++ }),
  });
  step(fx, 1);
  assert.equal(hops, 1);
  assert.ok(near(obj, v(2, 0, 0)));
  assert.equal(fx.tracks.has(obj), false);
  console.log('ok  chained flies on one object');
}

// 7. an effect that throws is dropped and reported; the others go on, nothing is lost
{
  const fx = new Fx(new THREE.Scene());
  const obj = new THREE.Object3D();
  const errors = [];
  const error = console.error;
  console.error = (e) => errors.push(e);
  try {
    let before = 0;
    let after = 0;
    let disposed = 0;
    fx.add({ update: () => (before++, before < 10) });
    fx.track(obj, { update: () => { throw new Error('boom'); }, dispose: () => disposed++ });
    fx.add({ update: () => (after++, after < 10) });
    step(fx, 0.5);
    assert.equal(errors.length, 1);
    assert.equal(errors[0].message, 'boom');
    assert.equal(disposed, 1, 'the effect that threw is retired');
    assert.equal(fx.active(obj), undefined, 'no stale motion left for a newer move to inherit');
    assert.equal(before, 10, 'the effect before it keeps running');
    assert.equal(after, 10, 'the effect after it keeps running');
    assert.equal(fx.items.length, 0);
  } finally {
    console.error = error;
  }
  console.log('ok  an effect that throws is dropped, the others go on');
}

// ---------- framing ----------

// The UI as app.css lays it out: topbar down to 58 px, roster 62 px tall at the
// bottom, panels 330/400 px wide (300/360 at <=1250 px) with a 12 px margin, and
// panels ignored as full-screen overlays at <=900 px.
function cssInsets(width, { left, right }) {
  if (width <= 900) return { top: 54, right: 0, bottom: 58, left: 0 };
  const small = width <= 1250;
  return { top: 58, right: right ? 12 + (small ? 360 : 400) : 0, bottom: 62, left: left ? 12 + (small ? 300 : 330) : 0 };
}
function cameraFor(fit, width, height, zoom = 1) {
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 400);
  camera.position.copy(fit.position);
  camera.lookAt(fit.target);
  camera.zoom = zoom;
  applyFrustum(camera, width, height, fit.unitsPerPx, fit.lensX, fit.lensY);
  camera.updateMatrixWorld();
  return camera;
}
const toPx = (camera, p, width, height) => {
  const n = p.clone().project(camera);
  return [((n.x + 1) / 2) * width, ((1 - n.y) / 2) * height];
};
const SIZES = [[1920, 1080], [2560, 1440], [1440, 900], [1280, 800], [800, 600]];
const PANELS = [{ left: true, right: true }, { left: true, right: false }, { left: false, right: true }, { left: false, right: false }];
const cases = SIZES.flatMap(([width, height]) => PANELS.map((panels) => ({ width, height, panels, insets: cssInsets(width, panels) })));

// 8. A1: the whole office lands inside the free area, centred, filling the tighter axis
{
  for (const { width, height, panels, insets } of cases) {
    const name = `${width}x${height} ${panels.left ? 'L' : '-'}${panels.right ? 'R' : '-'}`;
    const fit = fitOffice({ width, height, insets, envelope: ENVELOPE });
    const s = fit.safe;
    assert.equal(s.fallback, false, name);
    assert.ok(Math.abs(fit.target.y) < 1e-9, `${name}: target on the floor`);
    assert.ok(fit.position.clone().sub(fit.target).distanceTo(VIEW_OFFSET) < 1e-9, `${name}: same camera angle`);
    const px = ENVELOPE.map((p) => toPx(cameraFor(fit, width, height), p, width, height));
    const xs = px.map(([x]) => x);
    const ys = px.map(([, y]) => y);
    const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    assert.ok(minX >= s.x0 - 1 && maxX <= s.x1 + 1 && minY >= s.y0 - 1 && maxY <= s.y1 + 1, `${name}: inside the free area`);
    assert.ok(Math.abs((minX + maxX) / 2 - s.cx) <= 2 && Math.abs((minY + maxY) / 2 - s.cy) <= 2, `${name}: centred`);
    const fill = Math.max((maxX - minX) / s.w, (maxY - minY) / s.h);
    assert.ok(fill >= 0.95 && fill <= 1, `${name}: fills ${(fill * 100).toFixed(1)}% of the tighter axis`);
    assert.ok(Math.abs(fill - 1 / (1 + MARGIN)) < 1e-6, `${name}: margin`);
  }
  console.log(`ok  office framed in the free area (${cases.length} layouts)`);
}

// 9. A2 + A3: the target stays at the centre of the free area at any zoom,
//    and one px of drag moves the picture by exactly one px (pan stays 1:1)
{
  for (const { width, height, insets } of cases) {
    const fit = fitOffice({ width, height, insets, envelope: ENVELOPE });
    for (const zoom of [0.5, 1, 2.2, 4]) {
      const camera = cameraFor(fit, width, height, zoom);
      const [x, y] = toPx(camera, fit.target, width, height);
      assert.ok(Math.abs(x - fit.safe.cx) <= 1 && Math.abs(y - fit.safe.cy) <= 1, `${width}x${height} zoom ${zoom}: target at the centre`);
      // what OrbitControls uses for an orthographic pan, against the real px size
      const panUnitsPerPx = (camera.right - camera.left) / camera.zoom / width;
      assert.ok(Math.abs(panUnitsPerPx - fit.unitsPerPx / zoom) < 1e-12);
      const screenRight = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const [x2] = toPx(camera, fit.target.clone().addScaledVector(screenRight, panUnitsPerPx * 100), width, height);
      assert.ok(Math.abs(x2 - x - 100) < 1e-6, `${width}x${height} zoom ${zoom}: 100 px of pan moves the picture 100 px`);
    }
  }
  console.log('ok  target fixed under zoom, pan 1:1 with the lens shift');
}

// 10. A4: a window too small for its panels frames the whole canvas
{
  const insets = cssInsets(1920, { left: true, right: true });
  const s = safeRect(640, 480, insets);
  assert.equal(s.fallback, true);
  assert.deepEqual([s.x0, s.y0, s.x1, s.y1], [GAP, GAP, 640 - GAP, 480 - GAP]);
  const fit = fitOffice({ width: 640, height: 480, insets, envelope: ENVELOPE });
  const px = ENVELOPE.map((p) => toPx(cameraFor(fit, 640, 480), p, 640, 480));
  assert.ok(px.every(([x, y]) => x >= 0 && x <= 640 && y >= 0 && y <= 480));
  assert.equal(safeRect(1920, 1080, insets).fallback, false);
  // degenerate sizes never produce NaN
  assert.ok(Number.isFinite(fitOffice({ width: 0, height: 0, insets, envelope: ENVELOPE }).unitsPerPx));
  console.log('ok  small windows ignore the panels');
}

// 11. the reference scale is the old framing at 1920x1080 (62 units across)
assert.ok(Math.abs(REF_UNITS_PER_PX - Math.max(31, 62 / (1920 / 1080)) / 1080) < 1e-12);

// 12. A8 + S2.5: close-ups keep their old size on screen whatever the framing, and
//     the zoom limit moves with the projection, so no camera move is ever clipped
{
  const REF = REF_UNITS_PER_PX;
  const close = (a, b) => Math.abs(a / b - 1) < 1e-12;
  assert.equal(maxZoomFor(REF), 4); // the old fixed framing: the old limit
  for (const { width, height, insets } of cases) {
    const u = fitOffice({ width, height, insets, envelope: ENVELOPE }).unitsPerPx;
    const tag = `${width}x${height} ${insets.left ? 'L' : '-'}${insets.right ? 'R' : '-'}`;
    assert.ok(close(u / maxZoomFor(u), CLOSEST_UNITS_PER_PX), `${tag}: closest close-up as before`);
    assert.ok(close(u / zoomFor(REF / 2.2, u), REF / 2.2), `${tag}: agent focus as before`);
    assert.ok(close(u / zoomFor(REF / 2, u), REF / 2), `${tag}: room focus as before`);
    assert.equal(zoomFor(REF / 10, u), maxZoomFor(u)); // closer than allowed
    assert.equal(zoomFor(u * 5, u), MIN_ZOOM); // farther than allowed
  }
  assert.equal(maxZoomFor(CLOSEST_UNITS_PER_PX / 2), 1); // a huge screen still reaches the fit

  // The trap: OrbitControls.update() clamps camera.zoom into [minZoom, maxZoom] every
  // frame. A move eases zoom and unitsPerPx geometrically (scaleAt); a limit that follows
  // the eased unitsPerPx holds at every step (in logarithms the bound is linear in the
  // same parameter), while a limit set once for the end of the move cuts the zoom short.
  const scales = [...new Set(cases.map(({ width, height, insets }) => fitOffice({ width, height, insets, envelope: ENVELOPE }).unitsPerPx))];
  let stepsChecked = 0;
  let clippedByFinalLimit = 0;
  for (const u0 of scales) {
    for (const u1 of scales) {
      for (const z0 of [MIN_ZOOM, 1, maxZoomFor(u0)]) {
        for (const z1 of [MIN_ZOOM, 1, maxZoomFor(u1)]) {
          for (let i = 0; i <= 20; i++) {
            const e = i / 20;
            const u = scaleAt(u0, u1, e);
            const z = scaleAt(z0, z1, e);
            assert.ok(z >= MIN_ZOOM - 1e-12 && z <= maxZoomFor(u) * (1 + 1e-12), `zoom ${z} within the limit of ${u}`);
            if (z > maxZoomFor(u1) * (1 + 1e-12)) clippedByFinalLimit++;
            stepsChecked++;
          }
        }
      }
    }
  }
  assert.ok(clippedByFinalLimit > 0, 'the check can tell a limit set for the end of the move');
  console.log(`ok  close-ups at the old size, zoom limit follows the projection (${stepsChecked} steps; a fixed end limit would clip ${clippedByFinalLimit})`);
}

// 13. review R5: a camera move changes the size on screen by equal ratios, at the pace
//     of its ease like the target, instead of rushing at the start of a zoom in
{
  assert.equal(scaleAt(0.7, 3.1, 0), 0.7);
  assert.equal(scaleAt(0.7, 3.1, 1), 3.1, 'a move ends exactly where it heads');
  // the size on screen (unitsPerPx / zoom) is geometric: halfway is the geometric mean
  const [u0, u1, z0, z1] = [0.05, 0.03, 1, 3.6];
  const size = (e) => scaleAt(u0, u1, e) / scaleAt(z0, z1, e);
  assert.ok(Math.abs(size(0.5) / Math.sqrt(size(0) * size(1)) - 1) < 1e-12);
  // a focus from the full view, both panels open at 1920x1080: the first frame of the
  // 0.7 s cubic ease covers the same share of the zoom (in ratio) as of the way
  const u = fitOffice({ width: 1920, height: 1080, insets: cssInsets(1920, { left: true, right: true }), envelope: ENVELOPE }).unitsPerPx;
  const zoom = zoomFor(REF_UNITS_PER_PX / 2.2, u);
  const e1 = 1 - (1 - 1 / 60 / 0.7) ** 3;
  const share = (z) => Math.log(z) / Math.log(zoom);
  assert.ok(Math.abs(share(scaleAt(1, zoom, e1)) - e1) < 1e-12, 'zoom and target keep the same pace');
  const linear = 1 + (zoom - 1) * e1;
  assert.ok(share(linear) > 1.5 * e1, 'the check can tell the old linear zoom');
  console.log(`ok  zoom eased in ratio: first frame of a focus +${((scaleAt(1, zoom, e1) - 1) * 100).toFixed(1)}% (linear: +${((linear - 1) * 100).toFixed(1)}%)`);
}

console.log('ALL OK');
