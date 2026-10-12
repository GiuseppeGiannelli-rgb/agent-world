import * as THREE from 'three';

// Shared low-poly building blocks.

const matCache = new Map();
export function mat(color, opts = {}) {
  const key = `${color}|${JSON.stringify(opts)}`;
  if (!matCache.has(key)) matCache.set(key, new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0.02, flatShading: true, ...opts }));
  return matCache.get(key);
}

export function glow(color, intensity = 1, opts = {}) {
  return mat(color, { emissive: color, emissiveIntensity: intensity, ...opts });
}

export function box(w, h, d, material, x = 0, y = 0, z = 0, { cast = true, receive = true } = {}) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
  m.position.set(x, y, z);
  m.castShadow = cast;
  m.receiveShadow = receive;
  return m;
}

export function cyl(rt, rb, h, seg, material, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), material);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

export function tint(hex, amount) {
  // amount > 0 mixes toward white, < 0 toward black
  const c = new THREE.Color(hex);
  const target = amount > 0 ? new THREE.Color('#ffffff') : new THREE.Color('#000000');
  return `#${c.lerp(target, Math.abs(amount)).getHexString()}`;
}

export function roundedRect(w, d, r) {
  const s = new THREE.Shape();
  const x = -w / 2;
  const y = -d / 2;
  s.moveTo(x + r, y);
  s.lineTo(x + w - r, y);
  s.quadraticCurveTo(x + w, y, x + w, y + r);
  s.lineTo(x + w, y + d - r);
  s.quadraticCurveTo(x + w, y + d, x + w - r, y + d);
  s.lineTo(x + r, y + d);
  s.quadraticCurveTo(x, y + d, x, y + d - r);
  s.lineTo(x, y + r);
  s.quadraticCurveTo(x, y, x + r, y);
  return s;
}

export function slab(w, d, r, depth, material) {
  const m = new THREE.Mesh(new THREE.ExtrudeGeometry(roundedRect(w, d, r), { depth, bevelEnabled: false }), material);
  m.rotation.x = -Math.PI / 2;
  m.receiveShadow = true;
  return m;
}

export function canvasTexture(w, h, draw) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  draw(c.getContext('2d'), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

export function plant(size = 1) {
  const p = new THREE.Group();
  p.add(cyl(0.3 * size, 0.22 * size, 0.46 * size, 8, mat('#e9e4dc'), 0, 0.23 * size, 0));
  const leaf = mat('#4fae63');
  const leaf2 = mat('#3c9a55');
  const blobs = [[0, 0.85, 0, 0.4], [0.22, 1.12, 0.1, 0.3], [-0.2, 1.18, -0.08, 0.28], [0.02, 1.45, 0, 0.24]];
  blobs.forEach(([bx, by, bz, r], i) => {
    const m = new THREE.Mesh(new THREE.IcosahedronGeometry(r * size, 0), i % 2 ? leaf2 : leaf);
    m.position.set(bx * size, by * size, bz * size);
    m.castShadow = true;
    p.add(m);
  });
  p.userData.sway = Math.random() * Math.PI * 2;
  return p;
}

export function floorLamp(lightColor = '#fff1cf') {
  const g = new THREE.Group();
  g.add(cyl(0.035, 0.035, 2.1, 6, mat('#2f3440'), 0, 1.05, 0));
  g.add(cyl(0.22, 0.26, 0.05, 10, mat('#2f3440'), 0, 0.03, 0));
  const shade = new THREE.Mesh(new THREE.SphereGeometry(0.24, 12, 8), new THREE.MeshStandardMaterial({ color: lightColor, emissive: lightColor, emissiveIntensity: 1.2 }));
  shade.position.y = 2.2;
  g.add(shade);
  g.userData.bulb = shade.material;
  return g;
}
