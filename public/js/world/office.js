import * as THREE from 'three';
import { box, canvasTexture, cyl, floorLamp, glow, mat, plant, slab, tint } from './geo.js';
import { NavGrid } from './nav.js';

// One warm open-space office, diorama style: back walls north and west,
// the kanban board on the north wall facing the camera, the CEO on a
// platform in front of it with the Brain hologram above, team zones in two rows.

// ---------- layout ----------

export const WORLD = { minX: -25, maxX: 25, minZ: -18, maxZ: 18 };
export const FLOOR = { minX: -24, maxX: 24, minZ: -17, maxZ: 17 };
// The diorama's outer box as the camera sees it: the base and plinth under the floor
// (0.65 past its edge, down to y -1.66) and the top of the back walls with their cap
// (y 5.14). The camera framing fits these points (framing.js).
export const ENVELOPE = (() => {
  const bx = FLOOR.maxX + 0.65;
  const bz = FLOOR.maxZ + 0.65;
  const wx = FLOOR.maxX + 0.45;
  const wz = FLOOR.maxZ + 0.45;
  const points = [];
  for (const x of [-bx, bx]) for (const z of [-bz, bz]) for (const y of [-1.66, 0]) points.push(new THREE.Vector3(x, y, z));
  points.push(new THREE.Vector3(-wx, 5.14, -wz), new THREE.Vector3(wx, 5.14, -wz), new THREE.Vector3(-wx, 5.14, wz));
  return Object.freeze(points);
})();
export const CEO_DESK = { x: 0, z: -10.2 };
export const BRAIN = { x: 0, z: -11.6, y: 3.5, r: 3.3 };
export const BOARD = { x: 0, z: -16.9, width: 18, columns: ['DA FARE', 'IN CORSO', 'REVISIONE', 'FATTO'] };
export const DESK_TOP = 0.95;
const ZONE_W = 10.4;
const ZONE_D = 6.6;
const ZONES = [
  { x: -17.8, z: -1.2 },
  { x: -6, z: -1.2 },
  { x: 6, z: -1.2 },
  { x: 17.8, z: -1.2 },
  { x: -17.8, z: 9.6 },
  { x: -6, z: 9.6 },
  { x: 6, z: 9.6 },
  { x: 17.8, z: 9.6 },
  // spec 11 T08: the Reverse Engineering team, in the north-west corner between the window and the stage
  { x: -17.2, z: -11.6 },
];

// where free agents like to wander
export const SPOTS = [
  { x: -20.6, z: 14.6, say: '☕' },
  { x: -22.4, z: -6.2, say: '💧' },
  { x: 17.6, z: 14.3, say: '🛋️' },
  { x: -17, z: -15.3, say: '🌤️' },
  { x: 17, z: -15.3, say: '🌤️' },
  { x: -4, z: -15, say: '📋' },
  { x: 4, z: -15, say: '📋' },
  { x: -3.8, z: -7.4, say: '🧠' },
  { x: 3.8, z: -7.4, say: '🧠' },
];

export function columnOf(status) {
  if (status === 'queued') return 0;
  if (status === 'review') return 2;
  if (status === 'done' || status === 'failed' || status === 'skipped') return 3;
  return 1;
}

export function cardSlot(column, index) {
  const colW = BOARD.width / 4;
  const x0 = BOARD.x - BOARD.width / 2 + colW * (column + 0.5);
  const sub = index % 3;
  const row = Math.floor(index / 3);
  const r = Math.min(row, 7);
  return new THREE.Vector3(x0 + (sub - 1) * 1.42, 3.72 - r * 0.42, BOARD.z + 0.16 + (row > 7 ? (row - 7) * 0.04 : 0));
}

export function computeLayout(config) {
  const rooms = [];
  const desks = new Map();
  const bays = new Map();
  Object.entries(config.teams).forEach(([id, t], i) => {
    const slot = ZONES[i] ?? { x: -17.8 + (i % 4) * 11.9, z: 9.6 };
    rooms.push({ team: id, x: slot.x, z: slot.z, w: ZONE_W, d: ZONE_D, color: t.color, label: t.label, prop: t.prop ?? 'plant' });
    if (t.lead) desks.set(t.lead.id, { x: slot.x - 3.1, z: slot.z - 1.5, team: id, kind: 'lead', big: true });
    (t.workers ?? []).slice(0, 2).forEach((w, j) => desks.set(w.id, { x: slot.x + 0.1 + j * 2.6, z: slot.z - 1.5, team: id, kind: 'worker' }));
    const k = Math.min(3, t.maxSubAgents ?? 0);
    bays.set(id, Array.from({ length: k }, (_, j) => ({ x: slot.x - 3.0 + j * 2.6, z: slot.z + 2.0, team: id, kind: 'sub', slot: j })));
  });
  desks.set(config.ceo.id, { x: CEO_DESK.x, z: CEO_DESK.z, team: 'ceo', kind: 'ceo', big: true });
  for (const d of [...desks.values(), ...[...bays.values()].flat()]) d.seat = { x: d.x, z: d.z - 0.86 };
  return { rooms, desks, bays };
}

