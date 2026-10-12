import * as THREE from 'three';
import { mat, tint } from './geo.js';

const SKINS = ['#f2c9a4', '#e3b08b', '#c98d66', '#8f5c3d', '#f6d8bf', '#b97a52'];
const HAIRS = ['#3b2a20', '#6b4423', '#1f1b1a', '#b5651d', '#d9b26f', '#7a3b2e'];

function hash(s) {
  let h = 7;
  for (const ch of s) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

function part(geo, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(geo, material);
  m.position.set(x, y, z);
  m.castShadow = true;
  return m;
}

const cap = (color) => new THREE.SphereGeometry(0.31, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2);

// Headwear tells the teams apart at a glance.
function accessory(key, color, head) {
  const acc = new THREE.Group();
  const add = (...m) => acc.add(...m);
  switch (key) {
    case 'ceo': {
      const gold = new THREE.MeshStandardMaterial({ color: '#f5c451', emissive: '#e0a020', emissiveIntensity: 0.45, metalness: 0.5, roughness: 0.35, flatShading: true });
      add(part(new THREE.CylinderGeometry(0.2, 0.22, 0.12, 7, 1, true), gold, 0, 0.6, 0));
      for (let i = 0; i < 5; i++) {
        const a = (i / 5) * Math.PI * 2;
        add(part(new THREE.ConeGeometry(0.05, 0.14, 4), gold, Math.sin(a) * 0.2, 0.73, Math.cos(a) * 0.2));
      }
      add(part(new THREE.SphereGeometry(0.035, 6, 4), mat('#ef4f5f', { emissive: '#ef4f5f', emissiveIntensity: 0.6 }), 0, 0.62, 0.21));
      break;
    }
    case 'research': {
      add(part(cap(), mat(color), 0, 0.36, 0));
      add(part(new THREE.SphereGeometry(0.07, 6, 4), mat(tint(color, 0.5)), 0, 0.68, 0));
      const lens = new THREE.TorusGeometry(0.075, 0.015, 4, 12);
      add(part(lens, mat('#2b2b2b'), -0.1, 0.32, 0.27), part(lens, mat('#2b2b2b'), 0.1, 0.32, 0.27));
      break;
    }
    case 'dev': {
      const hat = mat('#f2c14e');
      add(part(cap(), hat, 0, 0.38, 0), part(new THREE.CylinderGeometry(0.38, 0.38, 0.03, 12), hat, 0, 0.39, 0.04));
      add(part(new THREE.BoxGeometry(0.05, 0.08, 0.5), mat('#e0a530'), 0, 0.6, 0));
      break;
    }
    case 'content': {
      const beret = part(new THREE.CylinderGeometry(0.3, 0.28, 0.1, 10), mat(color), 0.05, 0.58, 0);
      beret.rotation.z = -0.25;
      add(beret, part(new THREE.SphereGeometry(0.04, 6, 4), mat(tint(color, -0.3)), 0.08, 0.66, 0));
      const pencil = part(new THREE.CylinderGeometry(0.018, 0.018, 0.3, 5), mat('#f2c14e'), 0.3, 0.32, 0.02);
      pencil.rotation.x = Math.PI / 2.3;
      add(pencil);
      break;
    }
    case 'design': {
      const band = part(new THREE.TorusGeometry(0.31, 0.03, 5, 16, Math.PI), mat(color), 0, 0.3, 0);
      band.rotation.y = Math.PI / 2;
      add(band);
      for (const x of [-0.31, 0.31]) add(part(new THREE.CylinderGeometry(0.09, 0.09, 0.08, 10), mat(tint(color, -0.2)), x, 0.3, 0).rotateZ(Math.PI / 2));
      break;
    }
    case 'genai': {
      // glowing visor: the generative artists see what the models imagine
      const visor = part(new THREE.BoxGeometry(0.5, 0.13, 0.12), new THREE.MeshStandardMaterial({ color: '#1c222d', emissive: color, emissiveIntensity: 1.2 }), 0, 0.33, 0.24);
      add(visor, part(new THREE.TorusGeometry(0.32, 0.025, 5, 24), mat('#2f3440'), 0, 0.33, 0).rotateX(Math.PI / 2));
      break;
    }
    case 'prompt': {
      const band = part(new THREE.TorusGeometry(0.31, 0.025, 5, 16, Math.PI), mat('#2f3440'), 0, 0.3, 0);
      band.rotation.y = Math.PI / 2;
      add(band);
      const mic = part(new THREE.CylinderGeometry(0.015, 0.015, 0.3, 5), mat('#2f3440'), 0.28, 0.18, 0.14);
      mic.rotation.x = Math.PI / 2.4;
      mic.rotation.z = 0.5;
      add(mic, part(new THREE.SphereGeometry(0.045, 8, 6), mat(color), 0.16, 0.12, 0.28));
      break;
    }
    case 'skills': {
      add(part(new THREE.BoxGeometry(0.62, 0.04, 0.62), mat('#232933'), 0, 0.63, 0));
      add(part(new THREE.CylinderGeometry(0.22, 0.24, 0.12, 10), mat('#232933'), 0, 0.57, 0));
      add(part(new THREE.CylinderGeometry(0.012, 0.012, 0.25, 4), mat(color), 0.28, 0.52, 0.2));
      break;
    }
    case 'qa': {
      add(part(cap(), mat(color), 0, 0.37, 0));
      add(part(new THREE.CylinderGeometry(0.2, 0.2, 0.03, 10, 1, false, -Math.PI / 2, Math.PI), mat(tint(color, -0.2)), 0, 0.39, 0.2));
      break;
    }
    case 'sub': {
      add(part(new THREE.CylinderGeometry(0.012, 0.012, 0.3, 4), mat('#ffffff'), 0, 0.72, 0));
      add(part(new THREE.SphereGeometry(0.05, 8, 6), new THREE.MeshBasicMaterial({ color }), 0, 0.88, 0));
      break;
    }
    default:
      add(part(cap(), mat(color), 0, 0.37, 0));
  }
  head.add(acc);
}

function thoughtDots() {
  const g = new THREE.Group();
  const m = new THREE.MeshBasicMaterial({ color: '#ffffff' });
  for (let i = 0; i < 3; i++) g.add(new THREE.Mesh(new THREE.SphereGeometry(0.055, 8, 6), m));
  g.visible = false;
  return g;
}

function magnifier() {
  const g = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.022, 6, 16), mat('#3a3f47'));
  const glass = new THREE.Mesh(new THREE.CircleGeometry(0.1, 16), new THREE.MeshStandardMaterial({ color: '#bfe6ff', transparent: true, opacity: 0.55, emissive: '#bfe6ff', emissiveIntensity: 0.4 }));
  const handle = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.18, 6), mat('#7a5a40'));
  handle.position.y = -0.2;
  g.add(ring, glass, handle);
  g.visible = false;
  return g;
}

