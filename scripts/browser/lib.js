// Page-side helpers for the browser checks of spec 01. scripts/browser-test.js injects
// this file and then the checks into a running Agent World; in a browser console,
// paste this file first. Everything drives window.agentWorld: a fixed 60 fps clock,
// synthetic input, the real panel buttons, insets measured the way main.js does.
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
  return t;
})();