export function groundAt(layout, x, z) {
  return Math.hypot((x - CEO_DESK.x) / 1.35, z - (CEO_DESK.z - 0.7)) <= 3.0 ? 0.2 : 0;
}

// ---------- textures ----------

function plankTexture() {
  const t = canvasTexture(512, 512, (g, w, h) => {
    const rows = 8;
    for (let r = 0; r < rows; r++) {
      const offset = (r % 2) * 128 + (r % 3) * 37;
      for (let x = -offset; x < w; x += 256) {
        const shade = 214 + Math.floor(Math.random() * 18);
        g.fillStyle = `rgb(${shade + 18}, ${shade}, ${shade - 30})`;
        g.fillRect(x, (r * h) / rows, 256, h / rows);
        g.fillStyle = 'rgba(120, 85, 50, 0.18)';
        g.fillRect(x, (r * h) / rows, 2, h / rows);
      }
      g.fillStyle = 'rgba(120, 85, 50, 0.22)';
      g.fillRect(0, (r * h) / rows, w, 2);
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(7, 5);
  return t;
}

function skyTexture() {
  return canvasTexture(256, 128, (g, w, h) => {
    const grad = g.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, '#8ec5f0');
    grad.addColorStop(0.65, '#d9ecfa');
    grad.addColorStop(1, '#fde7c8');
    g.fillStyle = grad;
    g.fillRect(0, 0, w, h);
    g.fillStyle = 'rgba(120, 150, 180, 0.45)';
    for (let i = 0; i < 14; i++) {
      const bw = 10 + Math.random() * 18;
      const bh = 20 + Math.random() * 50;
      g.fillRect(i * 19, h - bh, bw, bh);
    }
  });
}

// ---------- furniture ----------

function deskPiece(d, color) {
  const g = new THREE.Group();
  const w = d.big ? 2.3 : 1.75;
  const wood = mat('#ecdcc4');
  const leg = mat('#6e5b4b');
  g.add(box(w, 0.08, 0.86, wood, 0, 0.74, 0));
  for (const [lx, lz] of [[-w / 2 + 0.08, -0.36], [w / 2 - 0.08, -0.36], [-w / 2 + 0.08, 0.36], [w / 2 - 0.08, 0.36]]) g.add(box(0.07, 0.7, 0.07, leg, lx, 0.35, lz));
  g.add(box(w - 0.15, 0.36, 0.04, mat('#d9c6aa'), 0, 0.5, 0.36));

  // laptop facing the seat, so the camera sees the agent's face
  const screenMat = new THREE.MeshStandardMaterial({ color: '#1d2733', emissive: new THREE.Color(color), emissiveIntensity: 0.15, roughness: 0.4 });
  const laptop = new THREE.Group();
  laptop.add(box(0.62, 0.03, 0.42, mat('#cfd3d8'), 0, 0.795, 0));
  const lid = new THREE.Group();
  lid.add(box(0.62, 0.42, 0.03, mat(color), 0, 0.21, 0));
  const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.54, 0.34), screenMat);
  screen.position.set(0, 0.21, -0.018);
  screen.rotation.y = Math.PI;
  lid.add(screen);
  lid.position.set(0, 0.81, 0.2);
  lid.rotation.x = 0.28;
  laptop.add(lid);
  laptop.position.x = d.big ? 0.35 : -0.05;
  g.add(laptop);
  if (d.big) {
    // the lead also has a second screen with the team's dashboard
    g.add(box(0.05, 0.28, 0.05, leg, -0.6, 0.92, 0.3));
    g.add(box(0.74, 0.44, 0.05, mat('#2a3340'), -0.6, 1.24, 0.32));
    const dash = new THREE.Mesh(new THREE.PlaneGeometry(0.66, 0.36), screenMat);
    dash.position.set(-0.6, 1.24, 0.29);
    dash.rotation.y = Math.PI;
    g.add(dash);
  }
  g.add(cyl(0.07, 0.06, 0.13, 8, mat(tint(color, 0.35)), w / 2 - 0.22, 0.845, -0.2));
  g.add(box(0.32, 0.015, 0.42, mat('#fbfaf6'), -w / 2 + 0.3, 0.79, -0.05));

  const chair = new THREE.Group();
  const seatMat = mat(tint(color, -0.25));
  chair.add(box(0.56, 0.09, 0.54, seatMat, 0, 0.46, 0));
  chair.add(box(0.56, 0.6, 0.08, seatMat, 0, 0.8, -0.26));
  chair.add(cyl(0.04, 0.04, 0.4, 6, mat('#555b63'), 0, 0.22, 0));
  chair.add(cyl(0.28, 0.28, 0.04, 5, mat('#555b63'), 0, 0.03, 0));
  chair.position.set(0, 0, -0.86);
  g.add(chair);
  g.position.set(d.x, d.kind === 'ceo' ? 0.2 : 0, d.z);
  return { group: g, screen: screenMat, width: w };
}

