import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { Bm25 } from './search.js';

// The Brain: shared memory that outlives runs. Agents write notes with
// "remember", read them with "recall", QA feedback becomes lessons, and every
// finished run leaves a summary. Relevant notes are handed to new tasks.
export class Brain {
  constructor(file, bus) {
    this.file = file;
    this.bus = bus;
    this.notes = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : [];
    this.reindex();
  }

  reindex() {
    this.index = new Bm25();
    for (const n of this.notes) this.index.add(n.id, [{ text: n.title, weight: 3 }, { text: n.text }, { text: (n.tags ?? []).join(' '), weight: 2 }, { text: n.team ?? '', weight: 1 }]);
  }

  save() {
    mkdirSync(dirname(this.file), { recursive: true });
    writeFileSync(this.file, JSON.stringify(this.notes, null, 1));
  }

  add({ title, text, tags = [], team = null, agentId = null, runId = null, kind = 'note' }) {
    const note = {
      id: randomUUID().slice(0, 8),
      ts: Date.now(),
      kind,
      title: String(title ?? '').slice(0, 160) || 'Nota',
      text: String(text ?? '').slice(0, 4000),
      tags: (Array.isArray(tags) ? tags : String(tags).split(',')).map((t) => String(t).trim()).filter(Boolean).slice(0, 8),
      team,
      agentId,
      runId,
    };
    this.notes.push(note);
    if (this.notes.length > 5000) this.notes.splice(0, this.notes.length - 5000);
    this.reindex();
    this.save();
    this.bus.emit('brain', { op: 'remember', agentId, count: this.notes.length, note });
    return note;
  }

  search(query, k = 5, { agentId = null, quiet = false } = {}) {
    const hits = this.index.search(query, k).map((h) => this.notes.find((n) => n.id === h.id)).filter(Boolean);
    if (!quiet) this.bus.emit('brain', { op: 'recall', agentId, count: this.notes.length, hits: hits.length });
    return hits;
  }

  list(limit = 200) {
    return this.notes.slice(-limit).reverse();
  }

  get count() {
    return this.notes.length;
  }
}
