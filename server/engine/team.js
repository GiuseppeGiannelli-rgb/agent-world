// The staff: who exists, who is free, and what each one is doing right now.
// Every state change is broadcast, which is what moves the characters in 3D.
// Leads can spawn short-lived sub-agents when their team has more parallel
// work than people; those appear in the room's sub-agent bay and vanish after.
export class Team {
  constructor(bus) {
    this.bus = bus;
    this.agents = new Map();
    this.waiters = [];
    this.subSeq = new Map();
  }

  load(staff) {
    const ids = new Set(staff.map((s) => s.id));
    for (const [id, a] of this.agents) if (!ids.has(id) && !a.busy && a.kind !== 'sub') this.agents.delete(id);
    for (const s of staff) {
      const a = this.agents.get(s.id);
      if (a) Object.assign(a, { name: s.name, team: s.team, kind: s.kind });
      else this.agents.set(s.id, this.fresh(s));
    }
  }

  fresh(s) {
    return { id: s.id, name: s.name, team: s.team, kind: s.kind, slot: s.slot ?? null, busy: false, state: 'idle', runId: null, taskId: null, wsId: null, target: null, text: '', tool: null, toolTarget: null, model: null, verdict: null, since: Date.now() };
  }

  get(id) {
    return this.agents.get(id);
  }

  list() {
    return [...this.agents.values()];
  }

  ofTeam(team) {
    return this.list().filter((a) => a.team === team);
  }

  ceo() {
    return this.list().find((a) => a.kind === 'ceo');
  }

  lead(team) {
    return this.list().find((a) => a.team === team && a.kind === 'lead') ?? null;
  }

  set(id, patch) {
    const a = this.agents.get(id);
    if (!a) return;
    Object.assign(a, patch, { since: Date.now() });
    this.bus.emit('agent', { ...a });
  }

  take(a, runId) {
    a.busy = true;
    a.runId = runId;
    return a;
  }

  // A free worker of the team; then the lead; then, if allowed, a new sub-agent.
  tryAcquire(team, runId, { allowLead = true, spawnLimit = 0 } = {}) {
    const members = this.ofTeam(team);
    const worker = members.find((a) => !a.busy && (a.kind === 'worker' || a.kind === 'sub'));
    if (worker) return this.take(worker, runId);
    if (allowLead) {
      const lead = members.find((a) => !a.busy && a.kind === 'lead');
      if (lead) return this.take(lead, runId);
    }
    const subs = members.filter((a) => a.kind === 'sub');
    if (subs.length < spawnLimit) return this.take(this.spawn(team, runId, subs), runId);
    return null;
  }

  tryAcquireLead(team, runId) {
    const lead = this.lead(team);
    if (lead && !lead.busy) return this.take(lead, runId);
    return null;
  }

  spawn(team, runId, existing) {
    const used = new Set(existing.map((s) => s.slot));
    let slot = 0;
    while (used.has(slot)) slot++;
    const n = (this.subSeq.get(team) ?? 0) + 1;
    this.subSeq.set(team, n);
    const a = this.fresh({ id: `${team}-sub${n}`, name: `Sub ${slot + 1}`, team, kind: 'sub', slot });
    a.runId = runId;
    this.agents.set(a.id, a);
    this.bus.emit('agent.spawn', { ...a });
    return a;
  }

  despawn(id) {
    const a = this.agents.get(id);
    if (!a || a.kind !== 'sub') return;
    this.agents.delete(id);
    this.bus.emit('agent.despawn', { id, team: a.team });
  }

  // Waits for a free member of a service team (QA reviewers are shared by everyone).
  acquire(team, runId, signal) {
    const a = this.tryAcquire(team, runId, { allowLead: true });
    if (a) return Promise.resolve(a);
    return new Promise((resolve, reject) => {
      const waiter = { team, runId, resolve, reject };
      this.waiters.push(waiter);
      signal?.addEventListener('abort', () => {
        this.waiters = this.waiters.filter((w) => w !== waiter);
        reject(signal.reason ?? new Error('aborted'));
      }, { once: true });
    });
  }

  release(id, patch = {}) {
    const a = this.agents.get(id);
    if (!a) return;
    a.busy = false;
    const i = this.waiters.findIndex((w) => w.team === a.team);
    if (i >= 0) {
      const [w] = this.waiters.splice(i, 1);
      this.take(a, w.runId);
      this.set(id, { state: 'idle', taskId: null, wsId: null, target: null, tool: null, text: '' });
      w.resolve(a);
      return;
    }
    if (a.kind === 'sub') {
      this.set(id, { state: 'idle', taskId: null, target: null, tool: null, text: '' });
      this.despawn(id);
      return;
    }
    this.set(id, { state: 'idle', runId: null, taskId: null, wsId: null, target: null, tool: null, text: '', verdict: null, ...patch });
  }
}