function ghostDesk(d, color) {
  const g = new THREE.Group();
  const m = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: 0.2, emissive: color, emissiveIntensity: 0.35, depthWrite: false });
  g.add(box(1.75, 0.08, 0.86, m, 0, 0.74, 0, { cast: false, receive: false }));
  g.add(box(0.62, 0.42, 0.03, m, 0, 1.0, 0.2, { cast: false, receive: false }));
  g.add(box(0.56, 0.09, 0.54, m, 0, 0.46, -0.86, { cast: false, receive: false }));
  g.position.set(d.x, 0, d.z);
  g.userData.material = m;
  return g;
}

function bayMark(zone) {
  const t = canvasTexture(512, 160, (g, w, h) => {
    g.strokeStyle = 'rgba(80, 60, 40, 0.45)';
    g.setLineDash([16, 12]);
    g.lineWidth = 4;
    g.strokeRect(6, 6, w - 12, h - 12);
    g.setLineDash([]);
    g.fillStyle = 'rgba(80, 60, 40, 0.55)';
    g.font = '700 22px "Segoe UI", system-ui, sans-serif';
    g.textAlign = 'right';
    g.fillText('SUB-AGENT BAY', w - 22, h - 20);
  });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(8.6, 2.7), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false }));
  m.rotation.x = -Math.PI / 2;
  m.position.set(zone.x - 0.4, 0.05, zone.z + 1.75);
  return m;
}

