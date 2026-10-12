import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

// Runs live in memory and are mirrored to data/runs/<id>.json.
export class Store {
  constructor(dataDir) {
    this.dir = join(dataDir, 'runs');
    mkdirSync(this.dir, { recursive: true });
    this.runs = new Map();
    this.timers = new Map();
    for (const f of readdirSync(this.dir).filter((n) => n.endsWith('.json'))) {
      try {
        const run = JSON.parse(readFileSync(join(this.dir, f), 'utf8'));
        if (!['completed', 'completed_with_failures', 'failed', 'stopped'].includes(run.status)) {
          run.status = 'stopped';
          run.error = run.error ?? 'Interrupted: the server stopped while this run was active.';
        }
        this.runs.set(run.id, run);
      } catch {
        // a broken file is skipped, not fatal
      }
    }
  }

  get(id) {
    return this.runs.get(id);
  }

  list() {
    return [...this.runs.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  save(run, immediate = false) {
    this.runs.set(run.id, run);
    clearTimeout(this.timers.get(run.id));
    const write = () => {
      this.timers.delete(run.id);
      writeFileSync(join(this.dir, `${run.id}.json`), JSON.stringify(run, null, 1));
    };
    if (immediate) write();
    else this.timers.set(run.id, setTimeout(write, 400));
  }

  has(id) {
    return this.runs.has(id) || existsSync(join(this.dir, `${id}.json`));
  }
}
