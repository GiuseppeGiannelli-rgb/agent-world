// A8 and S2.5-S2.7 (T7): close-ups at the size on screen of the old fixed framing,
// zoom limits that follow the projection, labels sized by the effective zoom, the
// minimap footprint on the free area. Run it at each viewport to check.
// mutate: true puts the trap back on purpose (the zoom limit set once per move, for
// where the move ends): "⌂ ... LR → --" and "drag that interrupts ⌂" must then fail.
window.__checks.absoluteScale = ({ mutate = false } = {}) =>
  window.__t.session(async (t) => {
    const { w, c, $ } = t;
    const REF = t.F.REF_UNITS_PER_PX;
    const s = t.screenScale;
    const ids = [...w.actors.keys()];
    const out = {};
    // every controls.update() that changes the zoom while a code move runs and no
    // gesture goes on is the clamp cutting the move short
    const update = w.controls.update;
    let clips = [];
    w.controls.update = function (...args) {
      const before = w.camera.zoom;
      const r = update.apply(this, args);
      if (w.fx.active(w.camera) && w.controls.state === -1 && Math.abs(w.camera.zoom - before) > 1e-9) clips.push([+before.toFixed(3), +w.camera.zoom.toFixed(3)]);
      return r;
    };
    if (mutate) {
      w.applyView = function () {
        t.F.applyFrustum(this.camera, this.width, this.height, this.view.unitsPerPx, this.view.lensX, this.view.lensY);
      };
      const move = Object.getPrototypeOf(w).moveCamera;
      w.moveCamera = function (o = {}) {
        move.call(this, o);
        this.controls.maxZoom = t.F.maxZoomFor((this.fx.active(this.camera)?.goal?.view ?? this.view).unitsPerPx);
      };
    }
    try {
      for (const [lay, [left, right]] of Object.entries(t.LAYOUTS)) {
        t.panels(left, right);
        t.home();
        const fitScale = s();
        // A8: the agent at the old size, the point focused at the centre of the free area
        const a = w.actors.get(ids[6]);
        const p0 = new t.V3(a.position.x, 0, a.position.z); // idle agents wander off
        w.focus(ids[6]);
        t.pump(1.0);
        const [x, y] = t.toScreen(p0);
        const lens = t.centreLens();
        const off = Math.hypot(x - (w.width / 2 + lens.lensX), y - (w.height / 2 + lens.lensY));
        t.result(out, `A8 ${lay}: agent focus`, Math.abs(s() / (REF / 2.2) - 1) < 0.05 && off < 1, { ratio: +(s() / (REF / 2.2)).toFixed(6), centreOffPx: +off.toFixed(2), zoom: +w.camera.zoom.toFixed(3) });
        t.home();
        w.focusRoom(w.layout.rooms[2].team);
        t.pump(1.0);
        t.result(out, `${lay}: room focus`, Math.abs(s() / (REF / 2) - 1) < 1e-6, { ratio: +(s() / (REF / 2)).toFixed(6) });
        // the closest and the farthest the wheel goes; a focus from closer stays closer
        t.home();
        t.wheel(t.at(0.5, 0.5), -120, 40);
        t.pump(0.5);
        const closest = s();
        w.focus(ids[9]);
        t.pump(1.0);
        const kept = s();
        t.home();
        t.wheel(t.at(0.5, 0.5), 120, 40);
        t.pump(0.5);
        const farthest = s();
        t.result(out, `${lay}: zoom limits`, Math.abs(closest / (REF / 4) - 1) < 1e-6 && Math.abs(kept / closest - 1) < 1e-6 && Math.abs(farthest / (2 * fitScale) - 1) < 1e-6, {
          closestVsOld: +(closest / (REF / 4)).toFixed(6),
          focusKeepsCloser: +(kept / closest).toFixed(6),
          farthestVsTwiceFit: +(farthest / (2 * fitScale)).toFixed(6),
        });
        // S2.7: the footprint corners fall back on the free area's corners on screen
        t.home();
        w.focus(ids[3]);
        t.pump(1.0);
        const safe = t.F.safeRect(w.width, w.height, w.insets);
        const want = [[safe.x0, safe.y0], [safe.x1, safe.y0], [safe.x1, safe.y1], [safe.x0, safe.y1]];
        const err = Math.max(...w.footprint().map(t.toScreen).map(([px, py], i) => Math.hypot(px - want[i][0], py - want[i][1])));
        t.result(out, `${lay}: minimap footprint`, err < 0.5, { maxErrPx: +err.toFixed(4) });
      }

      // moves that change the scale: no clamp, and the size on screen changes one way
      const glide = (name, setup, move) => {
        setup();
        clips = [];
        const trail = [s()];
        move();
        for (let i = 0; i < 60 && w.fx.active(w.camera); i++) {
          t.pump(1 / 60);
          trail.push(s());
        }
        t.pump(0.2);
        trail.push(s());
        const d = trail.slice(1).map((v, i) => v - trail[i]);
        const monotonic = d.every((v) => v >= -1e-12) || d.every((v) => v <= 1e-12);
        const worst = Math.max(...trail.slice(1).map((v, i) => Math.abs(Math.log(v / trail[i]))));
        t.result(out, name, !clips.length && monotonic, { clipCount: clips.length, firstClips: clips.slice(0, 3), monotonic, frames: trail.length, worstStepPct: +(100 * (Math.exp(worst) - 1)).toFixed(2) });
      };
      const closestIn = (left, right) => {
        t.panels(left, right);
        t.home();
        t.wheel(t.at(0.5, 0.5), -120, 40); // manual, at the closest close-up
        t.pump(0.5);
      };
      glide('⌂ from the closest view, LR → --', () => {
        closestIn(true, true);
        t.panels(false, false); // manual: nothing moves
        t.pump(0.3);
      }, () => $('#btn-home').click());
      glide('⌂ from the closest view, -- → LR', () => {
        closestIn(false, false);
        t.panels(true, true);
        t.pump(0.3);
      }, () => $('#btn-home').click());
      glide('focus started during a re-frame', () => {
        t.panels(false, false);
        t.home();
        t.panels(true, true); // 0.35 s re-frame towards a larger scale
        t.pump(0.1);
      }, () => w.focus(ids[11]));
      out['focus started during a re-frame'].endsAtOldSize = +(s() / (REF / 2.2)).toFixed(6);
      out['focus started during a re-frame'].ok &&= Math.abs(s() / (REF / 2.2) - 1) < 1e-6;
      glide('room focus from the closest view, LR', () => closestIn(true, true), () => w.focusRoom(w.layout.rooms[0].team));

      // review R5: a move changes the size on screen by equal ratios, at the pace of its
      // ease like the target (a linear zoom grew 18% in the first frame of this focus)
      {
        t.panels(true, true);
        t.home();
        const target0 = w.controls.target.clone();
        const s0 = s();
        w.focus(ids[6]);
        const { goal } = w.fx.active(w.camera);
        t.pump(1 / 60);
        const zoomShare = Math.log(s0 / s()) / Math.log(s0 / (goal.view.unitsPerPx / goal.zoom));
        const panShare = w.controls.target.distanceTo(target0) / goal.target.distanceTo(target0);
        t.result(out, 'focus from the full view: size and place at the same pace', Math.abs(zoomShare - panShare) < 0.002, {
          zoomSharePct: +(100 * zoomShare).toFixed(2),
          panSharePct: +(100 * panShare).toFixed(2),
          firstFrameGrowthPct: +(100 * (s0 / s() - 1)).toFixed(2),
        });
      }

      // While a move runs its next step hides the clamp; it shows once the user
      // interrupts the move. A pan must not change the size on screen.
      {
        closestIn(true, true);
        t.panels(false, false);
        t.pump(0.3);
        $('#btn-home').click();
        // early: the zoom is still above the limit of the fit it heads to (eased in ratio,
        // it drops below it within two frames at 1920x1080)
        t.pump(1 / 60);
        const aboveEndLimit = w.camera.zoom > t.F.maxZoomFor(w.fx.active(w.camera).goal.view.unitsPerPx);
        const before = s();
        const p = t.at(0.45, 0.5);
        t.pointer('pointerdown', p);
        for (let i = 1; i <= 6; i++) {
          t.pointer('pointermove', { clientX: p.clientX + 8 * i, clientY: p.clientY }); // the first move already takes the view
          t.pump(1 / 60);
        }
        t.pointer('pointerup', { clientX: p.clientX + 48, clientY: p.clientY });
        t.pump(0.5);
        const jump = s() / before - 1;
        t.result(out, 'drag that interrupts ⌂ from the closest view', Math.abs(jump) < 1e-9 && w.autoFrame === false, { sizeOnScreenChangePct: +(100 * jump).toFixed(3), zoomAboveEndLimit: aboveEndLimit });
      }

      // S2.6: label size and far class follow the effective zoom (FAR_ZOOM 0.55)
      const labels = (name) => {
        delete w.updateLabels;
        w.updateLabels();
        const ez = REF / s();
        const scale = +getComputedStyle(w.labelsEl).getPropertyValue('--label-scale');
        const far = w.labelsEl.classList.contains('far');
        const tags = [...w.labels.values()].map((l) => l.tag);
        // #labels.far .tag:not(.lead):not(.busy) { opacity: 0 }; computed opacity lags
        // behind in a tab that draws no frames, so the rule is applied here
        const shown = tags.filter((tag) => !far || tag.classList.contains('lead') || tag.classList.contains('busy'));
        const overlaps = (list) => {
          const rs = list.map((tag) => tag.getBoundingClientRect());
          let n = 0;
          for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) if (rs[i].left < rs[j].right && rs[j].left < rs[i].right && rs[i].top < rs[j].bottom && rs[j].top < rs[i].bottom) n++;
          return n;
        };
        w.updateLabels = () => {};
        const ok = Math.abs(scale - Math.min(1.1, Math.max(0.62, 0.5 + ez * 0.28))) < 1e-6 && far === ez < 0.55;
        t.result(out, `labels, ${name}`, ok, { effectiveZoom: +ez.toFixed(3), labelScale: +scale.toFixed(3), far, tagsShown: `${shown.length}/${tags.length}`, overlapsShown: overlaps(shown) });
      };
      for (const [lay, [left, right]] of Object.entries(t.LAYOUTS)) {
        t.panels(left, right);
        t.home();
        labels(`${lay} full view`);
      }
      t.panels(true, true);
      t.home();
      w.focus(ids[6]);
      t.pump(1.0);
      labels('LR agent focus');
    } finally {
      delete w.controls.update;
      delete w.applyView;
      delete w.moveCamera;
    }
    return out;
  });