function prop(kind, color) {
  const g = new THREE.Group();
  const dark = mat('#3a3f47');
  switch (kind) {
    case 'globe': {
      g.add(cyl(0.25, 0.32, 0.1, 10, mat('#6e5b4b'), 0, 0.05, 0));
      g.add(cyl(0.04, 0.04, 0.9, 6, mat('#6e5b4b'), 0, 0.5, 0));
      const s = new THREE.Mesh(new THREE.IcosahedronGeometry(0.5, 1), mat(color));
      s.position.y = 1.35;
      s.castShadow = true;
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.62, 0.025, 6, 32), mat('#b08a4a'));
      ring.position.y = 1.35;
      ring.rotation.x = 1.2;
      g.add(s, ring);
      g.userData.spin = s;
      break;
    }
    case 'rack': {
      g.add(box(0.9, 2.0, 0.8, mat('#2d333c'), 0, 1.0, 0));
      const leds = [];
      for (let i = 0; i < 12; i++) {
        const led = new THREE.MeshStandardMaterial({ color: '#111', emissive: i % 3 ? color : '#4b8ff2', emissiveIntensity: 1 });
        leds.push(led);
        g.add(box(0.08, 0.05, 0.02, led, -0.27 + (i % 4) * 0.18, 0.5 + Math.floor(i / 4) * 0.5, 0.41, { cast: false }));
      }
      g.userData.leds = leds;
      break;
    }
    case 'shelf':
    case 'library': {
      const n = kind === 'library' ? 2 : 1;
      const books = ['#ec6fa8', '#4b8ff2', '#3fbf6f', '#e3b23c', '#9466f0', '#f28a3a', '#f4efe6'];
      for (let k = 0; k < n; k++) {
        const s = new THREE.Group();
        s.add(box(1.4, 2.1, 0.5, mat('#8b6748'), 0, 1.05, 0));
        for (let row = 0; row < 3; row++) {
          let x = -0.6;
          while (x < 0.56) {
            const bw = 0.08 + Math.random() * 0.1;
            const bh = 0.36 + Math.random() * 0.2;
            s.add(box(bw, bh, 0.34, mat(books[Math.floor(Math.random() * books.length)]), x + bw / 2, 0.26 + row * 0.66 + bh / 2, 0.06, { cast: false }));
            x += bw + 0.02;
          }
        }
        s.position.x = k * 1.5 - (n - 1) * 0.75;
        g.add(s);
      }
      if (kind === 'library') {
        const book = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.06, 0.38), glow(color, 1.1));
        book.position.set(0, 2.7, 0.3);
        g.add(book);
        g.userData.float = book;
      }
      break;
    }
    case 'easel': {
      const wood = mat('#8b6748');
      const l1 = box(0.06, 1.8, 0.06, wood, -0.3, 0.9, 0);
      l1.rotation.z = 0.12;
      const l2 = box(0.06, 1.8, 0.06, wood, 0.3, 0.9, 0);
      l2.rotation.z = -0.12;
      g.add(l1, l2, box(0.06, 1.7, 0.06, wood, 0, 0.85, -0.3));
      const art = canvasTexture(128, 160, (c, w, h) => {
        c.fillStyle = '#fbf8f2';
        c.fillRect(0, 0, w, h);
        ['#9466f0', '#ec6fa8', '#e3b23c', '#4b8ff2'].forEach((col, i) => {
          c.fillStyle = col;
          c.beginPath();
          c.arc(30 + i * 22, 50 + (i % 2) * 40, 22, 0, Math.PI * 2);
          c.fill();
        });
      });
      const white = mat('#eeeeee');
      const cm = new THREE.Mesh(new THREE.BoxGeometry(0.9, 1.1, 0.04), [white, white, white, white, new THREE.MeshStandardMaterial({ map: art }), white]);
      cm.position.set(0, 1.35, 0.06);
      cm.castShadow = true;
      g.add(cm);
      break;
    }
    case 'studio': {
      g.add(cyl(0.02, 0.02, 1.7, 6, dark, -0.6, 0.85, 0));
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.42, 0.06, 8, 32), new THREE.MeshStandardMaterial({ color: '#ffffff', emissive: '#fff4d6', emissiveIntensity: 1.4 }));
      ring.position.set(-0.6, 1.95, 0);
      g.add(ring);
      for (let i = 0; i < 3; i++) {
        const leg = box(0.03, 1.3, 0.03, dark, 0.6 + Math.sin(i * 2.1) * 0.25, 0.62, Math.cos(i * 2.1) * 0.25);
        leg.rotation.z = Math.sin(i * 2.1) * 0.35;
        leg.rotation.x = -Math.cos(i * 2.1) * 0.35;
        g.add(leg);
      }
      g.add(box(0.36, 0.24, 0.3, mat('#1c222d'), 0.6, 1.35, 0));
      g.add(box(0.06, 0.06, 0.06, glow('#ef4f5f', 2), 0.75, 1.5, 0));
      break;
    }
    case 'board': {
      g.add(box(1.8, 1.2, 0.06, mat('#fbfbf8'), 0, 1.5, 0));
      g.add(box(1.9, 0.06, 0.1, dark, 0, 0.88, 0.02));
      g.add(box(0.05, 0.9, 0.05, dark, -0.8, 0.45, 0));
      g.add(box(0.05, 0.9, 0.05, dark, 0.8, 0.45, 0));
      ['#ffe066', '#ffadd2', '#9be7c4', '#a8d1ff', '#ffd59e', '#d6c2ff'].forEach((c, i) => g.add(box(0.26, 0.26, 0.01, mat(c), -0.6 + (i % 3) * 0.6, 1.75 - Math.floor(i / 3) * 0.45, 0.04, { cast: false })));
      break;
    }
    case 'checklist': {
      g.add(box(1.2, 1.5, 0.06, mat('#fbfbf8'), 0, 1.4, 0));
      g.add(box(0.05, 0.7, 0.05, dark, 0, 0.35, 0));
      for (let i = 0; i < 4; i++) {
        g.add(box(0.14, 0.14, 0.02, glow(i < 3 ? '#3fbf6f' : '#f28a3a', 0.5), -0.4, 1.85 - i * 0.3, 0.04, { cast: false }));
        g.add(box(0.6, 0.05, 0.02, mat('#b9bfc9'), 0.1, 1.85 - i * 0.3, 0.04, { cast: false }));
      }
      break;
    }
    case 'scanner': {
      // spec 11 T08: a terminal and a magnifying lens, for the team that reads applications without running them
      g.add(box(0.9, 1.1, 0.6, mat('#2d333c'), 0, 0.55, 0));
      g.add(box(0.74, 0.52, 0.04, new THREE.MeshStandardMaterial({ color: '#0f1c17', emissive: color, emissiveIntensity: 0.9 }), 0, 1.42, 0.2, { cast: false }));
      g.add(box(0.08, 0.32, 0.08, dark, 0, 1.12, 0.12));
      const leds = [];
      for (let i = 0; i < 4; i++) {
        const led = new THREE.MeshStandardMaterial({ color: '#111', emissive: i % 2 ? color : '#3fbf6f', emissiveIntensity: 1 });
        leds.push(led);
        g.add(box(0.1, 0.04, 0.02, led, -0.27 + i * 0.18, 0.95, 0.31, { cast: false }));
      }
      const lens = new THREE.Group();
      lens.add(new THREE.Mesh(new THREE.TorusGeometry(0.26, 0.05, 8, 24), mat('#b08a4a')));
      const handle = box(0.06, 0.42, 0.06, mat('#6e5b4b'), 0.22, -0.32, 0);
      handle.rotation.z = 0.7;
      lens.add(handle);
      lens.position.set(0.15, 2.05, 0.1);
      g.add(lens);
      g.userData.spin = lens;
      g.userData.leds = leds;
      break;
    }
    default:
      g.add(plant(1.2));
  }
  return g;
}

