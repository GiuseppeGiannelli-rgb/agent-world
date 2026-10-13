// Spec 02, E1-E6 and the N4 variants: where the labels of the rooms, the Brain and the
// agents land on screen, what each one covers, and which clicks they take.
// - production: the labels as drawn (DOM rectangles), in the order they are painted;
// - variants (oggi, A, B, C; spec §4.3): the room labels computed from an anchor and an
//   alignment, without touching the app. "oggi" is today's anchor and must match the
//   drawn labels within 1 px in every state, or nothing measured on A, B, C is worth
//   anything (the "model" check).
// It runs in t.session: the clock pumped at 60 fps, drawing suspended, the labels placed
// by the real updateLabels() right before each measure. Agents sit at their seats.
window.__checks.labels = (() => {
  const t = window.__t;
  const { w } = t;
  const place = () => Object.getPrototypeOf(w).updateLabels.call(w);
  const FAR_HIDDEN = '#labels.far .tag:not(.lead):not(.busy)';
  const BUBBLE = '💭 Scrivo la pagina del menu con prezzi e allerg…'; // short() keeps 46 characters
  // anchor on the floor (world units) and alignment of the label on it, as fractions of
  // its size: [0, 0.5] = left end, centred vertically (today); [1, 0] = right end, top
  const VARIANTS = {
    oggi: (r) => ({ at: [r.x - r.w / 2 + 0.2, 0.1, r.z - r.d / 2 + 0.2], align: [0, 0.5] }),
    A: (r) => ({ at: [r.x - r.w / 2 + 0.2, 0.1, r.z + r.d / 2 - 0.2], align: [0, 1] }),
    B: (r) => ({ at: [r.x, 0.1, r.z + r.d / 2 - 0.2], align: [0.5, 1] }),
    C: (r) => ({ at: [r.x + r.w / 2 - 0.2, 0.1, r.z + r.d / 2 + 0.2], align: [1, 0] }),
  };

  // ---------- the scene ----------

  // Agents at their seats, no stroll, no effect running: labels that do not move
  // between one measure and the next.
  const still = () => {
    w.wander = () => {};
    for (const a of w.actors.values()) {
      a.idleTrip = false;
      a.placeAtSeat();
    }
    for (let i = 0; i < 300 && w.fx.items.length; i++) t.pump(1 / 60);
    for (const a of w.actors.values()) a.placeAtSeat();
  };
  // Every bay seat taken, the way the lead spawns sub-agents during a run.
  const fillBays = () => {
    for (const [team, seats] of w.layout.bays) {
      seats.forEach((_, j) => {
        const id = `${team}-sub-check${j}`;
        if (!w.actors.has(id)) w.onSpawn({ id, name: `Sub ${j + 1}`, team, kind: 'sub', slot: j });
      });
    }
    t.pump(1.5);
    still();
    return [...w.actors.values()].filter((a) => a.kind === 'sub').length;
  };
  const bubbles = (open) => {
    for (const l of w.labels.values()) {
      if (open) {
        l.bubble.innerHTML = BUBBLE;
        l.bubble.className = 'bubble show';
        l.hideAt = performance.now() + 1e9;
      } else {
        l.bubble.classList.remove('show');
        l.hideAt = 0;
      }
    }
  };

  // ---------- the views of the matrix (§3.2) ----------

  const views = () => {
    const REF = t.F.REF_UNITS_PER_PX;
    const zoom = (ez) => () => {
      t.home();
      const z = (ez * w.view.unitsPerPx) / REF; // effective zoom = REF / (unitsPerPx / zoom)
      if (z < w.controls.minZoom || z > w.controls.maxZoom) return false; // out of the user's reach
      w.camera.zoom = z;
      w.camera.updateProjectionMatrix();
    };
    const list = [
      ['vista completa', () => t.home()],
      ['zoom 0,8', zoom(0.8)],
      ['zoom 1', zoom(1)],
      ['zoom 1,3', zoom(1.3)],
    ];
    for (const room of [w.layout.rooms[1], w.layout.rooms[5]]) {
      const id = [...w.actors].find(([, a]) => a.team === room.team && a.kind === 'worker')?.[0];
      if (id) {
        const focus = () => {
          t.home();
          w.focus(id);
          t.pump(0.8);
        };
        list.push([`focus su ${id}`, focus]);
        list.push([
          `primo piano su ${id}`,
          () => {
            focus();
            w.camera.zoom = w.controls.maxZoom;
            w.camera.updateProjectionMatrix();
          },
        ]);
      }
      list.push([
        `stanza ${room.team}`,
        () => {
          t.home();
          w.focusRoom(room.team);
          t.pump(0.8);
        },
      ]);
    }
    return list;
  };

  // ---------- measures ----------

  const centre = (b) => [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2];
  const within = ([x, y], b) => x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1;
  const union = (bs) => ({ x0: Math.min(...bs.map((b) => b.x0)), y0: Math.min(...bs.map((b) => b.y0)), x1: Math.max(...bs.map((b) => b.x1)), y1: Math.max(...bs.map((b) => b.y1)) });
  const edge = (a, b) => Math.max(Math.abs(a.x0 - b.x0), Math.abs(a.y0 - b.y0), Math.abs(a.x1 - b.x1), Math.abs(a.y1 - b.y1));
  const covered = (box, over) => Math.min(t.area(box), over.reduce((n, o) => n + t.overlap(box, o), 0)); // labels above one another barely touch

  // The room label of a variant on screen now: the anchor projected, the label's own size
  // (offsetWidth/offsetHeight, before the transform) at the labels' scale, aligned on it.
  // The name (the coloured square and the bold text) is placed the same way from its
  // offsets inside the label, which start at the label's padding edge (+ clientLeft).
  const modelled = (room, el, variant, scale, cr) => {
    const { at, align } = VARIANTS[variant](room);
    const [X, Y] = t.toScreen(new t.V3(...at));
    const [W, H] = [el.offsetWidth, el.offsetHeight];
    const x0 = cr.left + X - align[0] * W * scale;
    const y0 = cr.top + Y - align[1] * H * scale;
    const parts = [el.querySelector('i'), el.querySelector('b')];
    const nx0 = Math.min(...parts.map((p) => el.clientLeft + p.offsetLeft));
    const ny0 = Math.min(...parts.map((p) => el.clientTop + p.offsetTop));
    const nx1 = Math.max(...parts.map((p) => el.clientLeft + p.offsetLeft + p.offsetWidth));
    const ny1 = Math.max(...parts.map((p) => el.clientTop + p.offsetTop + p.offsetHeight));
    return {
      box: { x0, y0, x1: x0 + W * scale, y1: y0 + H * scale },
      name: { x0: x0 + nx0 * scale, y0: y0 + ny0 * scale, x1: x0 + nx1 * scale, y1: y0 + ny1 * scale },
      anchor: at,
    };
  };

  // The "SUB-AGENT BAY" text painted on the floor of each bay (office.js bayMark): a
  // 512 x 160 canvas on an 8.6 x 2.7 plane centred at (x - 0.4, z + 1.75), the text bold
  // 22 px, right-aligned at 22 px from the right edge, baseline 20 px above the bottom.
  const bayText = (() => {
    const g = document.createElement('canvas').getContext('2d');
    g.font = '700 22px "Segoe UI", system-ui, sans-serif';
    const m = g.measureText('SUB-AGENT BAY');
    const [u, v] = [8.6 / 512, 2.7 / 160]; // world units per canvas px, across and down
    return (room) => {
      const right = room.x - 0.4 - 4.3 + (512 - 22) * u;
      const base = room.z + 1.75 - 1.35 + (160 - 20) * v; // the canvas top lies at the back
      const top = base - m.actualBoundingBoxAscent * v;
      const pts = [
        [right - m.width * u, top],
        [right, top],
        [right - m.width * u, base],
        [right, base],
      ].map(([x, z]) => t.toScreen(new t.V3(x, 0.05, z)));
      const cr = t.rect();
      return { x0: cr.left + Math.min(...pts.map((p) => p[0])), y0: cr.top + Math.min(...pts.map((p) => p[1])), x1: cr.left + Math.max(...pts.map((p) => p[0])), y1: cr.top + Math.max(...pts.map((p) => p[1])) };
    };
  })();

  // One state measured: production and every variant. `worst` keeps, for each measure,
  // the largest value seen and where.
  const measure = (where, { fit, out }) => {
    const keep = (key, value, extra = {}) => {
      const n = (out.counts[key] ??= [0, 0]); // states where it is not 0, states measured
      n[1]++;
      if (value > 0) n[0]++;
      const cur = out.worst[key];
      if (!cur || value > cur.value) out.worst[key] = { value: +value.toFixed(2), where, ...extra };
    };
    const cr = t.rect();
    const safe = (() => {
      const s = t.F.safeRect(w.width, w.height, w.insets);
      return { x0: cr.left + s.x0, y0: cr.top + s.y0, x1: cr.left + s.x1, y1: cr.top + s.y1 };
    })();
    const kids = [...w.labelsEl.children];
    const zIndex = (el) => {
      const z = getComputedStyle(el).zIndex;
      return z === 'auto' ? 0 : Number(z);
    };
    const order = (el) => zIndex(el) * 1e4 + kids.indexOf(el); // higher is painted later, on top

    const pass = (withBubbles) => {
      bubbles(withBubbles);
      w.camera.updateMatrixWorld();
      place();
      const scale = parseFloat(w.labelsEl.style.getPropertyValue('--label-scale'));
      const agents = [];
      for (const [id, l] of w.labels) {
        const a = w.actors.get(id);
        if (!a) continue;
        const seated = a.atSeat();
        if (!l.tag.matches(FAR_HIDDEN)) agents.push({ id, kind: 'tag', el: l.tag, box: t.box(l.tag), order: order(l.tag), seated, sub: a.kind === 'sub', worker: a.kind === 'worker' });
        if (l.bubble.classList.contains('show')) agents.push({ id, kind: 'bubble', el: l.bubble, box: t.box(l.bubble), order: order(l.bubble), seated, sub: a.kind === 'sub' });
      }
      const rooms = w.roomLabels.map((r) => {
        const room = w.layout.rooms.find((x) => x.team === r.team);
        return { r, room, el: r.el, box: t.box(r.el), name: union([t.box(r.el.querySelector('i')), t.box(r.el.querySelector('b'))]), order: order(r.el) };
      });
      const brain = w.brainLabel ? { box: t.box(w.brainLabel), order: order(w.brainLabel) } : null;
      return { scale, agents, rooms, brain };
    };

    // E1: how much of each agent label or bubble the places painted above it cover
    const e1 = (agents, places, above) => {
      let pct = 0;
      let n = 0;
      for (const a of agents) {
        const c = covered(a.box, places.filter((p) => above(p, a)).map((p) => p.box)) / t.area(a.box);
        if (c > 0) n++;
        pct = Math.max(pct, 100 * c);
      }
      return { pct, n };
    };
    // E2: the name of each room under the labels of agents at their seats, painted above it
    const e2 = (rooms, agents, above) => Math.max(0, ...rooms.map((r) => covered(r.name, agents.filter((a) => a.kind === 'tag' && a.seated && !above(r, a)).map((a) => a.box))));
    // E4: pairs of place labels that overlap
    const e4 = (places) => {
      let n = 0;
      for (let i = 0; i < places.length; i++) for (let j = i + 1; j < places.length; j++) if (t.overlap(places[i].box, places[j].box) > 0.5) n++;
      return n;
    };

    // ---- with every bubble open: E1 ----
    {
      const { scale, agents, rooms, brain } = pass(true);
      const prodPlaces = [...rooms, ...(brain ? [brain] : [])];
      const r = e1(agents, prodPlaces, (p, a) => p.order > a.order);
      keep('prod E1', r.pct, { covered: r.n });
      for (const v of Object.keys(VARIANTS)) {
        const places = rooms.map((x) => ({ ...modelled(x.room, x.el, v, scale, cr), order: x.order })).concat(brain ? [brain] : []);
        const today = e1(agents, places, (p, a) => p.order > a.order);
        keep(`${v} E1 ordine dell'app`, today.pct, { covered: today.n });
        const agentsAbove = e1(agents, places, () => false);
        keep(`${v} E1 agenti sopra`, agentsAbove.pct, { covered: agentsAbove.n });
      }
    }

    // ---- bubbles closed: the model check, E2-E6, the bay text ----
    const { scale, agents, rooms, brain } = pass(false);
    const prodPlaces = [...rooms, ...(brain ? [brain] : [])];

    // the model against the room labels as drawn: one variant must match them within
    // 1 px, anchor included, and that is the variant the app draws ("oggi" before T3)
    const [drawn, off] = Object.keys(VARIANTS)
      .map((v) => {
        const worst = Math.max(
          ...rooms.map((x) => {
            const m = modelled(x.room, x.el, v, scale, cr);
            const anchorOff = Math.max(...m.anchor.map((c, i) => Math.abs(c - x.r.pos.getComponent(i))));
            return Math.max(edge(m.box, x.box), edge(m.name, x.name), anchorOff * 1e3);
          }),
        );
        return [v, worst];
      })
      .sort((a, b) => a[1] - b[1])[0];
    keep('model check', off, { variant: drawn });
    out.drawn[drawn] = (out.drawn[drawn] ?? 0) + 1;

    // spec 01, report N4: idle workers whose label has its centre under their room's
    // label where it was before T3, painted over them as it was (the model of "oggi")
    if (out.spec01 === undefined && where.startsWith('LR vista completa')) {
      const before = rooms.map((x) => modelled(x.room, x.el, 'oggi', scale, cr).box);
      const workers = agents.filter((a) => a.kind === 'tag' && a.worker);
      const hit = workers.map((a) => ({ a, box: before.find((b) => within(centre(a.box), b)) })).filter((x) => x.box);
      out.spec01 = { workers: workers.length, covered: hit.length, pct: hit.map(({ a, box }) => Math.round((100 * t.overlap(a.box, box)) / t.area(a.box))).sort((p, q) => p - q) };
    }

    // pick points: the body of each seated agent at 0.4, 0.8 and 1.2 above the floor,
    // where a click picks that very agent (not one standing in front of it)
    const picks = [];
    for (const a of agents.filter((x) => x.kind === 'tag' && x.seated)) {
      const actor = w.actors.get(a.id);
      for (const y of [0.4, 0.8, 1.2]) {
        const [x, yy] = t.toScreen(actor.position.clone().setY(actor.position.y + y));
        const p = { clientX: cr.left + x, clientY: cr.top + yy };
        if (p.clientX < cr.left || p.clientX > cr.right || p.clientY < cr.top || p.clientY > cr.bottom) continue;
        if (w.pick(p) === a.id) picks.push({ id: a.id, y, sub: actor.kind === 'sub', p: [p.clientX, p.clientY] });
      }
    }
    // the agents with a pick point taken, and which points: "Sub@0.4" is a sub-agent's
    // lowest point, the others are leads, workers and the CEO
    const tally = (hits) => {
      const ids = new Set(hits.map((x) => x.id));
      return [ids.size, { points: [...new Set(hits.map((x) => `${x.sub ? 'Sub' : 'agent'}@${x.y}`))].sort(), subAgents: new Set(hits.filter((x) => x.sub).map((x) => x.id)).size, others: new Set(hits.filter((x) => !x.sub).map((x) => x.id)).size }];
    };
    const intercepted = (boxes) => tally(picks.filter(({ p }) => boxes.some((b) => within(p, b))));

    // production
    keep('prod E2', e2(rooms, agents, (r, a) => r.order > a.order));
    if (fit) keep('prod E3', rooms.filter((x) => !t.inside(x.box, safe)).length);
    keep('prod E4', e4(prodPlaces));
    const takenBy = (p) => document.elementFromPoint(p[0], p[1]);
    // E5, with the exception accepted with D8 (spec §3.2): the lowest point of a
    // sub-agent may lie under its room label; it is counted apart
    const feet = (x) => x.sub && x.y === 0.4;
    const taken = picks.filter(({ p }) => takenBy(p)?.closest('.room-label'));
    keep('prod E5', ...tally(taken.filter((x) => !feet(x))));
    keep('prod E5 piedi', ...tally(taken.filter(feet)));
    // a name is visible when nothing of the UI lies over it (the minimap is no obstacle
    // for the framing and may cover one); a visible name must take the click itself
    const stage = w.canvas.parentElement;
    const names = rooms.filter((x) => within(centre(x.name), safe) && stage.contains(takenBy(centre(x.name))));
    const lost = names.filter((x) => takenBy(centre(x.name)).closest('.room-label') !== x.el);
    keep('prod E5 nomi', lost.length, { takenBy: lost.map((x) => `${x.r.team}: ${takenBy(centre(x.name)).className || takenBy(centre(x.name)).tagName}`) });
    if (w.labelsEl.classList.contains('far')) {
      const hidden = [...w.labels.values()].filter((l) => l.tag.matches(FAR_HIDDEN));
      keep('prod E6', hidden.filter((l) => takenBy(centre(t.box(l.tag)))?.closest('.tag') === l.tag).length, { hidden: hidden.length });
    }

    // the "SUB-AGENT BAY" text painted on the floor: up to 27% may be covered (D8)
    const bays = rooms.filter((x) => w.layout.bays.get(x.r.team)?.length);
    for (const x of bays) {
      const text = bayText(x.room);
      keep('prod scritta della bay', (100 * covered(text, rooms.map((r) => r.box))) / t.area(text), { team: x.r.team });
    }

    // variants
    for (const v of Object.keys(VARIANTS)) {
      const places = rooms.map((x) => ({ ...x, ...modelled(x.room, x.el, v, scale, cr) }));
      keep(`${v} E2`, e2(places, agents, () => false));
      if (fit) keep(`${v} E3`, places.filter((x) => !t.inside(x.box, safe)).length);
      keep(`${v} E4`, e4(places.concat(brain ? [brain] : [])));
      keep(`${v} E5`, ...intercepted(places.map((x) => x.box)));
      for (const x of bays) {
        const text = bayText(x.room);
        keep(`${v} scritta della bay`, (100 * covered(text, places.map((p) => p.box))) / t.area(text), { team: x.r.team });
      }
    }
    out.states++;
  };

  // The whole matrix at the current window size, for one bay state. The runner calls it
  // once per size, with the bays empty first, then full.
  const run = ({ bays = 'vuote' } = {}) =>
    t.session(async () => {
      still();
      const out = { worst: {}, counts: {}, drawn: {}, states: 0, skipped: [] };
      if (bays === 'piene') out.subAgents = fillBays();
      for (const [lay, [left, right]] of Object.entries(t.LAYOUTS)) {
        t.panels(left, right);
        for (const [view, go] of views()) {
          if (go() === false) {
            out.skipped.push(`${lay} ${view}`);
            continue;
          }
          measure(`${lay} ${view}, bay ${bays}`, { fit: view === 'vista completa', out });
        }
      }
      bubbles(false);
      t.home();
      return out;
    });

  // A variant drawn by CSS, for the screenshots and to check the model of every variant
  // as on the labels the app draws: updateLabels() is wrapped on this page only (the
  // app is not touched) and puts each room label on the variant's anchor, its transform
  // origin on the same point so the labels' scale leaves the anchor still, as T3 does.
  // order: "agenti" puts the agents' labels and bubbles over the place labels (E1, the
  // app's from T3), "oggi" leaves the DOM order (the app's before T3). null: the app's own.
  const ORDER = 'labels-order';
  const preview = (variant, { order = variant === 'oggi' ? 'oggi' : 'agenti' } = {}) => {
    delete w.updateLabels;
    document.getElementById(ORDER)?.remove();
    for (const r of w.roomLabels) r.el.style.removeProperty('transform-origin');
    if (variant === null) return place();
    const style = document.createElement('style');
    style.id = ORDER;
    style.textContent = order === 'agenti' ? '#labels .tag, #labels .bubble { z-index: 1; } #labels .room-label, #labels .brain-label { z-index: 0; }' : '#labels .tag, #labels .bubble, #labels .room-label, #labels .brain-label { z-index: auto; }';
    document.head.append(style);
    const proto = Object.getPrototypeOf(w);
    w.updateLabels = function () {
      proto.updateLabels.call(this);
      for (const r of this.roomLabels) {
        const { at, align } = VARIANTS[variant](this.layout.rooms.find((x) => x.team === r.team));
        const [x, y] = t.toScreen(new t.V3(...at));
        r.el.style.setProperty('transform-origin', `${align[0] * 100}% ${align[1] * 100}%`, 'important');
        r.el.style.transform = `translate(${x}px, ${y}px) translate(${-align[0] * 100}%, ${-align[1] * 100}%) scale(var(--label-scale))`;
      }
    };
    w.updateLabels();
  };
  // The model of every variant against the same variant drawn by CSS (preview), over
  // the layouts and a few views: the room label and its name, worst edge in px.
  const checkVariants = () =>
    t.session(async () => {
      still();
      const out = {};
      const cr = t.rect();
      try {
        for (const v of Object.keys(VARIANTS)) {
          let worst = 0;
          let where = '';
          for (const [lay, [left, right]] of Object.entries(t.LAYOUTS)) {
            t.panels(left, right);
            for (const [view, go] of views().filter(([name]) => !name.startsWith('stanza'))) {
              if (go() === false) continue;
              w.camera.updateMatrixWorld();
              preview(v);
              const scale = parseFloat(w.labelsEl.style.getPropertyValue('--label-scale'));
              for (const r of w.roomLabels) {
                const m = modelled(w.layout.rooms.find((x) => x.team === r.team), r.el, v, scale, cr);
                const drawn = { box: t.box(r.el), name: union([t.box(r.el.querySelector('i')), t.box(r.el.querySelector('b'))]) };
                const d = Math.max(edge(m.box, drawn.box), edge(m.name, drawn.name));
                if (d > worst) [worst, where] = [d, `${lay} ${view}, ${r.team}`];
              }
              // the session stubs updateLabels: the wrapper must not outlive this measure
              preview(null);
            }
          }
          out[v] = { worstPx: +worst.toFixed(2), where };
        }
      } finally {
        preview(null);
        t.home();
      }
      return out;
    });

  // E1 must catch the order put back on purpose: the room labels over the agents'.
  const orderTrap = () =>
    t.session(async () => {
      still();
      const style = document.createElement('style');
      style.textContent = '#labels .room-label, #labels .brain-label { z-index: 2; }';
      document.head.append(style);
      const out = { worst: {}, counts: {}, drawn: {}, states: 0 };
      try {
        t.panels(true, true);
        for (const [view, go] of views().slice(0, 4)) if (go() !== false) measure(`LR ${view}`, { fit: false, out });
      } finally {
        style.remove();
        bubbles(false);
        t.home();
      }
      return out.worst['prod E1'];
    });

  // For the wheel checks (E7) with real input: the centre of a room name and of an agent
  // label that the pointer would really hit there, in the view on screen now.
  const targets = () => {
    place();
    const free = (el) => {
      const [x, y] = centre(t.box(el));
      return el.contains(document.elementFromPoint(x, y)) ? [x, y] : null;
    };
    const room = w.roomLabels.map((r) => free(r.el.querySelector('b'))).find(Boolean) ?? null;
    const tag = [...w.labels.values()].filter((l) => !l.tag.matches(FAR_HIDDEN)).map((l) => free(l.tag)).find(Boolean) ?? null;
    return { room, tag };
  };
  const done = () => {
    delete w.wander;
    bubbles(false);
  };

  return { run, targets, done, still, preview, checkVariants, orderTrap, VARIANTS: Object.keys(VARIANTS) };
})();
