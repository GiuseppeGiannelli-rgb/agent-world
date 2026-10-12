import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const isObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

function merge(base, over) {
  if (!isObject(over)) return over === undefined ? base : over;
  const out = isObject(base) ? { ...base } : {};
  for (const [key, value] of Object.entries(over)) {
    out[key] = isObject(value) && isObject(out[key]) ? merge(out[key], value) : value;
  }
  return out;
}

// Sections the settings screen may change. Everything else stays file-only.
const EDITABLE = ['limits', 'pacing', 'router', 'providers', 'combos', 'teams', 'ceo', 'media', 'skills'];

// default.json ships with the app; local.json holds this machine's overrides.
export class Config {
  constructor(dir) {
    this.defaultsFile = join(dir, 'default.json');
    this.localFile = join(dir, 'local.json');
    this.reload();
  }

  reload() {
    const defaults = JSON.parse(readFileSync(this.defaultsFile, 'utf8'));
    this.local = existsSync(this.localFile) ? JSON.parse(readFileSync(this.localFile, 'utf8')) : {};
    this.value = merge(defaults, this.local);
    if (process.env.PORT) this.value.server.port = Number(process.env.PORT);
    this.value.limits.allowShell = process.env.AGENT_WORLD_ALLOW_SHELL === '1';
    // Test switch: no theatrical pauses, near-instant demo answers.
    if (process.env.AGENT_WORLD_FAST === '1') {
      for (const k of Object.keys(this.value.pacing)) this.value.pacing[k] = 20;
      this.value.providers.mock.latencyMs = [10, 40];
    }
    // Every agent of the office in one flat list: the CEO, then each team's lead and workers.
    const staff = [{ id: this.value.ceo.id, name: this.value.ceo.name, team: 'ceo', kind: 'ceo' }];
    for (const [team, t] of Object.entries(this.value.teams)) {
      if (t.lead) staff.push({ id: t.lead.id, name: t.lead.name, team, kind: 'lead' });
      for (const w of t.workers ?? []) staff.push({ id: w.id, name: w.name, team, kind: 'worker' });
    }
    this.value.staff = staff;
  }

  get() {
    return this.value;
  }

  update(patch) {
    for (const key of EDITABLE) {
      if (patch[key] === undefined) continue;
      // Combos are replaced whole so a removed fallback step really goes away.
      this.local[key] = key === 'combos' ? patch[key] : merge(this.local[key] ?? {}, patch[key]);
    }
    writeFileSync(this.localFile, JSON.stringify(this.local, null, 2));
    this.reload();
  }
}