function windowOn(group, { x, y, z, w, h, rotY = 0 }) {
  const win = new THREE.Group();
  const frame = mat('#7a5a3f');
  win.add(box(w + 0.3, 0.16, 0.3, frame, 0, -h / 2 - 0.08, 0));
  win.add(box(w + 0.3, 0.16, 0.3, frame, 0, h / 2 + 0.08, 0));
  win.add(box(0.16, h, 0.3, frame, -w / 2 - 0.07, 0, 0));
  win.add(box(0.16, h, 0.3, frame, w / 2 + 0.07, 0, 0));
  win.add(box(0.1, h, 0.26, frame, 0, 0, 0));
  const glassMat = new THREE.MeshBasicMaterial({ map: skyTexture() });
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(w, h), glassMat);
  glass.position.z = 0.02;
  win.add(glass);
  win.position.set(x, y, z);
  win.rotation.y = rotY;
  group.add(win);
  return glassMat;
}

function zoneRug(group, z) {
  const rug = slab(z.w, z.d, 0.6, 0.04, mat(tint(z.color, 0.74), { flatShading: false }));
  rug.position.set(z.x, 0.005, z.z);
  group.add(rug);
  const border = slab(z.w + 0.24, z.d + 0.24, 0.7, 0.03, mat(tint(z.color, 0.35), { flatShading: false }));
  border.position.set(z.x, 0, z.z);
  group.add(border);
}

// The face of the task board with its column titles; spec 06 redraws it in the
// language of the UI (World.relabel), so the titles travel with the texture.
export function boardFace(columns) {
  const face = canvasTexture(2048, 480, (c, cw, ch) => {
    c.fillStyle = '#fbf8f2';
    c.fillRect(0, 0, cw, ch);
    const colors = ['#9aa5b1', '#4b8ff2', '#f28a3a', '#3fbf6f'];
    const colW = cw / 4;
    columns.forEach((label, i) => {
      c.fillStyle = i % 2 ? '#f4efe6' : '#f8f4ec';
      c.fillRect(i * colW, 0, colW, ch);
      c.fillStyle = colors[i];
      c.fillRect(i * colW + 20, 14, colW - 40, 7);
      c.fillStyle = '#3b4756';
      c.font = '800 34px "Segoe UI", system-ui, sans-serif';
      c.textAlign = 'center';
      c.fillText(label, i * colW + colW / 2, 58);
      if (i) {
        c.fillStyle = '#d9d0c2';
        c.fillRect(i * colW - 1, 14, 2, ch - 28);
      }
    });
  });
  face.userData.columns = [...columns];
  return face;
}

