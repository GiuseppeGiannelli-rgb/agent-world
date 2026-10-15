import * as THREE from 'three';
import { MapControls } from 'three/addons/controls/MapControls.js';
import { Actor } from './character.js';
import { applyFrustum, fitOffice, maxZoomFor, MIN_ZOOM, REF_UNITS_PER_PX, safeRect, scaleAt, VIEW_OFFSET, zoomFor } from './framing.js';
import { t } from '../i18n.js';
import { Fx } from './fx.js';
import { BOARD, BRAIN, boardFace, brainParticles, buildOffice, cardSlot, columnOf, computeLayout, DESK_TOP, ENVELOPE, groundAt, SPOTS, WORLD } from './office.js';

const TOOL_ICON = {
  list_files: '📂',
  read_file: '📖',
  write_file: '✍️',
  web_search: '🔎',
  web_fetch: '🌐',
  run_command: '⚙️',
  generate_image: '🎨',
  generate_speech: '🎙️',
  search_skills: '📚',
  read_skill: '📘',
  remember: '🧠',
  recall: '🧠',
  ask_lead: '❓',
  ask_user: '🙋',
  finish: '✅',
};

const KIND_COLOR = {
  goal: '#ffffff',
  brief: '#f5c451',
  assign: '#f5c451',
  plan: '#f5c451',
  split: '#f5c451',
  skills: '#e3b23c',
  prompt: '#1fb5a8',
  spawn: '#ffffff',
  escalate: '#b18cff',
  question: '#4b8ff2',
  answer: '#f5c451',
  review: '#f28a3a',
  pass: '#3fbf6f',
  revise: '#ef4f5f',
  deliver: '#3fbf6f',
  stuck: '#ef4f5f',
  guidance: '#f5c451',
  error: '#ef4f5f',
  chat: '#ffffff',
  ask_user: '#ffffff',
  reply: '#ffffff',
};

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const short = (s, n = 46) => {
  const t = String(s ?? '').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n - 1)}…` : t;
};
const LIVE_TASK = ['assigned', 'working', 'review', 'revise'];
// the states shown at the desk: they wait for the end of a pickup trip (A10, N12)
const AT_DESK = ['thinking', 'tool'];
// Below this size on screen (a zoom of the old fixed framing) the labels of idle
// workers hide: from 0.52 down they overlap their lead's at the desks (T7 report).
const FAR_ZOOM = 0.55;

function cardTexture(id, title, color, state, isWs) {
  const c = document.createElement('canvas');
  c.width = 300;
  c.height = 84;
  const g = c.getContext('2d');
  g.fillStyle = state === 'done' ? '#eaf8ee' : state === 'failed' ? '#e9e9e9' : isWs ? '#fff8e6' : '#ffffff';
  g.fillRect(0, 0, 300, 84);
  g.fillStyle = state === 'failed' ? '#9a9a9a' : color;
  g.fillRect(0, 0, 12, 84);
  if (isWs) {
    g.strokeStyle = color;
    g.lineWidth = 6;
    g.strokeRect(3, 3, 294, 78);
  }
  g.fillStyle = '#7b7368';
  g.font = '700 20px "Segoe UI", system-ui, sans-serif';
  g.fillText(id.toUpperCase(), 24, 30);
  g.fillStyle = state === 'failed' ? '#8a8a8a' : '#262b36';
  g.font = '600 22px "Segoe UI", system-ui, sans-serif';
  g.fillText(short(title, 22), 24, 64);
  if (state === 'done') {
    g.fillStyle = '#3fbf6f';
    g.beginPath();
    g.arc(272, 26, 15, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = '#fff';
    g.lineWidth = 4;
    g.beginPath();
    g.moveTo(264, 26);
    g.lineTo(270, 32);
    g.lineTo(280, 20);
    g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export class World {
  constructor({ canvas, labels, minimap, onPick, onPickRoom }) {
    this.canvas = canvas;
    this.labelsEl = labels;
    this.minimap = minimap;
    this.onPick = onPick;
    this.onPickRoom = onPickRoom;
    this.actors = new Map();
    this.cards = new Map(); // key -> card ("ws:w1" or task id)
    this.cubes = new Map(); // key -> { mesh, owner }
    this.tasks = new Map();
    this.workstreams = new Map();
    this.runId = null;
    this.clock = new THREE.Clock();
    this.tmp = new THREE.Vector3();
    this.labels = new Map();
    this.roomLabels = [];
    this.flows = [];
    this.hovered = null;
    this.night = true;
    this.frameNo = 0;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.75));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer = renderer;

    const scene = new THREE.Scene();
    this.scene = scene;
    this.fx = new Fx(scene);

    this.hemi = new THREE.HemisphereLight('#fff6e8', '#b59c80', 1.2);
    scene.add(this.hemi);
    const sun = new THREE.DirectionalLight('#fff0d6', 2.2);
    sun.position.set(22, 40, 20);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -40, right: 40, top: 36, bottom: -36, near: 1, far: 120 });
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.03;
    this.sun = sun;
    scene.add(sun);
    this.fill = new THREE.DirectionalLight('#cfe3ff', 0.4);
    this.fill.position.set(-30, 18, -10);
    scene.add(this.fill);

    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 400);
    this.controls = new MapControls(this.camera, canvas);
    // maxZoom follows the projection: applyView() sets it
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08, screenSpacePanning: false, minZoom: MIN_ZOOM, minPolarAngle: 0.3, maxPolarAngle: 1.15, zoomToCursor: true });
    // Framing (framing.js): the panels float over the canvas, so the office is fitted
    // into the free area and the projection draws the camera target at its centre.
    this.insets = { top: 0, right: 0, bottom: 0, left: 0 }; // UI over the canvas, px per edge
    this.view = { unitsPerPx: REF_UNITS_PER_PX, lensX: 0, lensY: 0 }; // projection now applied
    this.framedOnce = false; // insets received at least once
    this.resizedAt = -1;
    // Automatic: the view follows the panels and the window. Once the user moves it
    // (drag, wheel, pinch, focus, minimap) it stays where they put it until ⌂ (S3).
    this.autoFrame = true;

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    // Presses on the canvas by pointer: where each went down and where it is now. One
    // released within CLICK px of where it went down is a click and picks an agent. One
    // that travels CLICK px, or two that pinch by as much, while the controls run a
    // gesture, takes the view; so does a wheel step the controls zoom with. The
    // controls' canvas listeners were added first: here their state is already set.
    const CLICK = 5;
    const presses = new Map(); // pointerId -> { x0, y0, x, y }
    let multi = false; // more than one pointer down since the last full release: no click
    let spread0 = 0; // distance between the first two presses since the set last changed
    const spread = () => {
      const [a, b] = presses.values();
      return b ? Math.hypot(a.x - b.x, a.y - b.y) : 0;
    };
    const takeView = () => {
      this.autoFrame = false;
      this.fx.stop(this.camera); // the controls own the camera now
    };
    // MapControls pans by pulling the floor point a press grabbed back under the pointer.
    // When code moves the picture under a held press, that point drifts away from the
    // pointer, and the next pointermove (even below CLICK px) would drag the view all the
    // way back: the grab follows the picture instead. _handleMouseDownPan is internal to
    // MapControls r186 (three is pinned to it); manual-mode.js checks the behaviour.
    this.regrab = () => {
      const [p] = presses.values();
      if (!p || this.controls.state !== 2) return; // 2: PAN (Controls.state); touch pans are incremental
      this.camera.updateMatrixWorld(); // lookAt() leaves matrixWorld as it was
      this.controls._handleMouseDownPan({ clientX: p.x, clientY: p.y });
    };
    const release = (e) => {
      const p = presses.get(e.pointerId);
      presses.delete(e.pointerId);
      const click = p && !multi && Math.hypot(e.clientX - p.x0, e.clientY - p.y0) < CLICK;
      if (!presses.size) multi = false;
      spread0 = spread();
      return click;
    };
    canvas.addEventListener('pointerdown', (e) => {
      presses.set(e.pointerId, { x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY });
      multi ||= presses.size > 1;
      spread0 = spread();
    });
    canvas.addEventListener('pointercancel', release);
    canvas.addEventListener('pointerup', (e) => {
      if (!release(e)) return;
      const id = this.pick(e);
      if (id) this.onPick?.(id);
    });
    canvas.addEventListener('wheel', (e) => {
      // the controls cancel the page scroll for the wheel steps they zoom with
      if (e.defaultPrevented && e.deltaY) takeView();
    }, { passive: true });
    // The labels take the pointer for their clicks, so a wheel step over one would never
    // reach the canvas: it is handed on, the same step at the same point, to the controls
    // and to the check above (spec 02, E7). It must be cancelable, the check reads
    // defaultPrevented; and the listener is not passive, or a touchpad pinch (Ctrl) over
    // a label would zoom the page.
    labels.addEventListener('wheel', (e) => {
      e.preventDefault();
      const { deltaX, deltaY, deltaZ, deltaMode, clientX, clientY, screenX, screenY, ctrlKey, shiftKey, altKey, metaKey } = e;
      canvas.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX, deltaY, deltaZ, deltaMode, clientX, clientY, screenX, screenY, ctrlKey, shiftKey, altKey, metaKey }));
    }, { passive: false });
    canvas.addEventListener('pointermove', (e) => {
      const p = presses.get(e.pointerId);
      if (p && !e.buttons) release(e); // its release never reached the canvas
      else if (p) {
        p.x = e.clientX;
        p.y = e.clientY;
        const travelled = Math.hypot(p.x - p.x0, p.y - p.y0) >= CLICK || Math.abs(spread() - spread0) >= CLICK;
        if (travelled && this.controls.state !== -1) takeView(); // -1: no gesture (Controls.state)
      }
      const id = this.pick(e);
      if (id !== this.hovered) {
        this.hovered = id;
        canvas.style.cursor = id ? 'pointer' : '';
        for (const [aid, label] of this.labels) label.tag.classList.toggle('hover', aid === id);
      }
    });
    minimap?.addEventListener('click', (e) => {
      const r = minimap.getBoundingClientRect();
      const x = WORLD.minX + ((e.clientX - r.left) / r.width) * (WORLD.maxX - WORLD.minX);
      const z = WORLD.minZ + ((e.clientY - r.top) / r.height) * (WORLD.maxZ - WORLD.minZ);
      this.autoFrame = false;
      this.panTo(x, z);
    });

    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    renderer.setAnimationLoop(() => this.frame());
  }

  // The whole office in the area the panels leave free, seen from the usual angle.
  // It hands the view back to the automatic framing (⌂).
  resetView({ animate = false, duration = 0.6 } = {}) {
    this.autoFrame = true;
    const fit = fitOffice({ width: this.width, height: this.height, insets: this.insets, envelope: ENVELOPE });
    this.moveCamera({
      target: fit.target,
      offset: VIEW_OFFSET,
      zoom: 1,
      view: { unitsPerPx: fit.unitsPerPx, lensX: fit.lensX, lensY: fit.lensY },
      duration: animate ? duration : 0,
    });
  }

  // How far the UI reaches into the canvas from each edge (measured by main.js).
  // A panel opening or closing re-frames the office smoothly; the first insets and
  // those that change together with the window size apply at once. In manual mode
  // the view stays: the insets only wait for ⌂ and for the moves that centre a point.
  setInsets(insets) {
    const sides = ['top', 'right', 'bottom', 'left'];
    if (this.framedOnce && sides.every((k) => Math.abs((insets[k] ?? 0) - this.insets[k]) < 0.5)) return;
    this.insets = Object.fromEntries(sides.map((k) => [k, insets[k] ?? 0]));
    const instant = !this.framedOnce || this.resizedAt === this.frameNo;
    this.framedOnce = true;
    if (!this.autoFrame) return;
    this.resetView({ animate: !instant, duration: 0.35 });
    if (instant) this.renderNow();
  }

  resize() {
    const el = this.canvas.parentElement;
    this.width = el.clientWidth;
    this.height = el.clientHeight;
    this.renderer.setSize(this.width, this.height, false);
    this.resizedAt = this.frameNo;
    // manual mode keeps scale, lens and target: the picture keeps its size and its
    // place around the canvas centre (S3.5)
    if (this.autoFrame) this.resetView();
    else this.applyView();
    // setSize cleared the canvas after this frame was drawn: draw it again before
    // the browser paints, or a resize flashes an empty or stretched picture
    this.renderNow();
  }

  // The projection in this.view, and the zoom limit that goes with it. OrbitControls
  // clamps camera.zoom into [minZoom, maxZoom] at every update, so the limit moves
  // with every step of a move that changes the scale. One set for the end of the move
  // clamps a zoom that is still above it: the next step hides that, but a drag or a
  // wheel that stops the move leaves the cut, and the picture jumps. Every change of the
  // picture made by code passes here, so a pan press in progress grabs again here.
  applyView() {
    this.controls.maxZoom = maxZoomFor(this.view.unitsPerPx);
    applyFrustum(this.camera, this.width, this.height, this.view.unitsPerPx, this.view.lensX, this.view.lensY);
    this.regrab();
  }

  // World units per CSS px on screen now: what close-ups and labels measure against.
  screenScale() {
    return this.view.unitsPerPx / this.camera.zoom;
  }

  renderNow() {
    this.renderer.render(this.scene, this.camera);
    this.updateLabels();
  }

  setTheme(night) {
    this.night = night;
    this.hemi.color.set(night ? '#8f9fd6' : '#fff6e8');
    this.hemi.groundColor.set(night ? '#2a2333' : '#b59c80');
    this.hemi.intensity = night ? 0.9 : 1.25;
    this.sun.color.set(night ? '#c3cdf5' : '#fff0d6');
    this.sun.intensity = night ? 0.9 : 2.2;
    this.fill.intensity = night ? 0.25 : 0.4;
    this.renderer.toneMappingExposure = night ? 1.15 : 1.05;
    this.hub?.applyTheme(night);
  }

  pick(e) {
    const r = this.canvas.getBoundingClientRect();
    this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects([...this.actors.values()].map((a) => a.root), true);
    for (const h of hits) {
      let o = h.object;
      while (o && !o.userData.agentId) o = o.parent;
      if (o) return o.userData.agentId;
    }
    return null;
  }

  // ---------- build ----------

  build(config, agents) {
    const key = JSON.stringify([config.staff, Object.values(config.teams).map((t) => [t.color, t.label, t.maxSubAgents, t.prop])]);
    if (this.buildKey === key) return;
    this.buildKey = key;
    if (this.hub) this.scene.remove(this.hub.group);
    for (const a of this.actors.values()) this.scene.remove(a.root);
    this.actors.clear();
    for (const l of this.labels.values()) {
      l.tag.remove();
      l.bubble.remove();
    }
    this.labels.clear();
    this.roomLabels.forEach((z) => z.el.remove());
    this.roomLabels = [];
    this.brainLabel?.remove();

    this.config = config;
    this.layout = computeLayout(config);
    this.hub = buildOffice(this.scene, this.layout, config);
    this.ground = (x, z) => groundAt(this.layout, x, z);
    this.setTheme(this.night);

    for (const a of agents) this.addActor(a);
    for (const r of this.layout.rooms) {
      const el = document.createElement('button');
      el.className = 'room-label';
      el.style.setProperty('--team', r.color);
      el.innerHTML = `<i></i><b>${esc(r.label)}</b><span></span>`;
      el.addEventListener('click', () => this.onPickRoom?.(r.team));
      this.labelsEl.append(el);
      // in the middle of the front edge, just inside: no desk there, the lead and the
      // workers sit at the back and the sub-agents in the bay behind it (spec 02, N4)
      this.roomLabels.push({ el, team: r.team, pos: new THREE.Vector3(r.x, 0.1, r.z + r.d / 2 - 0.2) });
    }
    this.brainLabel = document.createElement('div');
    this.brainLabel.className = 'brain-label';
    this.brainLabel.innerHTML = `<b>THE BRAIN</b><span>${t('world.brain', { n: this.brainShown ?? 0 })}</span>`;
    this.labelsEl.append(this.brainLabel);
    for (const a of agents) this.applyState(a, true);
  }

  // Spec 06: a new language rewrites the words only; build() would rebuild the scene
  // and move every agent back to its desk in the middle of a run.
  relabel(teamName) {
    for (const r of this.roomLabels) r.el.querySelector('b').textContent = teamName(r.team);
    if (this.brainLabel) this.brainLabel.querySelector('span').textContent = t('world.brain', { n: this.brainShown ?? 0 });
    const surface = this.hub?.board?.surface;
    const columns = ['todo', 'running', 'review', 'done'].map((k) => t(`world.column.${k}`));
    if (surface && surface.material.map?.userData.columns?.join() !== columns.join()) {
      surface.material.map?.dispose();
      surface.material.map = boardFace(columns);
      surface.material.needsUpdate = true;
    }
  }

  colorOf(agent) {
    if (agent.kind === 'ceo' || agent.team === 'ceo') return this.config.ceo.color;
    return this.config.teams[agent.team]?.color ?? '#999';
  }

  seatFor(agent) {
    if (agent.kind === 'sub') return this.layout.bays.get(agent.team)?.[agent.slot ?? 0]?.seat ?? null;
    return this.layout.desks.get(agent.id)?.seat ?? null;
  }

  addActor(agent) {
    if (this.actors.has(agent.id)) return this.actors.get(agent.id);
    const seat = this.seatFor(agent);
    if (!seat) return null;
    const actor = new Actor({ agent, color: this.colorOf(agent), seat, nav: this.hub.nav, groundAt: this.ground });
    this.scene.add(actor.root);
    this.actors.set(agent.id, actor);
    const tag = document.createElement('div');
    tag.className = `tag${agent.kind === 'sub' ? ' sub' : ''}${agent.kind === 'lead' ? ' lead' : ''}`;
    tag.innerHTML = `<i style="background:${this.colorOf(agent)}"></i>${esc(agent.name)}<b></b>`;
    tag.addEventListener('click', () => this.onPick?.(agent.id));
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    this.labelsEl.append(tag, bubble);
    this.labels.set(agent.id, { tag, bubble, state: tag.querySelector('b'), hideAt: 0 });
    return actor;
  }

  removeActor(id) {
    const a = this.actors.get(id);
    if (!a) return;
    this.scene.remove(a.root);
    this.actors.delete(id);
    const l = this.labels.get(id);
    l?.tag.remove();
    l?.bubble.remove();
    this.labels.delete(id);
  }

  // ---------- helpers ----------

  actorHead(id) {
    if (id === 'brain') return new THREE.Vector3(BRAIN.x, BRAIN.y, BRAIN.z);
    const a = this.actors.get(id);
    return a ? a.headWorld(new THREE.Vector3()) : new THREE.Vector3(BRAIN.x, BRAIN.y, BRAIN.z);
  }

  bubble(id, html, ms = 3200, cls = '') {
    const l = this.labels.get(id);
    if (!l) return;
    l.bubble.innerHTML = html;
    l.bubble.className = `bubble show ${cls}`;
    l.hideAt = performance.now() + ms;
  }

  deskOf(id) {
    const a = this.actors.get(id);
    if (a?.kind === 'sub') {
      const s = this.layout.bays.get(a.team)?.[this.subSlot(a)];
      return s ? { ...s, w: 1.75 } : null;
    }
    const d = this.layout.desks.get(id);
    return d ? { ...d, w: d.big ? 2.3 : 1.75 } : null;
  }

  subSlot(actor) {
    const slots = this.layout.bays.get(actor.team) ?? [];
    return Math.max(0, slots.findIndex((s) => Math.hypot(s.seat.x - actor.seat.x, s.seat.z - actor.seat.z) < 0.01));
  }

  deskSpot(id, index = 0) {
    const d = this.deskOf(id);
    if (!d) return this.actorHead(id);
    return new THREE.Vector3(d.x - d.w / 2 + 0.32 + (index % 5) * 0.4, DESK_TOP + (d.kind === 'ceo' ? 0.2 : 0), d.z - 0.12);
  }

  besideSeat(target) {
    const nav = this.hub.nav;
    for (const dx of [1.0, -1.0]) {
      const p = { x: target.seat.x + dx, z: target.seat.z - 0.1 };
      if (nav.freeAt(p.x, p.z)) return p;
    }
    return { x: target.seat.x, z: target.seat.z - 1.1 };
  }

  // The one camera animation: target, orbit offset, zoom and projection (scale and
  // lens shift, see framing.js) eased together. A newer move takes over from wherever
  // the camera is, and what it leaves unset, down to single view fields, keeps heading
  // where the replaced move was going (a pan during a focus still zooms in). Zoom is
  // relative to the final scale; `scale` asks instead for a size on screen (world
  // units per px) whatever the framing, within the zoom limits.
  moveCamera({ target, offset, zoom, scale, view, duration = 0.7 } = {}) {
    this.settleControls();
    const goal = this.fx.active(this.camera)?.goal;
    const fromTarget = this.controls.target.clone();
    const fromOffset = this.camera.position.clone().sub(fromTarget);
    const fromZoom = this.camera.zoom;
    const fromView = { ...this.view };
    const toView = { ...(goal?.view ?? fromView), ...view };
    const to = {
      target: (target ?? goal?.target ?? fromTarget).clone(),
      offset: (offset ?? goal?.offset ?? fromOffset).clone(),
      zoom: scale ? zoomFor(scale, toView.unitsPerPx) : (zoom ?? goal?.zoom ?? fromZoom),
      view: toView,
    };
    // the orbit turns the short way round; an unchanged offset is kept exactly
    const turning = !to.offset.equals(fromOffset);
    const a = new THREE.Spherical().setFromVector3(fromOffset);
    const b = new THREE.Spherical().setFromVector3(to.offset);
    const dTheta = ((b.theta - a.theta + 3 * Math.PI) % (2 * Math.PI)) - Math.PI;
    const lerp = (x, y, e) => x + (y - x) * e;
    const step = (e) => {
      this.controls.target.lerpVectors(fromTarget, to.target, e);
      if (turning) this.camera.position.setFromSphericalCoords(lerp(a.radius, b.radius, e), lerp(a.phi, b.phi, e), a.theta + dTheta * e);
      else this.camera.position.copy(fromOffset);
      this.camera.position.add(this.controls.target);
      this.camera.lookAt(this.controls.target); // the controls only re-aim on their next update
      // zoom and scale in ratio: the size on screen keeps the pace of the target
      this.camera.zoom = scaleAt(fromZoom, to.zoom, e);
      this.view.unitsPerPx = scaleAt(fromView.unitsPerPx, to.view.unitsPerPx, e);
      this.view.lensX = lerp(fromView.lensX, to.view.lensX, e);
      this.view.lensY = lerp(fromView.lensY, to.view.lensY, e);
      this.applyView();
    };
    if (!(duration > 0)) {
      this.fx.stop(this.camera);
      step(1);
      return;
    }
    let t = 0;
    this.fx.track(this.camera, {
      goal: to,
      update: (dt) => {
        t = Math.min(1, t + dt / duration);
        step(1 - (1 - t) ** 3);
        if (t < 1) return true;
        this.settleControls(); // a click made during the move leaves no drift behind
        return false;
      },
    });
  }

  // Drops what the controls still mean to apply and keeps the camera as it is on
  // screen. With damping, a drag leaves inertia, and a pan the controls worked out
  // while a move ran under a press is still pending: applying it would make the view
  // jump or drift away from where the move went.
  settleControls() {
    const { camera, controls } = this;
    const target = controls.target.clone();
    const position = camera.position.clone();
    const { zoom } = camera;
    const damping = controls.enableDamping;
    controls.enableDamping = false;
    controls.update(); // spends the pending pan, rotation and zoom, and zeroes them
    controls.enableDamping = damping;
    controls.target.copy(target);
    camera.position.copy(position);
    camera.lookAt(target);
    camera.zoom = zoom;
    camera.updateProjectionMatrix();
  }

  // The lens shift that draws the camera target at the centre of the free area as the
  // panels are now: in manual mode the view may still be framed for older insets.
  centreLens() {
    const safe = safeRect(this.width, this.height, this.insets);
    return { lensX: safe.cx - this.width / 2, lensY: safe.cy - this.height / 2 };
  }

  panTo(x, z) {
    this.moveCamera({ target: new THREE.Vector3(x, 0, z), view: this.centreLens() });
  }

  // A focus is the user's choice of what to look at: the view goes manual. The move
  // takes over the running one instead of stopping it, so it keeps its unfinished goal.
  // Close-ups keep the size on screen they had with the old fixed framing (S2.5); an
  // agent focus never backs away from a closer view.
  focus(agentId) {
    const a = this.actors.get(agentId);
    if (!a) return;
    this.autoFrame = false;
    const scale = Math.min(this.screenScale(), REF_UNITS_PER_PX / 2.2);
    this.moveCamera({ target: new THREE.Vector3(a.position.x, 0, a.position.z), scale, view: this.centreLens() });
  }

  focusRoom(team) {
    const r = this.layout.rooms.find((x) => x.team === team);
    if (!r) return;
    this.autoFrame = false;
    this.moveCamera({ target: new THREE.Vector3(r.x, 0, r.z), scale: REF_UNITS_PER_PX / 2, view: this.centreLens() });
  }

  // ---------- cards & cubes ----------

  resetRun(runId) {
    this.runId = runId;
    for (const c of this.cards.values()) this.scene.remove(c.mesh);
    for (const c of this.cubes.values()) {
      this.fx.stop(c.mesh);
      c.mesh.parent?.remove(c.mesh);
    }
    for (const a of this.actors.values()) a.carrying = null;
    this.cards.clear();
    this.cubes.clear();
    this.tasks.clear();
    this.workstreams.clear();
  }

  teamColor(team) {
    return this.config.teams[team]?.color ?? '#999';
  }

  makeCard(key, item, isWs, from) {
    const color = this.teamColor(item.team);
    const visual = isWs ? 'open' : this.visualOf(item.status);
    const material = new THREE.MeshStandardMaterial({ map: cardTexture(item.id, item.title, color, visual, isWs), roughness: 0.7 });
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(1.45, 0.4, 0.05), material);
    mesh.castShadow = true;
    mesh.position.copy(from ?? cardSlot(isWs ? 0 : columnOf(item.status), 0));
    this.scene.add(mesh);
    const card = { key, mesh, material, isWs, visual, target: mesh.position.clone(), flying: false, pulse: 0 };
    this.cards.set(key, card);
    return card;
  }

  visualOf(status) {
    return status === 'done' ? 'done' : status === 'failed' || status === 'skipped' ? 'failed' : 'open';
  }

  layoutCards() {
    const byCol = [[], [], [], []];
    for (const [key, card] of this.cards) {
      if (card.isWs) byCol[0].push({ key, order: `0${key}` });
      else {
        const t = this.tasks.get(key);
        if (t) byCol[columnOf(t.status)].push({ key, order: `1${t.id.padStart(8, '0')}` });
      }
    }
    byCol.forEach((list, col) => {
      list.sort((a, b) => a.order.localeCompare(b.order, undefined, { numeric: true }));
      list.forEach((x, i) => this.cards.get(x.key).target.copy(cardSlot(col, i)));
    });
  }

  refreshCard(task) {
    const card = this.cards.get(task.id);
    if (!card) return;
    const visual = this.visualOf(task.status);
    if (card.visual !== visual) {
      card.visual = visual;
      card.material.map.dispose();
      card.material.map = cardTexture(task.id, task.title, this.teamColor(task.team), visual, false);
      card.material.needsUpdate = true;
      card.pulse = 1;
    }
  }

  removeCard(key) {
    const c = this.cards.get(key);
    if (!c) return;
    this.scene.remove(c.mesh);
    this.cards.delete(key);
    this.layoutCards();
  }

  makeCube(team, size = 0.32) {
    const color = this.teamColor(team);
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(size, size, size), new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.6, roughness: 0.35, flatShading: true }));
    mesh.castShadow = true;
    mesh.add(new THREE.Mesh(new THREE.BoxGeometry(size * 1.45, size * 1.45, size * 1.45), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.18, depthWrite: false, blending: THREE.AdditiveBlending })));
    mesh.userData.cube = true;
    return mesh;
  }

  // Frees a cube from whatever moves it (a hand, a flight still running) and leaves it
  // in the scene where it is. Every cube hand-over starts here, so no stale flight
  // can land later and put the cube back in someone's hands.
  toScene(mesh) {
    this.fx.stop(mesh);
    if (mesh.parent === this.scene) return;
    const p = mesh.getWorldPosition(new THREE.Vector3());
    mesh.parent?.remove(mesh);
    mesh.position.copy(p);
    this.scene.add(mesh);
  }

  // The actor owns the cube as soon as the flight starts: the flight is only the picture.
  carryInto(actor, mesh) {
    if (actor.carrying && actor.carrying !== mesh) this.dropCube(actor);
    this.toScene(mesh);
    actor.carrying = mesh;
    this.fx.fly(mesh, () => actor.root.localToWorld(new THREE.Vector3(0, 0.86, 0.42)), {
      duration: 0.45,
      height: 0.6,
      done: () => {
        if (actor.carrying === mesh) actor.carry(mesh);
      },
    });
  }

  dropCube(actor) {
    const mesh = actor.release();
    if (!mesh) return;
    this.toScene(mesh);
    const onDesk = [...this.cubes.values()].filter((c) => c.owner === actor.id && c.mesh !== mesh && c.mesh.parent === this.scene).length;
    mesh.position.copy(this.deskSpot(actor.id, onDesk));
  }

  pickupWs(lead, wsId) {
    const ws = this.workstreams.get(wsId);
    const card = this.cards.get(`ws:${wsId}`);
    const mesh = this.makeCube(ws?.team ?? lead.team, 0.5);
    mesh.position.copy(card ? card.mesh.position : this.actorHead(lead.id));
    this.removeCard(`ws:${wsId}`);
    this.scene.add(mesh);
    this.cubes.set(`ws:${wsId}`, { mesh, owner: lead.id });
    this.carryInto(lead, mesh);
  }

  // The lead's workstream cube splits into one cube per subtask on the lead's desk.
  splitWs(wsId, leadId, tasks) {
    const big = this.cubes.get(`ws:${wsId}`);
    const lead = this.actors.get(leadId);
    let origin = this.deskSpot(leadId, 0);
    if (big) {
      if (lead?.carrying === big.mesh) lead.release();
      this.toScene(big.mesh);
      origin = big.mesh.position.clone();
      this.scene.remove(big.mesh);
      this.cubes.delete(`ws:${wsId}`);
      this.fx.burst(origin, this.teamColor(tasks[0]?.team), { count: 14, speed: 2 });
    }
    tasks.forEach((t, i) => {
      if (this.cubes.has(t.id)) return;
      const mesh = this.makeCube(t.team);
      mesh.position.copy(origin);
      this.scene.add(mesh);
      this.cubes.set(t.id, { mesh, owner: leadId });
      const spot = this.deskSpot(leadId, i);
      this.fx.fly(mesh, () => spot, { duration: 0.5 + i * 0.08, height: 0.8 });
    });
  }

  takeTaskCube(actor, taskId) {
    let cube = this.cubes.get(taskId);
    const task = this.tasks.get(taskId);
    if (!cube) {
      const mesh = this.makeCube(task?.team ?? actor.team);
      mesh.position.copy(this.actorHead(actor.id));
      this.scene.add(mesh);
      cube = { mesh, owner: actor.id };
      this.cubes.set(taskId, cube);
    }
    const prev = this.actors.get(cube.owner);
    if (prev !== actor && prev?.carrying === cube.mesh) prev.release();
    cube.owner = actor.id;
    this.carryInto(actor, cube.mesh);
  }

  deliverCube(taskId) {
    const cube = this.cubes.get(taskId);
    if (!cube) return;
    const actor = this.actors.get(cube.owner);
    if (actor?.carrying === cube.mesh) actor.release();
    this.cubes.delete(taskId);
    const card = this.cards.get(taskId);
    const mesh = cube.mesh;
    this.toScene(mesh);
    this.fx.fly(mesh, () => (card ? card.mesh.position : new THREE.Vector3(BOARD.x, 3, BOARD.z)), {
      duration: 1.3,
      height: 6,
      done: () => {
        this.scene.remove(mesh);
        if (card) {
          card.pulse = 1;
          this.fx.sparkle(card.mesh.position, '#3fbf6f');
        }
      },
    });
  }

  sinkCube(key) {
    const cube = this.cubes.get(key);
    if (!cube) return;
    this.cubes.delete(key);
    const actor = this.actors.get(cube.owner);
    if (actor?.carrying === cube.mesh) actor.release();
    const mesh = cube.mesh;
    this.toScene(mesh);
    mesh.material = new THREE.MeshStandardMaterial({ color: '#8a8a8a', roughness: 0.9 });
    mesh.children.forEach((c) => (c.visible = false));
    let t = 0;
    this.fx.add({
      update: (dt) => {
        t += dt;
        mesh.position.y -= dt * 0.4;
        mesh.scale.setScalar(Math.max(0.01, 1 - t / 1.5));
        return t < 1.5;
      },
      dispose: () => this.scene.remove(mesh),
    });
  }

  // ---------- server events ----------

  syncRun(run) {
    if (!this.hub) return;
    this.resetRun(run?.id ?? null);
    if (!run) return;
    const live = !['completed', 'completed_with_failures', 'failed', 'stopped'].includes(run.status);
    for (const w of run.workstreams ?? []) {
      this.workstreams.set(w.id, w);
      if (w.status === 'queued') this.makeCard(`ws:${w.id}`, w, true);
    }
    for (const t of run.tasks) {
      this.tasks.set(t.id, t);
      this.makeCard(t.id, t, false);
      if (live && LIVE_TASK.includes(t.status) && t.agentId && this.actors.has(t.agentId)) {
        const mesh = this.makeCube(t.team);
        mesh.position.copy(this.deskSpot(t.agentId));
        this.scene.add(mesh);
        this.cubes.set(t.id, { mesh, owner: t.agentId });
      }
    }
    this.layoutCards();
    for (const c of this.cards.values()) c.mesh.position.copy(c.target);
  }

  onRun(run) {
    if (run.id !== this.runId) this.syncRun(run);
  }

  onPlan({ runId, workstreams }) {
    if (runId !== this.runId) this.resetRun(runId);
    const ceo = this.actors.get(this.config.ceo.id);
    const from = ceo ? ceo.headWorld(new THREE.Vector3()) : new THREE.Vector3(0, 3, -8);
    workstreams.forEach((w, i) => {
      this.workstreams.set(w.id, w);
      const key = `ws:${w.id}`;
      if (this.cards.has(key)) return;
      const card = this.makeCard(key, w, true, from);
      card.mesh.scale.setScalar(0.01);
      card.flying = true;
      setTimeout(() => {
        this.layoutCards();
        card.mesh.scale.setScalar(1);
        this.fx.fly(card.mesh, () => card.target, { duration: 0.9, height: 3, spin: false, done: () => ((card.flying = false), card.mesh.rotation.set(0, 0, 0)) });
      }, 200 * i);
    });
    this.fx.ring(new THREE.Vector3(from.x, 0.3, from.z), this.config.ceo.color, { radius: 6, duration: 1.2 });
  }

  onWorkstream({ runId, ws }) {
    if (runId !== this.runId) return;
    this.workstreams.set(ws.id, ws);
    if ((ws.status === 'skipped' || ws.status === 'failed') && this.cards.has(`ws:${ws.id}`)) this.removeCard(`ws:${ws.id}`);
    if (ws.status === 'done') {
      const r = this.layout.rooms.find((x) => x.team === ws.team);
      if (r) this.fx.ring(new THREE.Vector3(r.x, 0.3, r.z), r.color, { radius: 9, duration: 1.4 });
    }
  }

  onSubtasks({ runId, wsId, leadId, tasks }) {
    if (runId !== this.runId) return;
    const lead = this.actors.get(leadId);
    const from = lead ? lead.headWorld(new THREE.Vector3()) : new THREE.Vector3(0, 3, 0);
    tasks.forEach((t, i) => {
      this.tasks.set(t.id, t);
      if (this.cards.has(t.id)) return;
      const card = this.makeCard(t.id, t, false, from);
      card.mesh.scale.setScalar(0.01);
      card.flying = true;
      setTimeout(() => {
        this.layoutCards();
        card.mesh.scale.setScalar(1);
        this.fx.fly(card.mesh, () => card.target, { duration: 1.2, height: 5, spin: false, done: () => ((card.flying = false), card.mesh.rotation.set(0, 0, 0)) });
      }, 160 * i);
    });
    const doSplit = () => this.splitWs(wsId, leadId, tasks);
    // if the lead is still walking back with the workstream, split when seated
    if (lead && (lead.queue.length || lead.carrying)) lead.do({ type: 'call', fn: doSplit });
    else doSplit();
  }

  onTask({ runId, task }) {
    if (runId !== this.runId) return;
    this.tasks.set(task.id, task);
    if (!this.cards.has(task.id)) this.makeCard(task.id, task, false);
    this.refreshCard(task);
    this.layoutCards();
    if (task.status === 'failed' || task.status === 'skipped') this.sinkCube(task.id);
  }

  onFile({ agentId, media }) {
    const actor = this.actors.get(agentId);
    if (!actor) return;
    const spot = this.deskSpot(agentId);
    this.fx.sparkle(spot, media ? '#ff8fb1' : '#7fe3ff');
    if (media === 'image') this.fx.ring(spot.clone().setY(1.2), '#ff8fb1', { radius: 1.6, duration: 0.8, flat: false });
  }

  onBrain({ op, agentId, count }) {
    this.brainShown = count;
    if (this.brainLabel) this.brainLabel.querySelector('span').textContent = t('world.brain', { n: count });
    if (this.hub && Math.abs((this.brainCount ?? 0) - count) >= 3) {
      brainParticles(this.hub.brain, count);
      this.brainCount = count;
    }
    if (this.hub) this.hub.brain.pulse = 1;
    if (!agentId || !this.actors.has(agentId)) return;
    const brainPos = () => new THREE.Vector3(BRAIN.x, BRAIN.y, BRAIN.z);
    if (op === 'remember') this.fx.beam(() => this.actorHead(agentId), brainPos, '#b18cff', { duration: 1.4, size: 0.1 });
    else this.fx.beam(brainPos, () => this.actorHead(agentId), '#5ad1ff', { duration: 1.4, size: 0.1 });
  }

  setBrainCount(count) {
    this.onBrain({ op: 'sync', agentId: null, count });
    if (this.hub) brainParticles(this.hub.brain, count);
    this.brainCount = count;
  }

  onMessage(m) {
    const color = KIND_COLOR[m.kind] ?? '#ffffff';
    const sky = (id) => {
      const h = this.actorHead(id);
      return new THREE.Vector3(h.x + 8, 18, h.z + 8);
    };
    if (m.from === 'user') {
      if (this.actors.has(m.to)) this.fx.beam(() => sky(m.to), () => this.actorHead(m.to), '#ffffff', { duration: 1.2, size: 0.18 });
      return;
    }
    if (m.to === 'user') {
      if (this.actors.has(m.from)) this.fx.beam(() => this.actorHead(m.from), () => sky(m.from), '#ffffff', { duration: 1.2, size: 0.16 });
      if (m.kind === 'ask_user') this.bubble(m.from, `🙋 ${esc(short(m.text, 60))}`, 6000, 'ask');
      return;
    }
    if (m.to === '*') {
      if (this.actors.has(m.from)) this.fx.ring(this.actors.get(m.from).position.clone().setY(0.4), color, { radius: 5, duration: 1.1 });
      return;
    }
    if (!this.actors.has(m.from) || !this.actors.has(m.to)) return;
    this.fx.beam(() => this.actorHead(m.from), () => this.actorHead(m.to), color, { duration: m.kind === 'brief' ? 1.4 : 1.1 });
    const say = { question: '❓', answer: '💬', guidance: '🧭', skills: '📚', prompt: '✍️', spawn: '✨', escalate: '⬆️', split: '🧩' }[m.kind];
    if (say) this.bubble(m.from, `${say} ${esc(short(m.text, 60))}`, 4200);
  }

  onSpawn(agent) {
    if (!this.hub) return;
    const actor = this.addActor(agent);
    if (!actor) return;
    actor.scale = 0.01;
    actor.scaleTarget = 1;
    const pos = actor.position.clone();
    this.fx.beam(() => new THREE.Vector3(pos.x, 22, pos.z), () => pos.clone().setY(1), actor.color, { duration: 0.6, size: 0.25 });
    this.fx.ring(pos.clone().setY(0.2), actor.color, { radius: 2.2, duration: 0.9 });
    this.fx.sparkle(pos.clone().setY(0.6), '#ffffff');
    const ghost = this.hub.anim.ghosts.get(agent.team)?.[agent.slot ?? 0];
    if (ghost) {
      ghost.userData.material.opacity = 0.85;
      ghost.userData.material.emissiveIntensity = 0.25;
    }
    this.bubble(agent.id, t('world.spawned'), 2400);
  }

  onDespawn({ id, team }) {
    const actor = this.actors.get(id);
    if (!actor) return;
    const ghost = this.hub.anim.ghosts.get(team)?.[this.subSlot(actor)];
    actor.scaleTarget = 0.01;
    this.fx.sparkle(actor.position.clone().setY(1), actor.color);
    this.fx.ring(actor.position.clone().setY(0.2), actor.color, { radius: 1.8, duration: 0.7 });
    for (const [key, c] of this.cubes) if (c.owner === id) this.sinkCube(key);
    setTimeout(() => {
      this.removeActor(id);
      if (ghost) {
        ghost.userData.material.opacity = 0.18;
        ghost.userData.material.emissiveIntensity = 0.4;
      }
    }, 800);
  }

  onRunDone({ status }) {
    if (status !== 'completed') return;
    for (const [id, a] of this.actors) {
      if (a.kind === 'ceo') this.fx.confetti(a.position.clone().setY(3));
      else setTimeout(() => a.play('celebrate', 2600), Math.random() * 700);
      this.bubble(id, '🎉', 2600);
    }
    this.fx.confetti(new THREE.Vector3(BRAIN.x, BRAIN.y + 1, BRAIN.z), { count: 220 });
  }

  applyState(a, initial = false) {
    let actor = this.actors.get(a.id);
    if (!actor && a.kind === 'sub' && this.hub) actor = this.addActor(a);
    const label = this.labels.get(a.id);
    if (!actor) return;
    // A10 (N12): the backend starts the work a fixed pickupMs after the assignment, but
    // the trip to the lead and back lasts as long as the path (and the frame rate) says.
    // While the actor is still on that trip, a working state waits for the arrival, as
    // a verdict waits for the reviewer: the latest one is applied there. Any other
    // state shows at once and drops the one put aside.
    if (!initial && AT_DESK.includes(a.state) && actor.queue.some((s) => s.arrival)) {
      actor.pending = a;
      return;
    }
    actor.pending = null;
    const prev = actor.state;
    actor.state = a.state;
    if (label) {
      label.state.className = `st-${a.state}`;
      label.tag.classList.toggle('busy', a.state !== 'idle');
    }

    if (initial) {
      if (a.state === 'reviewing' && a.target && this.actors.has(a.target)) {
        const p = this.besideSeat(this.actors.get(a.target));
        actor.teleport(p.x, p.z);
        actor.do({ type: 'faceTo', to: () => this.actors.get(a.target)?.position });
        actor.setBase('inspect');
      } else {
        actor.placeAtSeat();
        actor.setBase({ thinking: 'think', tool: 'work', paused: 'paused', asking: 'ask' }[a.state] ?? 'idle');
      }
      return;
    }

    if (actor.kind === 'ceo') {
      if (a.state === 'thinking') {
        actor.setBase('think');
        if (a.text) this.bubble(a.id, `💭 ${esc(short(a.text))}`, 3500);
      } else if (a.state === 'asking') {
        actor.setBase('ask');
        this.bubble(a.id, `🙋 ${esc(short(a.text, 60))}`, 6000, 'ask');
      } else if (a.state === 'celebrating') {
        actor.play('celebrate', 4000);
        actor.setBase('idle');
      } else actor.setBase(a.state === 'paused' ? 'paused' : 'idle');
      return;
    }

    switch (a.state) {
      case 'fetching': {
        const card = this.cards.get(`ws:${a.wsId}`);
        const x = card ? card.target.x : BOARD.x;
        actor.setBase('idle');
        actor
          .yieldTo()
          .walkTo(x, BOARD.z + 1.4)
          .do({ type: 'face', heading: Math.PI })
          .do({ type: 'call', fn: () => this.pickupWs(actor, a.wsId) })
          .do({ type: 'wait', ms: 450 });
        actor.goHome().do({ type: 'call', fn: () => this.dropCube(actor) });
        this.bubble(a.id, `📋 ${esc(short(a.text))}`, 3000);
        break;
      }
      case 'assigned': {
        const leadId = a.target;
        actor.setBase('idle');
        actor.yieldTo();
        if (leadId && this.actors.has(leadId) && leadId !== a.id) {
          const d = this.deskOf(leadId);
          actor
            .walkTo(d.x + 0.2, d.z + 1.05)
            .do({ type: 'faceTo', to: () => new THREE.Vector3(d.x, 0, d.z) })
            .do({ type: 'call', fn: () => this.takeTaskCube(actor, a.taskId) })
            .do({ type: 'wait', ms: 350 });
          actor.goHome().do({ type: 'call', fn: () => this.dropCube(actor) });
        } else {
          actor.goHome().do({ type: 'call', fn: () => this.takeTaskCube(actor, a.taskId) }, { type: 'wait', ms: 500 }, { type: 'call', fn: () => this.dropCube(actor) });
        }
        actor.do({ type: 'call', arrival: true, fn: () => this.arrived(actor) });
        this.bubble(a.id, `📋 ${esc(short(this.tasks.get(a.taskId)?.title ?? a.text))}`, 3000);
        break;
      }
      case 'thinking':
        actor.setBase('think');
        if (a.text && prev !== 'thinking') this.bubble(a.id, `${a.escalated ? '⬆️' : '💭'} ${esc(short(a.text))}`, 2600);
        break;
      case 'tool': {
        actor.setBase('work');
        const icon = TOOL_ICON[a.tool] ?? '🔧';
        const target = a.toolTarget ? ` <em>${esc(short(a.toolTarget, 28))}</em>` : '';
        this.bubble(a.id, `${icon}${target}${a.text ? `<small>${esc(short(a.text, 70))}</small>` : ''}`, 3400);
        break;
      }
      case 'asking':
        actor.setBase('ask');
        this.bubble(a.id, `🙋 ${esc(short(a.text, 60))}`, 8000, 'ask');
        break;
      case 'waiting':
        actor.setBase('idle');
        this.bubble(a.id, t('world.waiting'), 3000);
        break;
      case 'delivering': {
        const key = a.taskId ?? [...this.cubes.entries()].find(([, c]) => c.owner === a.id)?.[0];
        actor.do({ type: 'call', fn: () => this.deliverCube(key) });
        actor.play('celebrate', 1600);
        this.bubble(a.id, '✅ consegnato!', 2200, 'ok');
        break;
      }
      case 'paused':
        actor.setBase('paused');
        this.bubble(a.id, '💤', 2400);
        break;
      case 'reviewing': {
        const target = this.actors.get(a.target);
        if (!target) break;
        const p = this.besideSeat(target);
        actor.setBase('inspect');
        actor.yieldTo().walkTo(p.x, p.z).do({ type: 'faceTo', to: () => target.position });
        this.bubble(a.id, `🔍 ${esc(short(a.text))}`, 2600);
        break;
      }
      case 'verdict': {
        // shown once the reviewer has actually reached the desk
        const pass = a.verdict === 'pass';
        const text = a.text;
        const targetId = a.target;
        actor.do({
          type: 'call',
          fn: () => {
            const target = this.actors.get(targetId) ?? actor;
            this.bubble(a.id, pass ? `✔️ ${esc(short(text))}` : '✖️ da rivedere', 2600, pass ? 'ok' : 'bad');
            actor.play(pass ? 'wave' : 'shake', 1300);
            target.play(pass ? 'celebrate' : 'shake', 1300);
            this.fx.burst(target.headWorld(new THREE.Vector3()).setY(target.position.y + 1.2), pass ? '#3fbf6f' : '#ef4f5f', { count: pass ? 26 : 14 });
          },
        });
        break;
      }
      case 'idle':
      default:
        actor.setBase('idle');
        if (a.kind !== 'sub' && (!actor.atSeat() || actor.pose !== 'sit')) actor.goHome();
        for (const [key, c] of this.cubes) {
          if (c.owner !== a.id || key.startsWith('ws:')) continue;
          const task = this.tasks.get(key);
          if (task && !LIVE_TASK.includes(task.status) && task.status !== 'queued') this.sinkCube(key);
        }
    }
  }

  // The end of a pickup trip: the working state put aside meanwhile, if any (A10).
  arrived(actor) {
    const a = actor.pending;
    actor.pending = null;
    if (a && this.actors.get(a.id) === actor) this.applyState(a);
  }

  // Free agents stretch their legs: a walk to the Brain, a peek at the board.
  wander(dt) {
    this.wanderClock = (this.wanderClock ?? 0) + dt;
    if (this.wanderClock < 3.5) return;
    this.wanderClock = 0;
    const actors = [...this.actors.values()].filter((a) => a.kind !== 'ceo' && a.kind !== 'sub');
    if (actors.filter((a) => a.idleTrip).length >= 3 || Math.random() > 0.5) return;
    const free = actors.filter((a) => a.state === 'idle' && !a.queue.length && a.atSeat() && !a.idleTrip);
    if (!free.length) return;
    const a = free[Math.floor(Math.random() * free.length)];
    const s = SPOTS[Math.floor(Math.random() * SPOTS.length)];
    a.idleTrip = true;
    a.walkTo(s.x, s.z)
      .do({ type: 'face', heading: s.z < -12 ? Math.PI : Math.random() * Math.PI * 2 })
      .do({ type: 'call', fn: () => this.bubble(a.id, s.say, 2200) })
      .do({ type: 'wait', ms: 2200 + Math.random() * 2500 });
    a.goHome().do({ type: 'call', fn: () => (a.idleTrip = false) });
  }

  // Little data packets run along the roads of busy teams.
  flow(dt) {
    if (!this.hub) return;
    this.flowClock = (this.flowClock ?? 0) + dt;
    if (this.flowClock > 0.35) {
      this.flowClock = 0;
      const busy = new Set([...this.actors.values()].filter((a) => a.state && a.state !== 'idle').map((a) => a.team));
      for (const rd of this.hub.anim.roads) {
        if (!busy.has(rd.team) || Math.random() > 0.55 || this.flows.length > 80) continue;
        const out = Math.random() < 0.5;
        const mesh = new THREE.Mesh(this.flowGeo ??= new THREE.SphereGeometry(0.11, 8, 6), new THREE.MeshBasicMaterial({ color: this.teamColor(rd.team), transparent: true, opacity: 0.95 }));
        this.scene.add(mesh);
        const side = (Math.random() - 0.5) * 1.2;
        this.flows.push({ mesh, from: out ? rd.from : rd.to, to: out ? rd.to : rd.from, t: 0, speed: 0.35 + Math.random() * 0.25, side });
      }
    }
    this.flows = this.flows.filter((f) => {
      f.t += dt * f.speed;
      const dx = f.to.x - f.from.x;
      const dz = f.to.z - f.from.z;
      const len = Math.hypot(dx, dz) || 1;
      f.mesh.position.set(f.from.x + dx * f.t + (-dz / len) * f.side * 0.5, 0.28, f.from.z + dz * f.t + (dx / len) * f.side * 0.5);
      f.mesh.material.opacity = Math.min(1, (1 - f.t) * 3);
      if (f.t >= 1) {
        this.scene.remove(f.mesh);
        f.mesh.material.dispose();
        return false;
      }
      return true;
    });
  }

  // ---------- loop ----------

  frame() {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    const t = this.clock.elapsedTime;
    this.frameNo++;
    this.controls.update();
    if (this.hub) {
      this.wander(dt);
      this.flow(dt);
    }
    for (const a of this.actors.values()) a.update(dt, t);
    this.fx.update(dt);

    for (const card of this.cards.values()) {
      if (!card.flying) card.mesh.position.lerp(card.target, Math.min(1, dt * 6));
      if (card.pulse > 0) {
        card.pulse = Math.max(0, card.pulse - dt * 1.8);
        card.mesh.scale.setScalar(1 + Math.sin(card.pulse * Math.PI) * 0.2);
      }
    }

    if (this.hub) {
      const b = this.hub.brain;
      b.pulse = Math.max(0, (b.pulse ?? 0) - dt * 1.5);
      b.core.rotation.y += dt * 0.25;
      b.core.position.y = BRAIN.y + Math.sin(t * 1.1) * 0.12;
      b.core.scale.setScalar(1 + Math.sin(t * 2) * 0.02 + b.pulse * 0.12);
      b.core.material.emissiveIntensity = 0.8 + b.pulse * 1.4 + Math.sin(t * 2) * 0.1;
      b.shell.rotation.y -= dt * 0.15;
      b.shell.rotation.x += dt * 0.05;
      b.orbit.rotation.z += dt * 0.4;
      b.rings.forEach((r, i) => (r.rotation.z += dt * (i % 2 ? -0.2 : 0.15)));
      b.pillar.material.opacity = 0.12 + b.pulse * 0.25 + Math.sin(t * 3) * 0.03;
      if (b.particles) {
        const pos = b.particles.geometry.attributes.position;
        const s = b.particles.userData.seeds;
        for (let i = 0; i < pos.count; i++) {
          const r = s[i * 3];
          const a = s[i * 3 + 1] + t * (0.6 / r);
          pos.setXYZ(i, Math.cos(a) * r, s[i * 3 + 2] + Math.sin(t + i) * 0.05, Math.sin(a) * r);
        }
        pos.needsUpdate = true;
      }

      let working = 0;
      for (const [id, st] of this.hub.stations) {
        const actor = this.actors.get(id);
        const busy = actor && (actor.baseAnim === 'work' || actor.baseAnim === 'think') && actor.atSeat();
        if (busy) working++;
        st.screen.emissiveIntensity += ((busy ? 1.1 + Math.sin(t * 9 + id.length) * 0.15 : 0.25) - st.screen.emissiveIntensity) * Math.min(1, dt * 5);
      }
      for (const p of this.hub.anim.props) {
        if (p.userData.spin) p.userData.spin.rotation.y += dt * 0.6;
        if (p.userData.float) p.userData.float.position.y = 2.9 + Math.sin(t * 2) * 0.12;
        if (p.userData.leds) p.userData.leds.forEach((m) => Math.random() < dt * (2 + working) && (m.emissiveIntensity = Math.random() < 0.5 ? 0.15 : 1.8));
      }
      for (const p of this.hub.anim.plants) p.rotation.z = Math.sin(t * 0.8 + p.userData.sway) * 0.025;
    }

    this.renderer.render(this.scene, this.camera);
    this.updateLabels();
    if (this.minimap && this.frameNo % 4 === 0) this.drawMinimap();
  }

  updateLabels() {
    // the canvas fills #stage: resize() keeps its size, no layout read per frame
    const { width: w, height: h } = this;
    const now = performance.now();
    // the zoom of the old fixed framing that would show the office this size (S2.6):
    // labels keep their size next to the characters whatever the panels leave free
    const zoom = REF_UNITS_PER_PX / this.screenScale();
    const scale = Math.min(1.1, Math.max(0.62, 0.5 + zoom * 0.28));
    this.labelsEl.style.setProperty('--label-scale', String(scale));
    this.labelsEl.classList.toggle('far', zoom < FAR_ZOOM);
    const project = (v) => {
      v.project(this.camera);
      return [(v.x * 0.5 + 0.5) * w, (-v.y * 0.5 + 0.5) * h];
    };
    for (const [id, l] of this.labels) {
      const a = this.actors.get(id);
      if (!a) continue;
      const p = a.headWorld(this.tmp);
      p.y += 0.25;
      const [x, y] = project(p);
      l.tag.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%) scale(var(--label-scale))`;
      l.bubble.style.transform = `translate(${x}px, ${y - 28 * scale}px) translate(-50%, -100%) scale(var(--label-scale))`;
      if (l.hideAt && now > l.hideAt) {
        l.bubble.classList.remove('show');
        l.hideAt = 0;
      }
    }
    for (const r of this.roomLabels) {
      const [x, y] = project(this.tmp.copy(r.pos));
      // centred on the anchor, standing on it; app.css puts the transform origin there
      r.el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -100%) scale(var(--label-scale))`;
    }
    if (this.brainLabel) {
      const [x, y] = project(this.tmp.set(BRAIN.x + 2.3, BRAIN.y - 0.4, BRAIN.z));
      this.brainLabel.style.transform = `translate(${x}px, ${y}px) translate(0, -50%) scale(var(--label-scale))`;
    }
  }

  setRoomStats(stats) {
    for (const r of this.roomLabels) {
      const s = stats[r.team] ?? { agents: 0, busy: 0 };
      r.el.querySelector('span').textContent = t('teams.members', { n: s.agents, busy: s.busy });
      r.el.classList.toggle('active', s.busy > 0);
    }
  }

  drawMinimap() {
    const c = this.minimap;
    const g = c.getContext('2d');
    const W = c.width;
    const H = c.height;
    const sx = (x) => ((x - WORLD.minX) / (WORLD.maxX - WORLD.minX)) * W;
    const sz = (z) => ((z - WORLD.minZ) / (WORLD.maxZ - WORLD.minZ)) * H;
    g.clearRect(0, 0, W, H);
    g.fillStyle = this.night ? 'rgba(40,36,48,0.92)' : 'rgba(236,220,196,0.95)';
    g.fillRect(0, 0, W, H);
    for (const r of this.layout?.rooms ?? []) {
      g.fillStyle = r.color;
      g.globalAlpha = 0.75;
      g.fillRect(sx(r.x - r.w / 2), sz(r.z - r.d / 2), (r.w / (WORLD.maxX - WORLD.minX)) * W, (r.d / (WORLD.maxZ - WORLD.minZ)) * H);
    }
    g.globalAlpha = 1;
    g.strokeStyle = '#e7a83b';
    g.beginPath();
    g.arc(sx(BRAIN.x), sz(BRAIN.z), (BRAIN.r / (WORLD.maxX - WORLD.minX)) * W, 0, Math.PI * 2);
    g.stroke();
    g.fillStyle = this.night ? '#e9eefb' : '#2b3240';
    g.fillRect(sx(BOARD.x - BOARD.width / 2), sz(BOARD.z) - 1, (BOARD.width / (WORLD.maxX - WORLD.minX)) * W, 2);
    for (const a of this.actors.values()) {
      g.fillStyle = a.color;
      g.beginPath();
      g.arc(sx(a.position.x), sz(a.position.z), a.state && a.state !== 'idle' ? 3 : 2, 0, Math.PI * 2);
      g.fill();
    }
    const corners = this.footprint().map((p) => [sx(p.x), sz(p.z)]);
    g.strokeStyle = this.night ? 'rgba(255,255,255,0.8)' : 'rgba(40,40,40,0.7)';
    g.beginPath();
    corners.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
    g.closePath();
    g.stroke();
  }

  // The floor the user can see (S2.7): the corners of the area the panels leave free,
  // cast from the canvas down to y 0. The rest of the canvas is under the UI.
  footprint() {
    const s = safeRect(this.width, this.height, this.insets);
    const dir = this.camera.getWorldDirection(new THREE.Vector3());
    return [[s.x0, s.y0], [s.x1, s.y0], [s.x1, s.y1], [s.x0, s.y1]].map(([x, y]) => {
      const v = new THREE.Vector3((x / this.width) * 2 - 1, 1 - (y / this.height) * 2, 0).unproject(this.camera);
      return v.addScaledVector(dir, -v.y / dir.y);
    });
  }
}