export class Actor {
  constructor({ agent, color, seat, nav, groundAt }) {
    this.id = agent.id;
    this.name = agent.name;
    this.team = agent.team;
    this.kind = agent.kind;
    this.color = color;
    this.nav = nav;
    this.groundAt = groundAt;
    this.seat = seat;
    this.queue = [];
    this.path = null;
    this.speed = 3.2;
    this.pose = 'sit';
    this.anim = 'idle';
    this.animUntil = 0;
    this.baseAnim = 'idle';
    this.walking = false;
    this.heading = 0;
    this.targetHeading = 0;
    this.phase = Math.random() * 10;
    this.carrying = null;
    this.state = agent.state;
    this.scale = this.kind === 'sub' ? 0.01 : 1;
    this.scaleTarget = 1;

    const isSub = this.kind === 'sub';
    const h = hash(agent.id);
    const holo = (c) => new THREE.MeshStandardMaterial({ color: c, emissive: color, emissiveIntensity: 0.55, transparent: true, opacity: 0.78, flatShading: true });
    const skin = isSub ? holo(tint(color, 0.6)) : mat(SKINS[h % SKINS.length]);
    const hair = isSub ? holo(tint(color, 0.2)) : mat(HAIRS[(h >> 3) % HAIRS.length]);
    const shirt = isSub ? holo(color) : mat(color);
    const pants = isSub ? holo(tint(color, -0.4)) : mat(tint(color, -0.55));

    const root = new THREE.Group();
    root.userData.agentId = agent.id;
    this.root = root;
    const body = new THREE.Group();
    this.body = body;
    root.add(body);

    this.legs = [-0.12, 0.12].map((x) => {
      const pivot = new THREE.Group();
      pivot.position.set(x, 0.44, 0);
      pivot.add(part(new THREE.BoxGeometry(0.15, 0.4, 0.17), pants, 0, -0.2, 0));
      pivot.add(part(new THREE.BoxGeometry(0.16, 0.08, 0.24), isSub ? pants : mat('#2a2a30'), 0, -0.41, 0.04));
      body.add(pivot);
      return pivot;
    });

    this.torso = new THREE.Group();
    this.torso.position.y = 0.44;
    body.add(this.torso);
    this.torso.add(part(new THREE.CylinderGeometry(0.25, 0.31, 0.58, 8), shirt, 0, 0.28, 0));
    this.torso.add(part(new THREE.CylinderGeometry(0.1, 0.12, 0.06, 8), skin, 0, 0.6, 0));
    if (this.kind === 'ceo') this.torso.add(part(new THREE.BoxGeometry(0.08, 0.32, 0.04), mat('#ef4f5f'), 0, 0.32, 0.27));
    else if (this.kind === 'lead') this.torso.add(part(new THREE.BoxGeometry(0.14, 0.14, 0.03), mat('#f5c451', { emissive: '#f5c451', emissiveIntensity: 0.4 }), 0.12, 0.4, 0.28));
    else this.torso.add(part(new THREE.BoxGeometry(0.2, 0.12, 0.02), mat(tint(color, 0.45)), 0.08, 0.38, 0.28));

    this.arms = [-1, 1].map((side) => {
      const pivot = new THREE.Group();
      pivot.position.set(side * 0.33, 0.52, 0);
      pivot.add(part(new THREE.BoxGeometry(0.12, 0.42, 0.13), shirt, 0, -0.18, 0));
      pivot.add(part(new THREE.SphereGeometry(0.075, 8, 6), skin, 0, -0.42, 0));
      this.torso.add(pivot);
      return pivot;
    });
    this.lens = magnifier();
    this.lens.position.set(0, -0.62, 0.05);
    this.arms[1].add(this.lens);

    this.head = new THREE.Group();
    this.head.position.y = 0.6;
    this.torso.add(this.head);
    this.head.add(part(new THREE.IcosahedronGeometry(0.31, 1), skin, 0, 0.3, 0));
    const hairCap = part(new THREE.SphereGeometry(0.325, 10, 8, 0, Math.PI * 2, 0, Math.PI / 1.9), hair, 0, 0.32, -0.03);
    hairCap.rotation.x = -0.35;
    this.head.add(hairCap);
    const eye = new THREE.SphereGeometry(0.038, 6, 6);
    const eyeMat = isSub ? new THREE.MeshBasicMaterial({ color: '#ffffff' }) : mat('#1f1b1a', { flatShading: false });
    this.eyes = [part(eye, eyeMat, -0.1, 0.31, 0.27), part(eye, eyeMat, 0.1, 0.31, 0.27)];
    this.head.add(...this.eyes);
    if (!isSub) {
      const blush = new THREE.MeshBasicMaterial({ color: '#f29c9c', transparent: true, opacity: 0.5 });
      for (const x of [-0.17, 0.17]) {
        const b = new THREE.Mesh(new THREE.CircleGeometry(0.045, 10), blush);
        b.position.set(x, 0.22, 0.27);
        b.rotation.y = x * 1.6;
        this.head.add(b);
      }
    }
    accessory(this.kind === 'ceo' ? 'ceo' : isSub ? 'sub' : this.team, color, this.head);

    this.dots = thoughtDots();
    root.add(this.dots);

    const ring = new THREE.Mesh(new THREE.RingGeometry(0.34, 0.46, 28), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.02;
    this.halo = ring;
    root.add(ring);

    root.scale.setScalar(this.scale);
    this.placeAtSeat();
  }

  get position() {
    return this.root.position;
  }

  placeAtSeat() {
    this.root.position.set(this.seat.x, this.groundAt(this.seat.x, this.seat.z), this.seat.z);
    this.heading = this.targetHeading = 0;
    this.pose = 'sit';
    this.queue = [];
    this.path = null;
  }

  atSeat() {
    return Math.hypot(this.root.position.x - this.seat.x, this.root.position.z - this.seat.z) < 0.08;
  }

  teleport(x, z, heading = 0) {
    this.root.position.set(x, this.groundAt(x, z), z);
    this.heading = this.targetHeading = heading;
    this.pose = 'stand';
    this.queue = [];
    this.path = null;
  }

  headWorld(out = new THREE.Vector3()) {
    out.copy(this.root.position);
    out.y += (this.pose === 'sit' && !this.walking ? 1.6 : 1.8) * this.scale;
    return out;
  }

  // ----- queue -----

  do(...steps) {
    this.queue.push(...steps);
    return this;
  }

  // Drops whatever the agent was doing (a coffee break) to take new work.
  interrupt() {
    this.queue = [];
    this.path = null;
    this.idleTrip = false;
    return this;
  }

  walkTo(x, z) {
    return this.do({ type: 'stand' }, { type: 'walk', to: { x, z } });
  }

  goHome() {
    if (this.atSeat() && this.pose === 'sit' && !this.queue.length) return this;
    return this.do({ type: 'stand', home: true }, { type: 'walk', to: this.seat, home: true }, { type: 'face', heading: 0, home: true }, { type: 'sit', home: true });
  }

  // Gives up a coffee break or a walk home for new work; real work already queued is kept.
  yieldTo() {
    if (this.idleTrip || this.queue.every((s) => s.home)) this.interrupt();
    return this;
  }

  play(anim, ms) {
    this.anim = anim;
    this.animUntil = performance.now() + ms;
  }

  setBase(anim) {
    this.baseAnim = anim;
  }

  carry(mesh) {
    this.carrying = mesh;
    mesh.position.set(0, 0.86, 0.42);
    mesh.rotation.set(0, 0, 0);
    this.root.add(mesh);
  }

  release() {
    const m = this.carrying;
    this.carrying = null;
    return m;
  }

  // ----- per-frame -----

  update(dt, t) {
    const boost = 1 + Math.max(0, this.queue.length - 4) * 0.35;
    this.walking = false;
    while (this.queue.length) {
      const step = this.queue[0];
      if (step.type === 'stand') {
        this.pose = 'stand';
        this.queue.shift();
        continue;
      }
      if (step.type === 'sit') {
        this.pose = 'sit';
        this.queue.shift();
        continue;
      }
      if (step.type === 'face') {
        this.targetHeading = step.heading;
        this.queue.shift();
        continue;
      }
      if (step.type === 'faceTo') {
        const p = step.to();
        if (p) this.targetHeading = Math.atan2(p.x - this.root.position.x, p.z - this.root.position.z);
        this.queue.shift();
        continue;
      }
      if (step.type === 'call') {
        this.queue.shift();
        step.fn(this);
        continue;
      }
      if (step.type === 'wait') {
        step.left = (step.left ?? step.ms) - dt * 1000 * boost;
        if (step.left <= 0) this.queue.shift();
        break;
      }
      if (step.type === 'walk') {
        if (!this.path) {
          this.path = this.nav.path({ x: this.root.position.x, z: this.root.position.z }, step.to);
          let len = 0;
          let prev = this.root.position;
          for (const p of this.path) {
            len += Math.hypot(p.x - prev.x, p.z - prev.z);
            prev = p;
          }
          // long trips across the hub are a jog, not a stroll
          this.speed = Math.min(9, Math.max(3.2, 2.6 + len / 6));
        }
        const target = this.path[0];
        if (!target) {
          this.path = null;
          this.queue.shift();
          continue;
        }
        const dx = target.x - this.root.position.x;
        const dz = target.z - this.root.position.z;
        const dist = Math.hypot(dx, dz);
        const move = this.speed * boost * dt;
        this.walking = true;
        if (dist <= move) {
          this.root.position.x = target.x;
          this.root.position.z = target.z;
          this.path.shift();
          if (!this.path.length) {
            this.path = null;
            this.queue.shift();
          }
        } else {
          this.root.position.x += (dx / dist) * move;
          this.root.position.z += (dz / dist) * move;
          this.targetHeading = Math.atan2(dx, dz);
        }
        break;
      }
      this.queue.shift();
    }
    this.animate(dt, t);
  }

  animate(dt, t) {
    let diff = this.targetHeading - this.heading;
    diff = Math.atan2(Math.sin(diff), Math.cos(diff));
    this.heading += diff * Math.min(1, dt * 10);
    this.root.rotation.y = this.heading;

    this.scale += (this.scaleTarget - this.scale) * Math.min(1, dt * 5);
    this.root.scale.setScalar(Math.max(0.01, this.scale));

    const now = performance.now();
    const anim = this.walking ? 'walk' : now < this.animUntil ? this.anim : this.baseAnim;
    const sitting = this.pose === 'sit' && !this.walking;
    const running = this.walking && this.speed > 5;
    this.phase += dt * (anim === 'walk' ? (running ? 15 : 11) : 1);
    const k = Math.min(1, dt * 12);
    const lerp = (obj, prop, v) => {
      obj[prop] += (v - obj[prop]) * k;
    };

    let legL = 0;
    let legR = 0;
    let armL = 0;
    let armR = 0;
    let armLz = 0;
    let armRz = 0;
    let torsoX = 0;
    let headX = 0;
    let headY = 0;
    let headZ = 0;
    let y = 0;
    if (sitting) {
      legL = legR = -1.45;
      y = 0.05;
    }

    switch (anim) {
      case 'walk': {
        const s = Math.sin(this.phase);
        const amp = running ? 1.0 : 0.7;
        legL = s * amp;
        legR = -s * amp;
        armL = -s * amp * 0.9;
        armR = s * amp * 0.9;
        torsoX = running ? 0.18 : 0;
        y = Math.abs(Math.cos(this.phase)) * (running ? 0.12 : 0.06);
        break;
      }
      case 'work':
        armL = -1.15 + Math.sin(t * 22) * 0.12;
        armR = -1.15 + Math.sin(t * 22 + 1.7) * 0.12;
        headX = 0.18 + Math.sin(t * 3) * 0.03;
        break;
      case 'think':
        armR = -2.1;
        armRz = 0.5;
        armL = sitting ? -0.9 : 0;
        headZ = Math.sin(t * 1.5) * 0.12;
        headX = -0.12;
        break;
      case 'inspect':
        torsoX = 0.28;
        armR = -1.4 + Math.sin(t * 2.5) * 0.15;
        headX = 0.25;
        headY = Math.sin(t * 1.8) * 0.3;
        break;
      case 'celebrate':
        armL = -2.7 + Math.sin(t * 14) * 0.25;
        armR = -2.7 - Math.sin(t * 14) * 0.25;
        armLz = -0.3;
        armRz = 0.3;
        if (!sitting) y = Math.abs(Math.sin(t * 9)) * 0.28;
        headX = -0.2;
        break;
      case 'shake':
        headY = Math.sin(t * 20) * 0.45;
        armL = -0.4;
        armR = -0.4;
        break;
      case 'wave':
      case 'ask':
        armR = -2.7;
        armRz = 0.3 + Math.sin(t * (anim === 'ask' ? 6 : 12)) * 0.3;
        break;
      case 'paused':
        headX = 0.45;
        armL = sitting ? -0.9 : 0;
        armR = sitting ? -0.9 : 0;
        break;
      default:
        headY = Math.sin(t * 0.6 + this.phase) * 0.25;
        if (sitting) {
          armL = -0.85;
          armR = -0.85;
        }
    }

    lerp(this.legs[0].rotation, 'x', legL);
    lerp(this.legs[1].rotation, 'x', legR);
    lerp(this.arms[0].rotation, 'x', armL);
    lerp(this.arms[1].rotation, 'x', armR);
    lerp(this.arms[0].rotation, 'z', armLz);
    lerp(this.arms[1].rotation, 'z', armRz);
    lerp(this.torso.rotation, 'x', torsoX);
    lerp(this.head.rotation, 'x', headX);
    lerp(this.head.rotation, 'y', headY);
    lerp(this.head.rotation, 'z', headZ);
    lerp(this.body.position, 'y', y);
    const ground = this.groundAt(this.root.position.x, this.root.position.z);
    this.root.position.y += (ground - this.root.position.y) * Math.min(1, dt * 14);
    this.torso.scale.set(1, 1 + Math.sin(t * 2.2 + this.phase) * 0.015, 1);

    const blink = Math.sin(t * 0.9 + this.phase * 3) > 0.985 ? 0.15 : 1;
    this.eyes.forEach((e) => (e.scale.y = blink));

    this.lens.visible = anim === 'inspect';
    this.dots.visible = anim === 'think';
    if (this.dots.visible) {
      this.dots.position.y = sitting ? 1.85 : 2.05;
      this.dots.children.forEach((d, i) => {
        const a = t * 2.4 + (i * Math.PI * 2) / 3;
        d.position.set(Math.cos(a) * 0.32, Math.sin(t * 4 + i) * 0.06, Math.sin(a) * 0.32);
      });
    }
    this.halo.material.opacity = 0.35 + Math.sin(t * 3 + this.phase) * 0.12;
    if (this.carrying) this.carrying.rotation.y += dt * 1.5;
  }
}