function board(group) {
  const g = new THREE.Group();
  const w = BOARD.width;
  g.add(box(w + 0.5, 4.3, 0.16, mat('#3b4756'), 0, 2.45, 0));
  const surface = new THREE.Mesh(new THREE.PlaneGeometry(w, 4.0), new THREE.MeshStandardMaterial({ map: boardFace(BOARD.columns), roughness: 0.9 }));
  surface.position.set(0, 2.45, 0.09);
  surface.receiveShadow = true;
  g.add(surface);
  g.add(box(w + 0.2, 0.08, 0.3, mat('#5e6b7a'), 0, 0.42, 0.18));
  ['#e8749e', '#4fa3e8', '#53b96a'].forEach((c, i) => g.add(box(0.28, 0.06, 0.06, mat(c), -7.5 + i * 0.4, 0.49, 0.22)));
  g.position.set(BOARD.x, 0, BOARD.z);
  group.add(g);
  return { group: g, surface };
}

// The CEO stage with the Brain hologram floating behind and above the desk.
function ceoStage(group) {
  const g = new THREE.Group();
  const deck = new THREE.Mesh(new THREE.CylinderGeometry(3.0, 3.15, 0.2, 40), mat('#f1dcae', { flatShading: false }));
  deck.scale.set(1.35, 1, 1);
  deck.position.set(0, 0.1, -0.7);
  deck.receiveShadow = true;
  g.add(deck);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(3.05, 0.05, 6, 64), new THREE.MeshStandardMaterial({ color: '#e7a83b', emissive: '#e7a83b', emissiveIntensity: 0.6 }));
  ring.rotation.x = Math.PI / 2;
  ring.scale.set(1.35, 1, 1);
  ring.position.set(0, 0.21, -0.7);
  g.add(ring);
  g.position.set(CEO_DESK.x, 0, CEO_DESK.z);
  group.add(g);
}

