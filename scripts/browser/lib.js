// Page-side helpers for the browser checks of specs 01 and 02. scripts/browser-test.js
// injects this file and then the checks into a running Agent World; in a browser
// console, paste this file first. Everything drives window.agentWorld: a fixed 60 fps
// clock, synthetic input, the real panel buttons, insets measured the way main.js does;
// for spec 02 also the fixed UI as it should be laid out, and real frames.
window.__checks = window.__checks ?? {};
window.__t = (() => {
  const w = window.agentWorld;
  const c = w.canvas;
  const $ = (s) => document.querySelector(s);
  const narrow = matchMedia('(max-width: 900px)');
  const t = { w, c, $ };

  // How far the UI reaches into the canvas from each edge (main.js, measureInsets).
  t.measure = () => {
    const cr = c.getBoundingClientRect();
    const box = (el, counts = true) => {
      const r = el.getBoundingClientRect();
      return counts && r.width > 0 && r.height > 0 ? r : null;
    };
    const top = box($('.topbar'));
    const left = box($('#left'), !narrow.matches);
    const right = box($('#right'), !narrow.matches);
    const roster = box($('#roster'));
    return { top: top ? top.bottom - cr.top : 0, right: right ? cr.right - right.left : 0, bottom: roster ? cr.bottom - roster.top : 0, left: left ? left.right - cr.left : 0 };
  };
  // Size and insets applied at once, as the ResizeObservers would: a hidden tab gets
  // none of their callbacks, and the clock below runs ahead of the real one anyway.
  t.sync = () => {
    if (w.width !== c.parentElement.clientWidth || w.height !== c.parentElement.clientHeight) w.resize();
    w.setInsets(t.measure());
  };
  t.isOpen = (id) => !$(id).classList.contains('closed');
  t.panels = (left, right) => {
    if (t.isOpen('#left') !== left) $('#btn-left').click();
    if (t.isOpen('#right') !== right) $('#btn-right').click();
    t.sync();
  };
  t.LAYOUTS = { LR: [true, true], '-R': [false, true], '--': [false, false] };

  // The world advanced by hand at 60 fps, independent of how often the browser paints.
  t.pump = (seconds) => {
    w.clock.getDelta = () => 1 / 60;
    try {
      for (let i = 0; i < Math.max(1, Math.round(seconds * 60)); i++) w.frame();
    } finally {
      delete w.clock.getDelta;
    }
  };
  t.home = () => {
    w.resetView({ animate: false });
    t.pump(0.3);
  };

  // Input, in CSS px of the page.
  t.rect = () => c.getBoundingClientRect();
  t.at = (fx, fy) => {
    const r = t.rect();
    return { clientX: r.left + r.width * fx, clientY: r.top + r.height * fy };
  };
  t.pointer = (type, p, o = {}) =>
    c.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, composed: true, pointerId: 1, pointerType: 'mouse', isPrimary: true, button: 0, buttons: type === 'pointerup' || type === 'pointercancel' ? 0 : 1, ...p, ...o }));
  t.drag = (from, to, steps = 6, o = {}) => {
    t.pointer('pointerdown', from, o);
    for (let i = 1; i <= steps; i++) {
      t.pointer('pointermove', { clientX: from.clientX + ((to.clientX - from.clientX) * i) / steps, clientY: from.clientY + ((to.clientY - from.clientY) * i) / steps }, o);
      t.pump(1 / 60);
    }
    t.pointer('pointerup', to, o);
  };
  t.wheel = (p, deltaY, n = 1, o = {}) => {
    for (let i = 0; i < n; i++) {
      c.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY, ...p, ...o }));
      t.pump(1 / 60);
    }
  };

  // Measures, in CSS px of the canvas.
  t.toScreen = (p) => {
    w.camera.updateMatrixWorld();
    const v = p.clone().project(w.camera);
    return [(v.x * 0.5 + 0.5) * w.width, (-v.y * 0.5 + 0.5) * w.height];
  };
  // The floor point (y 0) under a point of the page.
  t.floorAt = (p) => {
    const r = t.rect();
    w.camera.updateMatrixWorld();
    w.raycaster.setFromCamera({ x: ((p.clientX - r.left) / r.width) * 2 - 1, y: -((p.clientY - r.top) / r.height) * 2 + 1 }, w.camera);
    const { origin, direction } = w.raycaster.ray;
    return origin.clone().addScaledVector(direction, -origin.y / direction.y);
  };
  t.screenScale = () => w.view.unitsPerPx / w.camera.zoom; // world units per px on screen
  t.centreLens = () => {
    const s = t.F.safeRect(w.width, w.height, w.insets);
    return { lensX: s.cx - w.width / 2, lensY: s.cy - w.height / 2 };
  };
  // The picture as a few points on screen: the floor corners and the camera target.
  t.picture = () => [[-24, 0, -17], [24, 0, -17], [-24, 0, 17], [24, 0, 17]].map((p) => t.toScreen(new t.V3(...p))).concat([t.toScreen(w.controls.target)]);
  t.moved = (a, b) => +Math.max(...a.map(([x, y], i) => Math.hypot(x - b[i][0], y - b[i][1]))).toFixed(2);
  t.V3 = w.controls.target.constructor;

  // Runs fn with the world on the clock above, drawing suspended and pointer capture
  // stubbed, then puts everything back. Drawing is suspended because a hidden tab is
  // slow; the matrices the controls, picking and projections read are still updated as
  // a real frame leaves them. Capture is stubbed because the browser refuses it for
  // synthetic pointers (OrbitControls asks for it on pointerdown).
  t.session = async (fn) => {
    t.F = await import('/js/world/framing.js');
    const render = w.renderer.render;
    const stageCss = c.parentElement.style.cssText;
    const open = [t.isOpen('#left'), t.isOpen('#right')];
    w.renderer.setAnimationLoop(null);
    w.renderer.render = (scene, camera) => {
      scene.updateMatrixWorld();
      if (camera.parent === null) camera.updateMatrixWorld();
    };
    w.updateLabels = () => {};
    c.setPointerCapture = () => {};
    c.releasePointerCapture = () => {};
    try {
      t.sync();
      return await fn(t);
    } finally {
      delete w.clock.getDelta;
      delete w.updateLabels;
      delete c.setPointerCapture;
      delete c.releasePointerCapture;
      w.renderer.render = render;
      w.labelsEl.classList.remove('far');
      c.parentElement.style.cssText = stageCss;
      if (t.isOpen('#left') !== open[0]) $('#btn-left').click();
      if (t.isOpen('#right') !== open[1]) $('#btn-right').click();
      t.sync();
      w.resetView({ animate: false });
      w.renderer.setAnimationLoop(() => w.frame());
    }
  };
  // One result per check: { ok, ...measures }.
  t.result = (out, name, ok, data = {}) => (out[name] = { ok: Boolean(ok), ...data });

  // ---------- the fixed UI (spec 02) ----------

  const medium = matchMedia('(max-width: 1250px)');
  t.narrow = () => narrow.matches;
  t.FIXED = { topbar: '.topbar', left: '#left', right: '#right', roster: '#roster', minimap: '#minimap', inspector: '#inspector' };
  // The fixed elements on screen now: a rectangle for each one shown, null for the rest.
  t.fixed = () =>
    Object.fromEntries(
      Object.entries(t.FIXED).map(([k, s]) => {
        const r = $(s).getBoundingClientRect();
        return [k, r.width > 0 && r.height > 0 ? { x0: r.left, y0: r.top, x1: r.right, y1: r.bottom } : null];
      }),
    );
  t.box = (el) => {
    const r = el.getBoundingClientRect();
    return { x0: r.left, y0: r.top, x1: r.right, y1: r.bottom };
  };
  t.area = (a) => (a ? Math.max(0, a.x1 - a.x0) * Math.max(0, a.y1 - a.y0) : 0);
  t.overlap = (a, b) => (a && b ? Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0)) : 0);
  t.inside = (a, b, tol = 0.5) => a.x0 >= b.x0 - tol && a.y0 >= b.y0 - tol && a.x1 <= b.x1 + tol && a.y1 <= b.y1 + tol;
  // Where spec 02 (§3.1) puts the column of the roster and the inspector, and the
  // minimap: x ranges from the window width and the panels alone, null for what is
  // hidden. Never from where the other elements are, so a minimap out of place does
  // not move what the roster is expected to do.
  t.expected = () => {
    const W = innerWidth;
    if (narrow.matches) return { roster: [8, W - 8], inspector: [8, W - 8], minimap: null };
    const [lw, rw] = medium.matches ? [300, 360] : [330, 400];
    const left = t.isOpen('#left');
    const right = t.isOpen('#right');
    const minimap = medium.matches ? null : right ? [W - rw - 24 - 204, W - rw - 24] : [W - 216, W - 12];
    const x0 = left ? 12 + lw + 12 : 12;
    const x1 = minimap ? minimap[0] - 12 : right ? W - 12 - rw - 12 : W - 12;
    return { roster: [x0, x1], inspector: [x0, x0 + Math.min(340, x1 - x0)], minimap };
  };
  // Real frames: the overlaps phase needs the ResizeObservers and the renders of main.js.
  t.frames = async (n = 1) => {
    for (let i = 0; i < n; i++) await new Promise((ok) => requestAnimationFrame(ok));
  };
  t.until = async (fn, frames = 90) => {
    for (let i = 0; i < frames && !fn(); i++) await t.frames(1);
    return fn();
  };
  t.inspectorOpen = () => !$('#inspector').classList.contains('hidden');
  // The tallest and widest inspector a user gets: 6 events in the timeline (main.js shows
  // no more), a chat long enough to reach the inspector's max-height, and the longest
  // strings with no place to break a line (no space, no hyphen): a file path cut at 36
  // characters as renderInspector cuts it, a model id, a link pasted in the chat. A render of the
  // inspector puts its own content back, so callers fill it right before they measure.
  t.tallInspector = () => {
    const el = $('#inspector');
    if (!t.inspectorOpen()) return;
    const path = 'site/assets/img/menu_pizze_fritte_napoletane.webp'.slice(0, 36);
    el.querySelector('.now').innerHTML = `<b>Al lavoro</b> · Scrive un file
      <div>Task <b>ws2.t3</b>: Pagina del menu con prezzi, allergeni e foto dei piatti</div>
      <div class="muted" style="margin-top:4px">Sto scrivendo la sezione delle pizze fritte</div>
      <div class="muted" style="margin-top:4px;font-family:var(--mono);font-size:11px">openrouter/anthropic/claude_sonnet_4.5_20250929</div>`;
    const timeline = el.querySelector('.timeline') ?? el.querySelector('.col-title').insertAdjacentElement('beforebegin', document.createElement('div'));
    timeline.className = 'timeline';
    timeline.innerHTML = `<div class="ev"><span class="t">t3</span><div>Scrive <code>${path}</code></div></div>`.repeat(6);
    const said = (i) => (i === 6 ? 'Guarda qui: https://www.pizzeriaesempio.it/menu/pizzefritte/napoletane_tradizionali.html' : i % 2 ? 'Ok, aggiungo la sezione e poi ricontrollo i prezzi con il lead.' : 'Aggiungi anche le pizze fritte, per favore.');
    el.querySelector('#chat-log').innerHTML = Array.from({ length: 8 }, (_, i) => `<div class="b ${i % 2 ? 'them' : 'me'}">${said(i)}</div>`).join('');
  };
  return t;
})();
