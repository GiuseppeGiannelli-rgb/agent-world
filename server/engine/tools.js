import { spawn } from 'node:child_process';
import { mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises';
import { dirname, join, relative, resolve, sep } from 'node:path';

const SKIP = new Set(['node_modules', '.git', '.next', 'dist', '__pycache__']);

// One shared folder per run. Every path an agent gives is resolved inside it.
export class Workspace {
  constructor(root) {
    this.root = resolve(root);
  }

  resolve(p = '.') {
    const clean = String(p ?? '.').trim().replace(/^[/\\]+/, '') || '.';
    const full = resolve(this.root, clean);
    if (full !== this.root && !full.startsWith(this.root + sep)) throw new Error(`Path outside the project folder: ${p}`);
    return full;
  }

  rel(full) {
    return relative(this.root, full).split(sep).join('/');
  }

  async ensure() {
    await mkdir(this.root, { recursive: true });
  }

  async list(p = '.', limit = 300) {
    const start = this.resolve(p);
    const out = [];
    const queue = [start];
    while (queue.length && out.length < limit) {
      const dir = queue.shift();
      let entries;
      try {
        entries = await readdir(dir, { withFileTypes: true });
      } catch {
        continue;
      }
      entries.sort((a, b) => a.name.localeCompare(b.name));
      for (const e of entries) {
        if (SKIP.has(e.name)) continue;
        const full = join(dir, e.name);
        if (e.isDirectory()) queue.push(full);
        else {
          const s = await stat(full).catch(() => null);
          out.push({ path: this.rel(full), size: s?.size ?? 0 });
        }
        if (out.length >= limit) break;
      }
    }
    return out;
  }

  async listText(p = '.') {
    const files = await this.list(p);
    return files.map((f) => `${f.path} (${f.size} B)`).join('\n');
  }

  async read(p, max = 12000) {
    const text = await readFile(this.resolve(p), 'utf8');
    return text.length > max ? `${text.slice(0, max)}\n… [truncated, ${text.length - max} more chars]` : text;
  }

  async write(p, content) {
    const full = this.resolve(p);
    await mkdir(dirname(full), { recursive: true });
    const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
    await writeFile(full, text, 'utf8');
    return { path: this.rel(full), bytes: Buffer.byteLength(text) };
  }

  async writeBytes(p, bytes) {
    const full = this.resolve(p);
    await mkdir(dirname(full), { recursive: true });
    await writeFile(full, bytes);
    return { path: this.rel(full), bytes: bytes.length };
  }

  async size(p) {
    try {
      const s = await stat(this.resolve(p));
      return s.isFile() ? s.size : -1;
    } catch {
      return -1;
    }
  }
}

export function runCommand(cmd, cwd, timeoutMs, signal) {
  return new Promise((resolvePromise) => {
    const child = spawn(cmd, { cwd, shell: true, windowsHide: true });
    let output = '';
    const take = (d) => {
      output += d.toString();
      if (output.length > 20000) output = output.slice(-20000);
    };
    child.stdout.on('data', take);
    child.stderr.on('data', take);
    const kill = () => {
      if (process.platform === 'win32') spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], { windowsHide: true });
      else child.kill('SIGKILL');
    };
    const timer = setTimeout(() => {
      output += `\n[killed after ${timeoutMs} ms]`;
      kill();
    }, timeoutMs);
    signal?.addEventListener('abort', kill, { once: true });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolvePromise({ code: code ?? -1, output: output.slice(-5000) });
    });
    child.on('error', (err) => {
      clearTimeout(timer);
      resolvePromise({ code: -1, output: err.message });
    });
  });
}
