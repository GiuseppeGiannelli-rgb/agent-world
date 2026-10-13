import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync } from 'node:fs';
import { mkdir, open, readdir, readFile, rename, rm } from 'node:fs/promises';
import { homedir } from 'node:os';
import { basename, dirname, join, relative, resolve, sep } from 'node:path';
import { Bm25 } from './search.js';

// '.incoming' holds default repos while they are being cloned (ensureRepos).
const SKIP = new Set(['node_modules', '.git', 'dist', 'build', '.next', '__pycache__', '.venv', 'venv', '.incoming']);
const MAX_FILES = 8000;

function git(args) {
  return new Promise((res, rej) => {
    const child = spawn('git', args, { windowsHide: true });
    let err = '';
    child.stderr.on('data', (d) => (err += d));
    child.on('error', rej);
    child.on('close', (code) => (code === 0 ? res() : rej(new Error(`git ha risposto ${code}: ${err.slice(-300)}`))));
  });
}

function expand(p, root) {
  if (p === '~' || p.startsWith('~/') || p.startsWith('~\\')) return join(homedir(), p.slice(2));
  return resolve(root, p);
}

function parseFrontmatter(text) {
  const m = text.match(/^﻿?---\r?\n([\s\S]*?)\r?\n---/);
  const meta = {};
  if (m) {
    let key = null;
    for (const line of m[1].split(/\r?\n/)) {
      const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
      if (kv) {
        key = kv[1];
        meta[key] = kv[2].replace(/^["']|["']$/g, '').trim();
      } else if (key && /^\s+\S/.test(line)) {
        meta[key] = `${meta[key]} ${line.trim()}`.trim();
      }
    }
  }
  const body = m ? text.slice(m[0].length) : text;
  return { meta, body };
}

async function head(file, bytes = 6000) {
  const fh = await open(file, 'r');
  try {
    const buf = Buffer.alloc(bytes);
    const { bytesRead } = await fh.read(buf, 0, bytes, 0);
    return buf.subarray(0, bytesRead).toString('utf8');
  } finally {
    await fh.close();
  }
}

// The Skill Hub: every SKILL.md found in the configured folders (Claude Code
// plugins, ~/.claude/skills, Codex, your own repos…) indexed for search.
// Workers get the best few for their task; anyone can search the rest.
export class SkillLibrary {
  constructor({ root, config, bus }) {
    this.root = root;
    this.config = config;
    this.bus = bus;
    this.skills = [];
    this.byId = new Map();
    this.index = new Bm25();
    this.indexing = null;
    this.vendorDir = join(root, 'skills', 'vendor');
  }

  get sources() {
    return (this.config.get().skills?.sources ?? ['skills']).map((s) => ({ label: s, dir: expand(s, this.root) }));
  }

  async walk(dir, out, depth = 0) {
    if (depth > 9 || out.length >= MAX_FILES) return;
    let entries;
    try {
      entries = await readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (SKIP.has(e.name)) continue;
      const full = join(dir, e.name);
      if (e.isDirectory()) await this.walk(full, out, depth + 1);
      else if (e.name.toLowerCase() === 'skill.md') out.push(full);
    }
  }

  reindex() {
    this.indexing ??= this.doIndex().finally(() => (this.indexing = null));
    return this.indexing;
  }

  async doIndex() {
    const skills = [];
    const seen = new Set();
    for (const src of this.sources) {
      if (!existsSync(src.dir)) continue;
      const files = [];
      await this.walk(src.dir, files);
      for (const file of files) {
        let text;
        try {
          text = await head(file);
        } catch {
          continue;
        }
        const { meta, body } = parseFrontmatter(text);
        const name = (meta.name || basename(dirname(file))).slice(0, 80);
        const description = (meta.description || body.replace(/^#.*$/m, '').trim().split(/\r?\n\r?\n/)[0] || '').slice(0, 600);
        const key = `${name}|${description.slice(0, 80)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const id = createHash('sha1').update(file).digest('hex').slice(0, 10);
        const headings = [...body.matchAll(/^#{1,3}\s+(.+)$/gm)].map((m) => m[1]).slice(0, 12).join(' ');
        skills.push({ id, name, description, source: src.label, path: file, rel: relative(src.dir, dirname(file)).split(sep).join('/') || name, headings });
      }
    }
    const index = new Bm25();
    for (const s of skills) index.add(s.id, [{ text: s.name.replace(/[-_]/g, ' '), weight: 4 }, { text: s.description, weight: 2 }, { text: s.headings }, { text: s.rel.replace(/[/_-]/g, ' ') }]);
    this.skills = skills;
    this.byId = new Map(skills.map((s) => [s.id, s]));
    this.index = index;
    this.bus.emit('skills', { count: skills.length });
    return skills.length;
  }

  find(idOrName) {
    if (this.byId.has(idOrName)) return this.byId.get(idOrName);
    const q = String(idOrName ?? '').toLowerCase();
    return this.skills.find((s) => s.name.toLowerCase() === q) ?? null;
  }

  search(query, k = 8) {
    return this.index.search(query, k).map((h) => ({ ...this.byId.get(h.id), score: Number(h.score.toFixed(2)) }));
  }

  async read(idOrName, max = 12000) {
    const s = this.find(idOrName);
    if (!s) throw new Error(`Skill not found: ${idOrName}`);
    const text = await readFile(s.path, 'utf8');
    return { skill: s, text: text.length > max ? `${text.slice(0, max)}\n… [truncated]` : text };
  }

  summary() {
    const bySource = {};
    for (const s of this.skills) bySource[s.source] = (bySource[s.source] ?? 0) + 1;
    return { count: this.skills.length, sources: this.sources.map((s) => ({ label: s.label, dir: s.dir, exists: existsSync(s.dir), count: bySource[s.label] ?? 0 })) };
  }

  // A new clone must not join an indexing pass that started before it.
  async refresh() {
    await this.indexing;
    return this.reindex();
  }

  // "https://github.com/owner/repo" -> its folder in skills/vendor, or null.
  repo(url) {
    const m = String(url ?? '').trim().match(/^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/);
    return m ? { slug: `${m[1]}/${m[2]}`, url: `https://github.com/${m[1]}/${m[2]}.git`, dir: join(this.vendorDir, `${m[1]}-${m[2]}`) } : null;
  }

  // Clones (or updates) a GitHub repository of skills into skills/vendor.
  async addRepo(url) {
    const repo = this.repo(url);
    if (!repo) throw new Error('Serve un indirizzo GitHub del tipo https://github.com/utente/repo');
    await mkdir(this.vendorDir, { recursive: true });
    await git(existsSync(repo.dir) ? ['-C', repo.dir, 'pull', '--ff-only'] : ['clone', '--depth', '1', repo.url, repo.dir]);
    const before = this.skills.length;
    await this.refresh();
    return { repo: repo.slug, path: repo.dir, added: this.skills.length - before, total: this.skills.length };
  }

  // The repos in skills.repos ship with the app: each missing one is cloned
  // once, into skills/vendor/.incoming first, so a clone cut short never looks
  // installed. Clones already there are left alone (the Skill tab updates them).
  // Never throws: without network the app starts with the skills it has.
  async ensureRepos() {
    const added = [];
    for (const url of this.config.get().skills?.repos ?? []) {
      const repo = this.repo(url);
      if (!repo) {
        console.warn(`Skill Hub    →  repo ignorata, non è un indirizzo GitHub: ${url}`);
        continue;
      }
      if (existsSync(repo.dir)) continue;
      const tmp = join(this.vendorDir, '.incoming', basename(repo.dir));
      try {
        await rm(tmp, { recursive: true, force: true });
        await mkdir(dirname(tmp), { recursive: true });
        await git(['clone', '--depth', '1', repo.url, tmp]);
        await rename(tmp, repo.dir);
        added.push(repo.slug);
      } catch (err) {
        await rm(tmp, { recursive: true, force: true }).catch(() => {});
        if (!existsSync(repo.dir)) console.warn(`Skill Hub    →  ${repo.slug} non scaricata: ${err.message.split('\n')[0]}`);
      }
    }
    if (added.length) await this.refresh();
    return added;
  }
}