function brain(group) {
  const g = new THREE.Group();
  const geo = new THREE.IcosahedronGeometry(0.95, 4);
  const pos = geo.attributes.position;
  const v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    const n = 1 + 0.12 * Math.sin(v.x * 4.8) * Math.sin(v.y * 4.2) * Math.sin(v.z * 5.1) + (Math.abs(v.x) < 0.08 ? -0.08 : 0);
    v.multiplyScalar(n);
    pos.setXYZ(i, v.x * 1.15, v.y * 0.92, v.z);
  }
  geo.computeVertexNormals();
  const core = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: '#ffd9a0', emissive: '#e7a83b', emissiveIntensity: 0.9, roughness: 0.3, flatShading: true }));
  const shell = new THREE.Mesh(new THREE.IcosahedronGeometry(1.45, 1), new THREE.MeshBasicMaterial({ color: '#ffcc66', wireframe: true, transparent: true, opacity: 0.4 }));
  const orbit = new THREE.Mesh(new THREE.TorusGeometry(1.9, 0.025, 6, 72), new THREE.MeshBasicMaterial({ color: '#ffd27a', transparent: true, opacity: 0.8 }));
  orbit.rotation.x = 1.15;
  for (const m of [core, shell, orbit]) m.position.y = BRAIN.y;
  g.add(core, shell, orbit);
  const rings = [];
  const pillar = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.32, BRAIN.y - 0.4, 20, 1, true), new THREE.MeshBasicMaterial({ color: '#ffd27a', transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
  pillar.position.y = (BRAIN.y - 0.4) / 2 + 0.2;
  g.add(pillar);
  const light = new THREE.PointLight('#ffcf7a', 4, 12, 1.6);
  light.position.y = BRAIN.y;
  g.add(light);
  g.position.set(BRAIN.x, 0, BRAIN.z);
  group.add(g);
  return { group: g, core, shell, orbit, rings, pillar, light, particles: null };
}

export function brainParticles(b, count) {
  if (b.particles) {
    b.group.remove(b.particles);
    b.particles.geometry.dispose();
  }
  const n = Math.max(30, Math.min(400, 30 + count * 5));
  const seeds = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    seeds[i * 3] = 1.2 + Math.random() * 1.1;
    seeds[i * 3 + 1] = Math.random() * Math.PI * 2;
    seeds[i * 3 + 2] = (Math.random() - 0.5) * 1.4;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  const pts = new THREE.Points(geo, new THREE.PointsMaterial({ color: '#ffe2a8', size: 0.08, transparent: true, opacity: 0.95, depthWrite: false }));
  pts.userData.seeds = seeds;
  pts.position.y = BRAIN.y;
  b.group.add(pts);
  b.particles = pts;
}

function decorations(group, nav, anim) {
  // bookshelf and water cooler on the west wall
  const shelf = prop('shelf', '#4b8ff2');
  shelf.rotation.y = Math.PI / 2;
  shelf.position.set(-23.55, 0, 4.2);
  group.add(shelf);
  nav.block(-23.55, 4.2, 0.7, 1.6);
  const cooler = new THREE.Group();
  cooler.add(box(0.5, 1.0, 0.5, mat('#e9edf1'), 0, 0.5, 0));
  cooler.add(cyl(0.22, 0.22, 0.55, 10, new THREE.MeshStandardMaterial({ color: '#8fd0ff', transparent: true, opacity: 0.6, roughness: 0.1 }), 0, 1.3, 0));
  cooler.position.set(-23.3, 0, -6.2);
  group.add(cooler);
  nav.block(-23.3, -6.2, 0.6, 0.6);

  // coffee corner
  const coffee = new THREE.Group();
  coffee.add(box(2.6, 0.95, 0.9, mat('#f2ebe1'), 0, 0.475, 0));
  coffee.add(box(2.7, 0.08, 1.0, mat('#7a5a40'), 0, 0.99, 0));
  coffee.add(box(0.5, 0.6, 0.45, mat('#3a3f47'), -0.7, 1.33, 0));
  coffee.add(box(0.3, 0.12, 0.2, glow('#e7a83b', 0.4), -0.7, 1.45, 0.24));
  ['#e8749e', '#4fa3e8', '#53b96a'].forEach((c, i) => coffee.add(cyl(0.07, 0.06, 0.12, 8, mat(c), 0.2 + i * 0.25, 1.09, 0.1)));
  coffee.position.set(-20.6, 0, 16.0);
  group.add(coffee);
  nav.block(-20.6, 16.0, 2.7, 1.0);

  // lounge
  const sofa = new THREE.Group();
  const fabric = mat('#7fa7c9');
  sofa.add(box(3.2, 0.45, 1.1, fabric, 0, 0.3, 0));
  sofa.add(box(3.2, 0.7, 0.3, fabric, 0, 0.75, 0.45));
  sofa.add(box(0.3, 0.6, 1.1, fabric, -1.6, 0.55, 0));
  sofa.add(box(0.3, 0.6, 1.1, fabric, 1.6, 0.55, 0));
  sofa.add(box(0.7, 0.18, 0.5, mat('#f2c14e'), -0.8, 0.62, 0.05));
  sofa.add(box(0.7, 0.18, 0.5, mat('#e8749e'), 0.8, 0.62, 0.05));
  sofa.position.set(17.6, 0, 16.2);
  sofa.rotation.y = Math.PI;
  group.add(sofa);
  nav.block(17.6, 16.2, 3.4, 1.2);
  group.add(cyl(0.6, 0.6, 0.06, 10, mat('#7a5a40'), 13.9, 0.42, 15.6), cyl(0.06, 0.06, 0.4, 6, mat('#555'), 13.9, 0.2, 15.6));
  nav.block(13.9, 15.6, 1.2, 1.2);

  // posters on the north wall, between the windows and the board
  for (const [c, x] of [['#4fa3e8', -11.2], ['#e8749e', 11.2]]) {
    group.add(box(1.4, 1.0, 0.04, mat('#fbf7f0'), x, 2.8, -16.8, { cast: false }));
    group.add(box(1.16, 0.76, 0.02, mat(c), x, 2.8, -16.77, { cast: false }));
  }

  for (const [x, z] of [[-23.0, -15.8], [23.0, -15.8]]) {
    const lamp = floorLamp();
    lamp.position.set(x, 0, z);
    group.add(lamp);
    anim.lamps.push(lamp);
    nav.block(x, z, 0.6, 0.6);
  }

  for (const [x, z, s] of [[-23.0, 15.8, 1.3], [23.1, 6.5, 1.2], [23.1, -6.5, 1.1], [-9.6, -16.0, 0.9], [9.6, -16.0, 0.9], [0, 15.6, 1.0], [-23.2, 10.5, 1.0], [11.9, 4.2, 0.8], [-11.9, 4.2, 0.8], [0, 4.2, 0.8]]) {
    const p = plant(s);
    p.position.set(x, 0, z);
    group.add(p);
    anim.plants.push(p);
    nav.block(x, z, 0.7 * s, 0.7 * s, 0.15);
  }
}

export function buildOffice(scene, layout, config) {
  const group = new THREE.Group();
  scene.add(group);
  const nav = new NavGrid({ minX: FLOOR.minX + 0.6, maxX: FLOOR.maxX - 0.5, minZ: FLOOR.minZ + 0.8, maxZ: FLOOR.maxZ - 0.5, cell: 0.5 });
  const anim = { props: [], plants: [], lamps: [], roads: [], ghosts: new Map(), windows: [] };

  // diorama base and floor
  const W = FLOOR.maxX - FLOOR.minX;
  const D = FLOOR.maxZ - FLOOR.minZ;
  const baseMat = mat('#a07a55');
  group.add(box(W + 1, 1.6, D + 1, baseMat, 0, -0.86, 0, { cast: false }));
  group.add(box(W + 1.3, 0.1, D + 1.3, mat('#7d5b3e'), 0, -1.6, 0, { cast: false }));
  const floorMat = new THREE.MeshStandardMaterial({ map: plankTexture(), roughness: 0.9 });
  const floor = new THREE.Mesh(new THREE.BoxGeometry(W, 0.12, D), floorMat);
  floor.position.y = -0.06;
  floor.receiveShadow = true;
  group.add(floor);

  // back walls, cut-away
  const wallMat = mat('#f4ede3', { flatShading: false });
  group.add(box(W + 0.8, 5.0, 0.4, wallMat, 0, 2.5, FLOOR.minZ - 0.2));
  group.add(box(0.4, 5.0, D + 0.8, wallMat, FLOOR.minX - 0.2, 2.5, 0));
  group.add(box(W + 0.8, 0.3, 0.46, mat('#d8c3a5'), 0, 0.15, FLOOR.minZ + 0.02));
  group.add(box(0.46, 0.3, D + 0.8, mat('#d8c3a5'), FLOOR.minX + 0.02, 0.15, 0));
  group.add(box(W + 0.8, 0.18, 0.5, mat('#e2d4c0'), 0, 5.05, FLOOR.minZ - 0.2));
  group.add(box(0.5, 0.18, D + 0.8, mat('#e2d4c0'), FLOOR.minX - 0.2, 5.05, 0));
  anim.windows.push(windowOn(group, { x: -17.2, y: 2.8, z: FLOOR.minZ + 0.02, w: 6.4, h: 2.6 }));
  anim.windows.push(windowOn(group, { x: 17.2, y: 2.8, z: FLOOR.minZ + 0.02, w: 6.4, h: 2.6 }));
  anim.windows.push(windowOn(group, { x: FLOOR.minX + 0.02, y: 2.8, z: -1.2, w: 5.6, h: 2.6, rotY: Math.PI / 2 }));
  anim.windows.push(windowOn(group, { x: FLOOR.minX + 0.02, y: 2.8, z: 9.6, w: 5.6, h: 2.6, rotY: Math.PI / 2 }));

  const bd = board(group);
  nav.block(BOARD.x, BOARD.z + 0.3, BOARD.width + 0.6, 0.9, 0);
  ceoStage(group);
  const b = brain(group);
  brainParticles(b, 0);

  for (const z of layout.rooms) {
    zoneRug(group, z);
    group.add(bayMark(z));
    const p = prop(z.prop, z.color);
    const px = z.x + z.w / 2 - 0.8;
    const pz = z.z - z.d / 2 + 0.9;
    p.position.set(px, 0, pz);
    p.rotation.y = -Math.PI / 6;
    group.add(p);
    anim.props.push(p);
    nav.block(px, pz, 1.2, 1.0, 0.15);
  }

  const stations = new Map();
  for (const [id, d] of layout.desks) {
    const color = d.kind === 'ceo' ? config.ceo.color : config.teams[d.team]?.color ?? '#999';
    const piece = deskPiece(d, color);
    group.add(piece.group);
    stations.set(id, { desk: d, screen: piece.screen });
    nav.block(d.x, d.z, piece.width, 0.86, 0.12);
  }
  for (const [team, slots] of layout.bays) {
    const color = config.teams[team].color;
    anim.ghosts.set(team, slots.map((s) => {
      const gd = ghostDesk(s, color);
      group.add(gd);
      nav.block(s.x, s.z, 1.75, 0.86, 0.12);
      return gd;
    }));
  }
  decorations(group, nav, anim);

  const applyTheme = (night) => {
    for (const w of anim.windows) w.color.set(night ? '#2a3550' : '#ffffff');
    for (const l of anim.lamps) l.userData.bulb.emissiveIntensity = night ? 2.2 : 0.8;
    b.light.intensity = night ? 9 : 4;
    floorMat.color.set(night ? '#b9a993' : '#ffffff');
  };
  return { group, nav, stations, anim, brain: b, board: bd, applyTheme };
}
