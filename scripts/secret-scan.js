// Keeps secrets and personal data out of git.
//
//   node scripts/secret-scan.js --staged        what `git commit` is about to record (pre-commit hook)
//   node scripts/secret-scan.js --message FILE  a commit message (commit-msg hook)
//   node scripts/secret-scan.js --history       every blob reachable from any ref, every commit
//                                               message and every author/committer identity
//
// Exits 1 and prints "where: rule" lines when something is found. Matches are
// never printed in full: a scan log must not leak what it found.
//
// Personal words (real name, e-mail) are never written in this repo. They come
// from the untracked file .git/info/personal-words (one word per line) when it
// exists; otherwise from `git config user.name` / `user.email`, which protects a
// fresh clone. The file wins so that a pseudonymous identity ("agent-world-dev")
// does not turn common words into findings.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const SECRET_RULES = [
  ['anthropic key', /sk-ant-[A-Za-z0-9_-]{20,}/],
  ['openrouter key', /sk-or-v1-[a-f0-9]{32,}/],
  ['openai key', /sk-(?:proj-)?[A-Za-z0-9_-]{32,}/],
  ['groq key', /gsk_[A-Za-z0-9]{20,}/],
  ['cerebras key', /csk-[a-z0-9]{20,}/],
  ['google key', /AIza[0-9A-Za-z_-]{35}|AQ\.[A-Za-z0-9_-]{20,}/],
  ['elevenlabs key', /sk_[a-f0-9]{40,}/],
  ['github token', /(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}/],
  ['slack token', /xox[abpr]-[A-Za-z0-9-]{10,}/],
  ['aws key id', /AKIA[0-9A-Z]{16}/],
  ['private key', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['bearer token', /Bearer\s+[A-Za-z0-9_\-.]{24,}/],
  // NAME=value in env style, with a real value (not empty, not a ${reference})
  ['assigned secret', /^[ \t]*(?:export[ \t]+)?[A-Z][A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|_KEY)[ \t]*=[ \t]*(?!\$)[^\s#]{8,}/m],
];
const PATH_RULES = [
  ['absolute windows user path', /\b[A-Za-z]:(?:\\{1,2}|\/)Users(?:\\{1,2}|\/)[A-Za-z0-9._-]+/],
  ['absolute msys user path', /\/[a-z]\/Users\/[A-Za-z0-9._-]+/],
  ['absolute unix home path', /(?<![\w.~])\/(?:Users|home)\/[A-Za-z][A-Za-z0-9._-]*\//],
];
// Files that must never be tracked, whatever they contain.
const FORBIDDEN_FILES = [
  [/(^|\/)\.env(\.(?!example$)[^/]*)?$/, 'env file'],
  [/(^|\/)config\/(local|[^/]*\.local)\.json$/, 'local config'],
  [/\.(pem|key|p12|pfx|keystore)$/i, 'key file'],
  [/(^|\/)id_(rsa|ed25519)/, 'ssh key'],
  [/(^|\/)(data|workspace)\//, 'runtime data'],
  // HANDOFF.md is no longer here: it is tracked on main as the progress notes. Its
  // content is scanned like every other file (keys, user paths, personal words).
];

const git = (args, opts = {}) => execFileSync('git', args, { maxBuffer: 256 * 1024 * 1024, ...opts });
const gitText = (args, opts) => git(args, opts).toString('utf8');

export function personalWords(root = process.cwd()) {
  const words = new Set();
  const add = (w) => {
    w = String(w ?? '').trim().toLowerCase();
    if (w.length >= 4 && !/^(noreply|users|github|example|claude|test|user)$/.test(w)) words.add(w);
  };
  // the common dir: a worktree's own git dir (.git/worktrees/<name>, an absolute path,
  // which join() would glue after root) has no info/ of its own
  const file = join(resolve(root, gitText(['-C', root, 'rev-parse', '--git-common-dir']).trim()), 'info', 'personal-words');
  if (existsSync(file)) {
    for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) if (line.trim() && !line.startsWith('#')) add(line);
    return [...words];
  }
  for (const key of ['user.name', 'user.email']) {
    let v = '';
    try {
      v = gitText(['-C', root, 'config', key]).trim();
    } catch {
      continue; // not set
    }
    if (key === 'user.email') v = v.split('@')[0];
    for (const part of v.split(/[^\p{L}\p{N}]+/u)) add(part);
    if (key === 'user.email') add(v.replace(/[^\p{L}\p{N}]/gu, ''));
  }
  return [...words];
}

const redact = (s) => (s.length <= 8 ? `${s.slice(0, 2)}…` : `${s.slice(0, 4)}…(${s.length} chars)`);

// Findings for one text: [{ rule, line, sample }]; samples are redacted.
export function scanText(text, words = []) {
  const found = [];
  const lineOf = (i) => text.slice(0, i).split('\n').length;
  for (const [rule, rx] of [...SECRET_RULES, ...PATH_RULES]) {
    const g = new RegExp(rx.source, rx.flags.includes('g') ? rx.flags : `${rx.flags}g`);
    for (const m of text.matchAll(g)) found.push({ rule, line: lineOf(m.index), sample: redact(m[0].trim()) });
  }
  const lower = text.toLowerCase();
  for (const w of words) {
    for (let i = lower.indexOf(w); i >= 0; i = lower.indexOf(w, i + 1)) found.push({ rule: 'personal word', line: lineOf(i), sample: redact(w) });
  }
  return found;
}

export function scanPath(path) {
  const p = path.replace(/\\/g, '/');
  if (p.endsWith('.env.example')) return null;
  return FORBIDDEN_FILES.find(([rx]) => rx.test(p))?.[1] ?? null;
}

const isBinary = (buf) => buf.subarray(0, 8000).includes(0);

function report(findings) {
  for (const f of findings) console.log(`${f.where}: ${f.rule}${f.sample ? ` (${f.sample})` : ''}`);
  return findings.length ? 1 : 0;
}

function staged() {
  const words = personalWords();
  const out = [];
  const files = gitText(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']).split('\0').filter(Boolean);
  for (const file of files) {
    const why = scanPath(file);
    if (why) out.push({ where: file, rule: `${why} must not be committed` });
    const buf = git(['show', `:${file}`]);
    if (isBinary(buf)) continue;
    for (const f of scanText(buf.toString('utf8'), words)) out.push({ where: `${file}:${f.line}`, rule: f.rule, sample: f.sample });
  }
  return out;
}

function message(file) {
  const text = readFileSync(file, 'utf8').split(/\r?\n/).filter((l) => !l.startsWith('#')).join('\n');
  return scanText(text, personalWords()).map((f) => ({ where: `commit message:${f.line}`, rule: f.rule, sample: f.sample }));
}

// A merge made from GitHub's web UI: two parents, GitHub as committer, the subject
// "Merge pull request #N from <account>/<branch>". The account that clicked is its
// author, and the account name is in the subject. The user chose (2026-10-18) not to
// rewrite those merges, so --history lets that account name and the identity through
// in such a commit only. Its body (the PR title), its files and every other commit are
// scanned as before; the commit hooks have no exception, so a message like that typed
// locally is still blocked when it is committed.
const GITHUB_MERGE = /^Merge pull request #\d+ from ([A-Za-z0-9][A-Za-z0-9-]{0,38})\/\S+$/;
const GITHUB_COMMITTER = 'GitHub <noreply@github.com>';
export function githubMergeSubject({ parents, committer, body }) {
  const [subject, ...rest] = (body ?? '').split('\n');
  const m = parents === 2 && committer === GITHUB_COMMITTER ? subject.match(GITHUB_MERGE) : null;
  return m ? [subject.replace(m[1], '<account>'), ...rest].join('\n') : null;
}

function history() {
  const words = personalWords();
  const out = [];
  const paths = new Map(); // blob -> first path seen
  for (const line of gitText(['rev-list', '--objects', '--all']).split('\n')) {
    const [sha, ...rest] = line.split(' ');
    const p = rest.join(' ');
    if (!sha || !p) continue;
    const why = scanPath(p);
    if (why) out.push({ where: p, rule: `${why} in history` });
    if (!paths.has(sha)) paths.set(sha, p);
  }
  const types = gitText(['cat-file', '--batch-check=%(objectname) %(objecttype)'], { input: [...paths.keys()].join('\n') });
  const blobs = new Set(types.split('\n').filter((l) => l.endsWith(' blob')).map((l) => l.split(' ')[0]));
  for (const [sha, p] of paths) {
    if (!blobs.has(sha)) continue;
    const buf = git(['cat-file', '-p', sha]);
    if (isBinary(buf)) continue;
    for (const f of scanText(buf.toString('utf8'), words)) out.push({ where: `${p}:${f.line} (blob ${sha.slice(0, 7)})`, rule: f.rule, sample: f.sample });
  }
  const log = gitText(['log', '--all', '--format=%H%x00%P%x00%an <%ae>%x00%cn <%ce>%x00%B%x01']);
  const identities = new Map();
  for (const entry of log.split('\x01')) {
    const [h, parents, author, committer, body] = entry.replace(/^\n/, '').split('\x00');
    if (!h) continue;
    const merge = githubMergeSubject({ parents: parents.split(' ').filter(Boolean).length, committer, body });
    for (const f of scanText(merge ?? body ?? '', words)) out.push({ where: `commit ${h.slice(0, 7)} message`, rule: f.rule, sample: f.sample });
    if (merge !== null) continue; // a GitHub merge: its author is the account that clicked
    for (const id of new Set([author, committer])) {
      if (scanText(id ?? '', words).length) identities.set(id, (identities.get(id) ?? 0) + 1);
    }
  }
  for (const [id, n] of identities) out.push({ where: `${n} commits`, rule: 'personal identity in author/committer', sample: redact(id) });
  return out;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [mode, arg] = process.argv.slice(2);
  let findings;
  if (mode === '--staged') findings = staged();
  else if (mode === '--message') findings = message(arg);
  else if (mode === '--history') findings = history();
  else {
    console.error('usage: node scripts/secret-scan.js --staged | --message FILE | --history');
    process.exit(2);
  }
  const code = report(findings);
  if (code) console.log(`\nsecret-scan: ${findings.length} finding(s). Remove them (or move the value to .env) before committing.`);
  else console.log('secret-scan: clean');
  process.exit(code);
}
