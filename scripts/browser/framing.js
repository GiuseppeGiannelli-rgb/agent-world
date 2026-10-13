// A1 against the real World, A6, and the T5 checks that must not regress: the whole
// envelope in the free area, a panel re-framing the office in 0.35 s with no jump at
// the click, a resize that never leaves the projection stretched, every agent clickable
// through the lens shift.
window.__checks.framing = () =>
  window.__t.session(async (t) => {
    const { w, c, $ } = t;
    const { ENVELOPE } = await import('/js/world/office.js');
    const out = {};
    const outside = () => {
      const s = t.F.safeRect(w.width, w.height, w.insets);
      return ENVELOPE.map(t.toScreen).filter(([x, y]) => x < s.x0 - 1 || x > s.x1 + 1 || y < s.y0 - 1 || y > s.y1 + 1).length;
    };
    const onFit = () => {
      const lens = t.centreLens();
      return Math.abs(w.view.lensX - lens.lensX) < 1e-9 && Math.abs(w.view.lensY - lens.lensY) < 1e-9 && w.camera.zoom === 1;
    };

    for (const [lay, [left, right]] of Object.entries(t.LAYOUTS)) {
      t.panels(left, right);
      t.home();
      t.result(out, `A1 ${lay}: envelope in the free area`, outside() === 0, { pointsOutside: outside() });
    }

    // A6: each panel closes and opens again; the picture must not jump at the click
    for (const side of ['right', 'left']) {
      t.panels(true, true);
      t.home();
      for (const step of ['closes', 'opens']) {
        const before = t.picture();
        $(`#btn-${side}`).click();
        t.sync();
        const jump = t.moved(before, t.picture());
        let frames = 0;
        while (w.fx.active(w.camera) && frames < 120) {
          t.pump(1 / 60);
          frames++;
        }
        const seconds = frames / 60;
        t.result(out, `A6 ${side} panel ${step}`, jump === 0 && Math.abs(seconds - 0.35) <= 1 / 60 && onFit() && outside() === 0, { jumpAtClickPx: jump, seconds: +seconds.toFixed(3), endsOnFit: onFit(), pointsOutside: outside() });
      }
    }

    // a resize in automatic mode: buffer and projection follow at once, fitted again
    {
      t.panels(true, true);
      t.home();
      const css = c.parentElement.style.cssText;
      c.parentElement.style.cssText += ';right:160px;bottom:90px';
      t.sync();
      const aspect = (w.camera.right - w.camera.left) / (w.camera.top - w.camera.bottom);
      const ratio = w.renderer.getPixelRatio();
      const buffer = c.width === Math.floor(w.width * ratio) && c.height === Math.floor(w.height * ratio);
      t.result(out, 'resize: no stretched frame', Math.abs(aspect - w.width / w.height) < 1e-9 && buffer && onFit() && outside() === 0, { size: [w.width, w.height], aspectMatches: Math.abs(aspect - w.width / w.height) < 1e-9, bufferMatches: buffer, endsOnFit: onFit() });
      c.parentElement.style.cssText = css;
      t.sync();
    }

    // every agent picked by a click through the canvas listeners. What a click there must
    // pick is the first agent on a ray cast straight from the projected point, without
    // client coordinates: an idle agent strolling in front of another one (once in six
    // runs) is the right answer, not a miss.
    {
      t.panels(true, true);
      t.home();
      const onPick = w.onPick;
      const picked = [];
      w.onPick = (id) => picked.push(id);
      const owner = (o) => {
        while (o && !o.userData.agentId) o = o.parent;
        return o?.userData.agentId;
      };
      const roots = [...w.actors.values()].map((a) => a.root);
      let hits = 0;
      let covered = 0;
      const missed = [];
      try {
        for (const [id, a] of w.actors) {
          const point = a.position.clone().setY(0.7);
          const [x, y] = t.toScreen(point);
          const ndc = point.clone().project(w.camera);
          w.raycaster.setFromCamera({ x: ndc.x, y: ndc.y }, w.camera);
          const front = w.raycaster.intersectObjects(roots, true).map((h) => owner(h.object)).find(Boolean);
          if (front !== id) covered++;
          const r = t.rect();
          const p = { clientX: r.left + x, clientY: r.top + y };
          t.pointer('pointerdown', p);
          t.pointer('pointerup', p);
          if (picked.at(-1) === front) hits++;
          else missed.push({ id, front, got: picked.at(-1) ?? null });
        }
      } finally {
        w.onPick = onPick;
      }
      t.result(out, 'clicks on agents through the lens shift', hits === w.actors.size && covered <= 2 && w.autoFrame === true, { picked: `${hits}/${w.actors.size}`, coveredByAnother: covered, autoFrame: w.autoFrame, missed });
    }
    return out;
  });
