import * as THREE from 'three';

// Short-lived visual effects. Each effect returns false from update() when done.
export class Fx {
  constructor(scene) {
    this.scene = scene;
    this.items = [];
  }

  add(item) {
    this.items.push(item);
    return item;
  }

  update(dt) {
    this.items = this.items.filter((fx) => {
      const alive = fx.update(dt);
      if (!alive) fx.dispose?.();
      return alive;
    });
  }

  // A glowing packet travelling on an arc between two moving points.
  beam(fromFn, toFn, color, { duration = 1.1, size = 0.13, onArrive } = {}) {
    const scene = this.scene;
    const head = new THREE.Mesh(new THREE.SphereGeometry(size, 12, 10), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 1, depthWrite: false }));
    const glow = new THREE.Mesh(new THREE.SphereGeometry(size * 2.4, 12, 10), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.25, depthWrite: false, blending: THREE.AdditiveBlending }));
    head.add(glow);
    const N = 32;
    const positions = new Float32Array(N * 3);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.85, depthWrite: false }));
    line.frustumCulled = false;
    scene.add(head, line);
    let t = 0;
    let arrived = false;
    let fade = 0.5;
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const point = (u, out) => {
      a.copy(fromFn());
      b.copy(toFn());
      const lift = 1 + a.distanceTo(b) * 0.28;
      out.lerpVectors(a, b, u);
      out.y += Math.sin(Math.PI * u) * lift;
      return out;
    };
    const tmp = new THREE.Vector3();
    return this.add({
      update: (dt) => {
        if (!arrived) {
          t = Math.min(1, t + dt / duration);
          const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
          point(e, tmp);
          head.position.copy(tmp);
          const start = Math.max(0, e - 0.35);
          for (let i = 0; i < N; i++) {
            point(start + ((e - start) * i) / (N - 1), tmp);
            positions.set([tmp.x, tmp.y, tmp.z], i * 3);
          }
          geo.attributes.position.needsUpdate = true;
          if (t >= 1) {
            arrived = true;
            onArrive?.();
            this.ring(b.clone().setY(b.y - 0.3), color, { radius: 0.7, duration: 0.6 });
          }
          return true;
        }
        fade -= dt;
        line.material.opacity = Math.max(0, fade * 1.6);
        head.material.opacity = Math.max(0, fade * 2);
        glow.material.opacity = Math.max(0, fade * 0.5);
        return fade > 0;
      },
      dispose: () => {
        scene.remove(head, line);
        geo.dispose();
      },
    });
  }

  ring(pos, color, { radius = 1.4, duration = 0.9, flat = true } = {}) {
    const m = new THREE.Mesh(new THREE.RingGeometry(0.8, 1, 40), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false }));
    if (flat) m.rotation.x = -Math.PI / 2;
    m.position.copy(pos);
    this.scene.add(m);
    let t = 0;
    return this.add({
      update: (dt) => {
        t += dt / duration;
        const s = 0.2 + t * radius;
        m.scale.set(s, s, s);
        m.material.opacity = 0.8 * (1 - t);
        return t < 1;
      },
      dispose: () => this.scene.remove(m),
    });
  }

  burst(pos, color, { count = 22, speed = 3.2, life = 1.0 } = {}) {
    const geo = new THREE.TetrahedronGeometry(0.08);
    const material = new THREE.MeshBasicMaterial({ color, transparent: true });
    const parts = [];
    for (let i = 0; i < count; i++) {
      const p = new THREE.Mesh(geo, material);
      p.position.copy(pos);
      const a = Math.random() * Math.PI * 2;
      const up = 0.6 + Math.random() * 0.8;
      p.userData.v = new THREE.Vector3(Math.cos(a) * speed * Math.random(), up * speed, Math.sin(a) * speed * Math.random());
      this.scene.add(p);
      parts.push(p);
    }
    this.ring(pos.clone().setY(0.05), color, { radius: 2.2, duration: 0.8 });
    let t = 0;
    return this.add({
      update: (dt) => {
        t += dt;
        for (const p of parts) {
          p.userData.v.y -= 9 * dt;
          p.position.addScaledVector(p.userData.v, dt);
          p.rotation.x += dt * 6;
          p.rotation.y += dt * 4;
        }
        material.opacity = Math.max(0, 1 - t / life);
        return t < life;
      },
      dispose: () => {
        parts.forEach((p) => this.scene.remove(p));
        geo.dispose();
        material.dispose();
      },
    });
  }

  confetti(pos, { count = 160, life = 4.2 } = {}) {
    const colors = ['#e7a83b', '#4fa3e8', '#53b96a', '#e8749e', '#9b7be6', '#ef7a45', '#ffffff'];
    const geo = new THREE.PlaneGeometry(0.14, 0.08);
    const mats = colors.map((c) => new THREE.MeshBasicMaterial({ color: c, side: THREE.DoubleSide, transparent: true }));
    const parts = [];
    for (let i = 0; i < count; i++) {
      const p = new THREE.Mesh(geo, mats[i % mats.length]);
      p.position.copy(pos);
      const a = Math.random() * Math.PI * 2;
      const r = 1 + Math.random() * 4;
      p.userData.v = new THREE.Vector3(Math.cos(a) * r, 6 + Math.random() * 5, Math.sin(a) * r);
      p.userData.spin = new THREE.Vector3(Math.random() * 8, Math.random() * 8, Math.random() * 8);
      this.scene.add(p);
      parts.push(p);
    }
    let t = 0;
    return this.add({
      update: (dt) => {
        t += dt;
        for (const p of parts) {
          const v = p.userData.v;
          v.y -= 7 * dt;
          v.multiplyScalar(1 - dt * 0.9);
          if (p.position.y <= 0.05 && v.y < 0) {
            v.set(0, 0, 0);
            p.position.y = 0.05;
          } else {
            p.position.addScaledVector(v, dt);
            p.rotation.x += p.userData.spin.x * dt;
            p.rotation.y += p.userData.spin.y * dt;
          }
        }
        if (t > life - 1) mats.forEach((m) => (m.opacity = Math.max(0, life - t)));
        return t < life;
      },
      dispose: () => {
        parts.forEach((p) => this.scene.remove(p));
        geo.dispose();
        mats.forEach((m) => m.dispose());
      },
    });
  }

  sparkle(pos, color) {
    const geo = new THREE.OctahedronGeometry(0.06);
    const material = new THREE.MeshBasicMaterial({ color, transparent: true });
    const parts = [];
    for (let i = 0; i < 10; i++) {
      const p = new THREE.Mesh(geo, material);
      p.position.set(pos.x + (Math.random() - 0.5) * 0.8, pos.y + Math.random() * 0.2, pos.z + (Math.random() - 0.5) * 0.6);
      p.userData.vy = 0.8 + Math.random() * 1.2;
      this.scene.add(p);
      parts.push(p);
    }
    let t = 0;
    return this.add({
      update: (dt) => {
        t += dt;
        for (const p of parts) {
          p.position.y += p.userData.vy * dt;
          p.rotation.y += dt * 5;
        }
        material.opacity = Math.max(0, 1 - t / 1.2);
        return t < 1.2;
      },
      dispose: () => {
        parts.forEach((p) => this.scene.remove(p));
        geo.dispose();
        material.dispose();
      },
    });
  }

  // Moves an object along an arc to a destination, then calls done.
  fly(obj, toFn, { duration = 0.9, height = 2, spin = true, done } = {}) {
    const from = obj.position.clone();
    let t = 0;
    const to = new THREE.Vector3();
    return this.add({
      update: (dt) => {
        t = Math.min(1, t + dt / duration);
        const e = 1 - (1 - t) ** 3;
        to.copy(toFn());
        obj.position.lerpVectors(from, to, e);
        obj.position.y += Math.sin(Math.PI * e) * height;
        if (spin) obj.rotation.y += dt * 6;
        else obj.rotation.y = Math.sin(Math.PI * e) * 0.6;
        if (t >= 1) done?.();
        return t < 1;
      },
    });
  }
}
