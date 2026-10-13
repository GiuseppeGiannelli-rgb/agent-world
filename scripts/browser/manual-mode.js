// A7 (T6): which inputs hand the view to the user, and what manual mode keeps still.
// The picture is measured as the floor corners and the target on screen, before and
// after the right panel closes and opens again: in manual mode it must not move by a
// hair, in automatic mode the panels re-frame it. Drag inertia decays by 0.92 a frame,
// so each case waits 3 s (0.92^180 ~ 3e-7) before comparing.
window.__checks.manualMode = () =>
  window.__t.session(async (t) => {
    const { w, c, $ } = t;
    const out = {};
    const ids = [...w.actors.keys()];
    const rightPanel = (open) => t.panels(true, open);
    const scenario = (name, act, takesView = true) => {
      rightPanel(true);
      t.home();
      act();
      t.pump(3.0);
      const auto = w.autoFrame;
      const a = t.picture();
      rightPanel(false);
      t.pump(0.6);
      const b = t.picture();
      rightPanel(true);
      t.pump(0.6);
      const moved = Math.max(t.moved(a, b), t.moved(a, t.picture()));
      t.result(out, name, takesView ? !auto && moved < 0.01 : auto && moved > 1, { autoFrame: auto, pxMovedByPanels: moved });
    };
    const touch = (type, id, p) => c.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: id, pointerType: 'touch', isPrimary: id % 2 === 1, button: 0, buttons: type === 'pointerup' ? 0 : 1, ...p }));
    const nudge = (p, dx, dy = 0) => ({ clientX: p.clientX + dx, clientY: p.clientY + dy });

    // inputs that take the view
    scenario('drag (pan)', () => t.drag(t.at(0.5, 0.5), t.at(0.6, 0.55)));
    scenario('drag with the right button (rotate)', () => t.drag(t.at(0.5, 0.5), t.at(0.6, 0.5), 6, { button: 2, buttons: 2 }));
    scenario('drag with the middle button (dolly)', () => t.drag(t.at(0.5, 0.5), t.at(0.5, 0.45), 6, { button: 1, buttons: 4 }));
    scenario('drag of exactly 5 px', () => t.drag(t.at(0.5, 0.5), nudge(t.at(0.5, 0.5), 5), 5));
    scenario('drag out and back', () => {
      const p = t.at(0.4, 0.4);
      t.pointer('pointerdown', p);
      t.pointer('pointermove', nudge(p, 30));
      t.pump(0.05);
      t.pointer('pointermove', p);
      t.pointer('pointerup', p);
    });
    scenario('wheel', () => t.wheel(t.at(0.5, 0.5), -100));
    scenario('trackpad pinch (ctrl + wheel)', () => c.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 3, ctrlKey: true, ...t.at(0.5, 0.5) })));
    scenario('touch pinch, 3 px per finger', () => {
      const a = t.at(0.45, 0.5);
      const b = t.at(0.55, 0.5);
      touch('pointerdown', 11, a);
      touch('pointerdown', 12, b);
      for (let i = 1; i <= 3; i++) {
        touch('pointermove', 11, nudge(a, -i));
        touch('pointermove', 12, nudge(b, i));
        t.pump(1 / 60);
      }
      touch('pointerup', 11, nudge(a, -3));
      touch('pointerup', 12, nudge(b, 3));
    });
    scenario('click on an agent', () => {
      const [x, y] = t.toScreen(w.actors.get(ids[5]).position.clone().setY(0.7));
      const p = { clientX: t.rect().left + x, clientY: t.rect().top + y };
      t.pointer('pointerdown', p);
      t.pointer('pointerup', p);
    });
    scenario('click on a room label', () => w.roomLabels[1].el.click());
    scenario('click on the minimap', () => {
      const m = w.minimap.getBoundingClientRect();
      w.minimap.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: m.left + m.width * 0.2, clientY: m.top + m.height * 0.3 }));
    });

    // inputs that do not
    scenario('click on the floor, 2 px of jitter', () => t.drag(t.at(0.52, 0.52), nudge(t.at(0.52, 0.52), 2, 1), 2), false);
    scenario('drag of 4.9 px', () => t.drag(t.at(0.5, 0.5), nudge(t.at(0.5, 0.5), 4.9), 3), false);
    scenario('horizontal wheel only (deltaY 0)', () => c.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaX: 80, deltaY: 0, ...t.at(0.5, 0.5) })), false);
    scenario('wheel while a press is held', () => {
      t.pointer('pointerdown', t.at(0.5, 0.5));
      t.wheel(t.at(0.5, 0.5), -100);
      t.pointer('pointerup', t.at(0.5, 0.5));
    }, false);
    scenario('two-finger tap', () => {
      touch('pointerdown', 21, t.at(0.45, 0.5));
      touch('pointerdown', 22, t.at(0.55, 0.5));
      touch('pointerup', 21, t.at(0.45, 0.5));
      touch('pointermove', 22, nudge(t.at(0.55, 0.5), 1));
      touch('pointerup', 22, t.at(0.55, 0.5));
    }, false);
    scenario('cancelled press, then hover', () => {
      t.pointer('pointerdown', t.at(0.5, 0.5));
      t.pointer('pointercancel', t.at(0.5, 0.5));
      t.pointer('pointermove', t.at(0.7, 0.7), { buttons: 0 });
    }, false);
    scenario('lost release, then hover', () => {
      t.pointer('pointerdown', t.at(0.5, 0.5));
      t.pointer('pointermove', t.at(0.7, 0.7), { buttons: 0 });
      t.pointer('pointerup', t.at(0.7, 0.7)); // only so the controls leave their pan state
    }, false);

    // ⌂ hands the view back, animated, and the panels re-frame it again
    {
      rightPanel(true);
      t.home();
      t.drag(t.at(0.5, 0.5), t.at(0.65, 0.6));
      t.pump(3.0);
      const a = t.picture();
      $('#btn-home').click();
      t.pump(1 / 60);
      const firstFrame = t.moved(a, t.picture());
      const animating = w.fx.active(w.camera) != null;
      t.pump(0.7);
      const lens = t.centreLens();
      const fitted = w.view.lensX === lens.lensX && w.camera.zoom === 1;
      const b = t.picture();
      rightPanel(false);
      t.pump(0.6);
      const reframed = t.moved(b, t.picture());
      t.result(out, '⌂ back to automatic', w.autoFrame && animating && firstFrame > 0 && firstFrame < 40 && fitted && reframed > 1, { autoFrame: w.autoFrame, firstFramePx: firstFrame, animating, fitted, pxMovedByPanelsAfter: reframed });
    }

    // a resize keeps scale, lens and target in manual mode; re-fits in automatic mode
    {
      rightPanel(true);
      t.home();
      t.drag(t.at(0.5, 0.5), t.at(0.58, 0.55));
      t.pump(3.0);
      const v0 = { ...w.view, zoom: w.camera.zoom, target: w.controls.target.clone() };
      const width = w.width;
      const css = c.parentElement.style.cssText;
      c.parentElement.style.cssText += ';right:160px;bottom:90px';
      t.sync();
      const same = w.view.unitsPerPx === v0.unitsPerPx && w.view.lensX === v0.lensX && w.view.lensY === v0.lensY && w.camera.zoom === v0.zoom && w.controls.target.equals(v0.target);
      const aspect = Math.abs((w.camera.right - w.camera.left) / (w.camera.top - w.camera.bottom) - w.width / w.height) < 1e-9;
      t.pump(0.5);
      // the tail of the drag inertia still nudges the target by ~1e-6 units
      const still = w.view.unitsPerPx === v0.unitsPerPx && w.controls.target.distanceTo(v0.target) < 1e-5;
      t.result(out, 'resize in manual mode', !w.autoFrame && same && aspect && still && w.width === width - 160, { size: [w.width, w.height], sameView: same, aspectMatches: aspect, stillAfterFrames: still });
      c.parentElement.style.cssText = css;
      t.sync();
      $('#btn-home').click();
      t.pump(0.8);
      c.parentElement.style.cssText += ';right:160px;bottom:90px';
      t.sync();
      const refitted = w.view.lensX === t.centreLens().lensX;
      t.result(out, 'resize in automatic mode', w.autoFrame && refitted && w.width === width - 160, { refitted });
      c.parentElement.style.cssText = css;
      t.sync();
      t.pump(0.3);
    }

    // S3.7: a focus centres on the free area as the panels are now, in manual mode too
    {
      rightPanel(false);
      t.home();
      t.drag(t.at(0.5, 0.5), t.at(0.55, 0.5)); // manual, framed without the right panel
      t.pump(1.0);
      rightPanel(true); // the view stays...
      t.pump(0.6);
      const a = w.actors.get(ids[7]);
      const p0 = new t.V3(a.position.x, 0, a.position.z); // idle agents wander off
      w.focus(ids[7]); // ...until the user centres something
      t.pump(1.0);
      const lens = t.centreLens();
      const [x, y] = t.toScreen(p0);
      const off = [x - (w.width / 2 + lens.lensX), y - (w.height / 2 + lens.lensY)];
      t.result(out, 'focus centres in the free area', Math.hypot(...off) < 1, { offPx: off.map((n) => +n.toFixed(2)) });
    }

    // S3.7, review R2: a room label clicked with the right panel closed opens the Team
    // tab, and the room lands at the centre of the free area that is left once it is open
    {
      rightPanel(false);
      t.home();
      const room = w.layout.rooms[1];
      w.roomLabels.find((r) => r.team === room.team).el.click(); // selectTeam(team, true) in main.js
      t.sync(); // the ResizeObserver after the panel opened
      t.pump(1.0);
      const lens = t.centreLens();
      const [x, y] = t.toScreen(new t.V3(room.x, 0, room.z));
      const off = [x - (w.width / 2 + lens.lensX), y - (w.height / 2 + lens.lensY)];
      t.result(out, 'room label with the right panel closed', t.isOpen('#right') && Math.hypot(...off) < 1, { rightPanelOpened: t.isOpen('#right'), offPx: off.map((n) => +n.toFixed(2)) });
      rightPanel(true);
    }

    // A press held while code moves the camera, then a drag (review R1). The grab follows
    // the picture: the floor point under the pointer when the drag starts ends under the
    // pointer (A3), wherever the move took the point first pressed. MapControls on its own
    // pulls that first point back, and the view slid 82-447 px at 1920x1080.
    const dragAfterMove = (name, start, { wait, drag: [dx, dy], steps, check = () => ({}) }) => {
      rightPanel(true);
      t.home();
      start();
      const from = t.at(0.4, 0.5);
      t.pointer('pointerdown', from);
      t.pump(wait); // the move shifts the view under the press...
      let at = from;
      let grabbed = null;
      const seen = {};
      for (let i = 1; i <= steps; i++) {
        // until the view is taken, what is under the pointer is what the drag holds
        if (i === 1 || w.fx.active(w.camera)) grabbed = t.floorAt(at);
        at = nudge(from, (dx * i) / steps, (dy * i) / steps);
        t.pointer('pointermove', at);
        Object.assign(seen, check(i));
        t.pump(1 / 60);
      }
      t.pump(1.5); // the damping catches up while the button is still down
      const r = t.rect();
      const [gx, gy] = t.toScreen(grabbed);
      const off = [gx + r.left - at.clientX, gy + r.top - at.clientY];
      t.pointer('pointerup', at);
      const ok = Math.hypot(...off) < 1 && Object.values(seen).every(Boolean);
      t.result(out, name, ok, { ...seen, grabOffPx: off.map((n) => +n.toFixed(2)) });
    };
    // below the threshold an automatic move goes on, past it the move stops
    dragAfterMove('drag during an automatic re-frame', () => {
      rightPanel(false); // 0.35 s re-frame starts
      t.pump(0.1);
    }, {
      wait: 0.08,
      drag: [120, 40],
      steps: 30, // 4.2 px a step
      check: (i) => (i === 1 ? { movesOnBelow5px: w.fx.active(w.camera) != null && w.autoFrame === true } : i === 2 ? { stopsAt8px: w.fx.active(w.camera) == null && w.autoFrame === false } : {}),
    });
    dragAfterMove('drag during a focus', () => {
      w.focus(ids[2]);
      t.pump(0.05);
    }, { wait: 0.2, drag: [20, 0], steps: 4 });
    dragAfterMove('drag during ⌂ from a close-up', () => {
      w.focus(ids[4]);
      t.pump(1.0);
      $('#btn-home').click();
      t.pump(0.05);
    }, { wait: 0.2, drag: [20, 0], steps: 4 });
    dragAfterMove('press held through a focus, then 3 px', () => {
      w.focus(ids[2]);
      t.pump(0.05);
    }, { wait: 1.0, drag: [3, 0], steps: 1 });
    rightPanel(true);

    // S4.6: a click while the camera moves leaves no drift and no jump
    for (const hold of [0.05, 0.15]) {
      const run = (thenFocus) => {
        rightPanel(true);
        t.home();
        w.focus(ids[2]);
        t.pump(0.15);
        const p = t.at(0.4, 0.6);
        t.pointer('pointerdown', p);
        t.pump(hold);
        t.pointer('pointermove', nudge(p, 1));
        t.pump(1 / 60);
        t.pointer('pointerup', nudge(p, 1));
        if (thenFocus) {
          const a = t.picture();
          w.focus(ids[9]);
          return t.moved(a, t.picture());
        }
        t.pump(0.7);
        const a = t.picture();
        t.pump(1.0);
        return t.moved(a, t.picture());
      };
      const drift = run(false);
      const jump = run(true);
      t.result(out, `click during a focus, held ${hold} s`, drift < 0.01 && jump < 0.01, { driftAfterPx: drift, jumpAtNextFocusPx: jump });
    }
    return out;
  });
