// Checks the parts of the 3D world that run without a browser:
// the effect loop (one tracked motion per object, nested effects).
import assert from 'node:assert/strict';
import * as THREE from 'three';
import { Fx } from '../public/js/world/fx.js';

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
  fx.track(obj, { update: () => (updates++, true), dispose: () => disposed++ });
  step(fx, 0.1);
  const seen = updates;
  fx.stop(obj);
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

console.log('ALL OK');
