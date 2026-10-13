// Spec 02, P1-P5: the fixed UI (topbar, panels, roster, minimap, inspector) never
// overlaps, sits where §3.1 of the spec puts it, and keeps no memory of how it got
// there. The page side of the overlaps phase: scripts/browser-test.js sets the window
// sizes and loads the pages, these functions press the real buttons, tabs, room labels
// and roster members, then measure. No t.session here: the layout is plain CSS, and the
// ResizeObservers and renders of main.js have to run as they do for a user.
window.__checks.overlaps = (() => {
  const t = window.__t;
  const { w, $ } = t;
  const COMPARED = ['topbar', 'left', 'right', 'roster', 'minimap']; // P4; the inspector is P2's
  const round = (r) => r && [r.x0, r.y0, r.x1, r.y1].map((n) => +n.toFixed(1));
  const range = (r) => r && [+r.x0.toFixed(1), +r.x1.toFixed(1)];

  // The panels as the user sees them: wide, which ones are open (LR, L-, -R, --);
  // narrow, which overlay is open (none, L, R). Narrow keeps the closed classes of the
  // wide layout out of sight: they must change nothing there (Q2).
  const state = () => {
    if (t.narrow()) return $('#left').classList.contains('open') ? 'L' : $('#right').classList.contains('open') ? 'R' : 'none';
    return `${t.isOpen('#left') ? 'L' : '-'}${t.isOpen('#right') ? 'R' : '-'}`;
  };
  const snapshot = () => {
    const f = t.fixed();
    return Object.fromEntries(COMPARED.map((k) => [k, round(f[k])]));
  };

  // P1-P3 now, and P4 when the runner hands over the reference snapshots of this size
  // (a fresh page brought to each panel state with the buttons).
  const check = (ref = null) => {
    const inspector = t.inspectorOpen();
    if (inspector) t.tallInspector();
    const f = t.fixed();
    const e = t.expected();
    const narrow = t.narrow();
    const pairs = [];
    const names = Object.keys(f);
    for (let i = 0; i < names.length; i++) {
      for (let j = i + 1; j < names.length; j++) {
        const [a, b] = [names[i], names[j]];
        // narrow: the panels and the inspector are overlays, which may cover each other
        if (narrow && ![a, b].some((n) => n === 'topbar' || n === 'roster')) continue;
        const area = t.overlap(f[a], f[b]);
        if (area > 0.01) pairs.push(`${a}/${b} ${Math.round(area)} px²`);
      }
    }
    // how far an element is from where it should be, in px (Infinity: shown or hidden wrongly)
    const off = (got, want) => (want ? (got ? Math.max(Math.abs(got.x0 - want[0]), Math.abs(got.x1 - want[1])) : Infinity) : got ? Infinity : 0);
    const miss = (name, want) => (off(f[name], want) > 0.5 ? `${name} ${JSON.stringify(range(f[name]))}, expected ${JSON.stringify(want)}` : null);
    // P2: nothing in the inspector scrolls sideways, the inspector itself or its chat
    const sideways = () => {
      const scrolling = [['inspector', $('#inspector')], ['chat', $('#chat-log')]].filter(([, x]) => x && x.scrollWidth > x.clientWidth);
      return scrolling.length ? scrolling.map(([n, x]) => `${n} scrolls sideways: ${x.scrollWidth} > ${x.clientWidth}`).join('; ') : null;
    };
    const out = {
      state: state(),
      inspector,
      P1: pairs.filter((p) => !p.includes('inspector')),
      P1i: pairs.filter((p) => p.includes('inspector')),
      P2: miss('roster', e.roster),
      P2i: inspector ? miss('inspector', e.inspector) ?? sideways() : null,
      P3: miss('minimap', e.minimap),
    };
    if (ref) {
      const want = ref[out.state];
      const got = snapshot();
      const diffs = want ? COMPARED.filter((k) => JSON.stringify(got[k]) !== JSON.stringify(want[k]) && !(got[k] && want[k] && got[k].every((n, i) => Math.abs(n - want[k][i]) <= 0.5))) : ['no reference'];
      out.P4 = diffs.length ? diffs.map((k) => `${k} ${JSON.stringify(got[k])}, fresh page ${JSON.stringify(want?.[k])}`).join('; ') : null;
    }
    return out;
  };

  // The inputs of the matrix (§3.1), each with the real element. One that cannot apply
  // now (no "Vai alla stanza" on screen, no inspector to close) returns false.
  const inputs = {
    left: async () => $('#btn-left').click(),
    right: async () => $('#btn-right').click(),
    tab: async () => $('#tabs button:not(.active)').click(),
    room: async () => {
      w.roomLabels[1].el.click(); // main.js selectTeam(team, true)
      await t.frames(2); // the Team tab renders on the next frame
    },
    goroom: async () => {
      const b = $('[data-focusroom]');
      if (!b || !b.offsetParent) return false;
      b.click();
    },
    member: async () => {
      $('#roster .member').click();
      await t.until(t.inspectorOpen);
    },
    close: async () => {
      if (!t.inspectorOpen()) return false;
      $('#inspector [data-act="close-inspector"]').click();
      await t.until(() => !t.inspectorOpen());
    },
  };
  const press = async (name) => {
    const done = await inputs[name]();
    await t.frames(2);
    return done !== false;
  };

  // Back to a start state: the inspector closed and, wide, the panels of `layout` set
  // with the buttons; narrow, every overlay closed (the closed classes stay as they are).
  const reset = async (layout) => {
    if (t.inspectorOpen()) await inputs.close();
    if (t.narrow()) {
      if ($('#left').classList.contains('open')) $('#btn-left').click();
      if ($('#right').classList.contains('open')) $('#btn-right').click();
    } else if (layout) {
      const [l, r] = [layout[0] === 'L', layout[1] === 'R'];
      if (t.isOpen('#left') !== l) $('#btn-left').click();
      if (t.isOpen('#right') !== r) $('#btn-right').click();
    }
    await t.frames(2);
  };

  // Every input of the matrix from one start state; the start itself is checked too.
  // "Vai alla stanza" needs a room open in the Team tab, ✕ an open inspector: they get it
  // with the real elements first.
  const each = async (layout, ref) => {
    const out = { start: (await reset(layout), check(ref)) };
    for (const name of Object.keys(inputs)) {
      await reset(layout);
      if (name === 'goroom') await press('room');
      if (name === 'close') await press('member');
      const applied = await press(name);
      out[name] = { ...check(ref), applied };
    }
    await reset(layout);
    return out;
  };

  // P5: in automatic mode, an input that opens or closes a panel re-frames the view and
  // A1 of spec 01 stays at 0%. mutate: the insets frozen on purpose, then a tab opens the
  // right panel: the view keeps the old framing and the check must catch it.
  const settle = async () => {
    await t.frames(3); // the ResizeObservers report, the re-frame starts
    await t.until(() => !w.fx.active(w.camera), 180);
    await t.frames(2);
  };
  const covered = () => {
    const c = window.__checks.coverage();
    return { ok: c.floorUnderObstaclesPct === 0 && c.envelopeUnderObstacles === 0, floorUnderUiPct: c.floorUnderObstaclesPct, envelopePointsUnderUi: c.envelopeUnderObstacles };
  };
  const reframe = async ({ mutate = false } = {}) => {
    await reset('LR');
    w.resetView();
    await settle();
    const out = {};
    try {
      const steps = mutate ? ['right', 'freeze', 'tab'] : ['left', 'left', 'right', 'tab'];
      for (const [i, name] of steps.entries()) {
        if (name === 'freeze') {
          w.setInsets = () => {};
          continue;
        }
        await press(name);
        await settle();
        out[`${i + 1}. ${name} → ${state()}`] = { auto: w.autoFrame, ...covered() };
      }
    } finally {
      delete w.setInsets;
      await reset('LR');
      w.setInsets(t.measure());
      w.resetView();
      await settle();
    }
    return out;
  };

  return { snapshot, state, check, press, reset, each, reframe };
})();
