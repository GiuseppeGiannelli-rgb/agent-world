// scripts/secret-scan.js: what the commit hooks block and what they let through,
// in a throwaway git repo. The fake secrets are assembled at run time, so this file
// never contains one (the pre-commit hook scans it too).
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { ownedDir, removeDir } from './lib/temp.js';

const SCAN = join(dirname(fileURLToPath(import.meta.url)), 'secret-scan.js');
const repo = ownedDir('secrets');
let failures = 0;
const check = (name, ok, data = {}) => {
  if (!ok) failures++;
  console.log(`${ok ? 'ok ' : 'FAIL'} ${name}${ok ? '' : `  ${JSON.stringify(data)}`}`);
};
const git = (...args) => execFileSync('git', ['-c', 'core.hooksPath=', ...args], { cwd: repo, stdio: ['ignore', 'pipe', 'pipe'] }).toString();
const scan = (...args) => {
  const r = spawnSync(process.execPath, [SCAN, ...args], { cwd: repo, encoding: 'utf8' });
  return { code: r.status, out: `${r.stdout}${r.stderr}` };
};
const write = (rel, text) => {
  mkdirSync(dirname(join(repo, rel)), { recursive: true });
  writeFileSync(join(repo, rel), text);
};
// stage exactly these files, nothing else
const stageOnly = (files) => {
  git('rm', '--cached', '-r', '-q', '--ignore-unmatch', '.');
  for (const [rel, text] of Object.entries(files)) {
    write(rel, text);
    git('add', '-f', rel);
  }
};

const fakeKey = ['sk', 'ant', 'api03', 'Q'.repeat(40)].join('-');
const winPath = ['C:', 'Users', 'someone', 'project'].join('\\');
const realName = ['Zorblax', 'Quintavalle'];

try {
  git('init', '-q');
  git('config', 'user.name', realName.join(' '));
  git('config', 'user.email', `${realName[1].toLowerCase()}@example.invalid`);

  stageOnly({ 'README.md': '# Demo\nNo secrets here. Paths are relative: ../other-repo, ~/ComfyUI.\n' });
  let r = scan('--staged');
  check('a clean commit passes', r.code === 0 && /clean/.test(r.out), r);

  stageOnly({ 'src/client.js': `const key = '${fakeKey}';\n` });
  r = scan('--staged');
  check('an API key is blocked', r.code === 1 && /anthropic key/.test(r.out), r);
  check('the key is not printed in full', !r.out.includes(fakeKey), r);

  stageOnly({ '.env': 'PORT=4300\n' });
  r = scan('--staged');
  check('a .env file is blocked whatever it holds', r.code === 1 && /env file/.test(r.out), r);

  stageOnly({ '.env.example': 'PORT=4300\nANTHROPIC_API_KEY=\nOPENAI_API_KEY=${OPENAI_API_KEY}\n' });
  r = scan('--staged');
  check('.env.example with empty values passes', r.code === 0, r);

  stageOnly({ '.env.example': `PORT=4300\nMISTRAL_API_KEY=${'abc123XYZ'.repeat(3)}\n` });
  r = scan('--staged');
  check('.env.example with a real value is blocked', r.code === 1 && /assigned secret/.test(r.out), r);

  stageOnly({ 'app.js': 'const OPENAI_API_KEY = process.env.OPENAI_API_KEY;\nconst kind = "sk-short";\n' });
  r = scan('--staged');
  check('code that reads a key from the environment passes', r.code === 0, r);

  stageOnly({ 'docs/notes.md': `Run it from ${winPath}.\n` });
  r = scan('--staged');
  check('an absolute user path is blocked', r.code === 1 && /absolute windows user path/.test(r.out), r);

  stageOnly({ 'docs/retro.md': `Pushed by ${realName[1]} on Monday.\n` });
  r = scan('--staged');
  check('the name from git config is blocked', r.code === 1 && /personal word/.test(r.out), r);

  stageOnly({ 'config/local.json': '{}\n', 'data/runs/x.json': '{}\n' });
  r = scan('--staged');
  check('local config and runtime data are blocked', r.code === 1 && /local config/.test(r.out) && /runtime data/.test(r.out), r);

  // HANDOFF.md is tracked now (the progress notes on main): its name is no longer
  // blocked, but its content is scanned like every other file
  stageOnly({ 'HANDOFF.md': '# HANDOFF\nStatus: spec 08 done, PR open.\n' });
  r = scan('--staged');
  check('a clean HANDOFF.md passes', r.code === 0 && !/local notes/.test(r.out), r);
  stageOnly({ 'HANDOFF.md': `# HANDOFF\nkey ${fakeKey}\nfrom ${winPath}\nthanks ${realName[1]}\n` });
  r = scan('--staged');
  check('a key, a user path or a name in HANDOFF.md is still blocked', r.code === 1 && /HANDOFF\.md:2: anthropic key/.test(r.out) && /HANDOFF\.md:3: absolute windows user path/.test(r.out) && /HANDOFF\.md:4: personal word/.test(r.out) && !/local notes/.test(r.out), r);

  write('MSG_OK', 'fix: a plain message\n');
  write('MSG_BAD', `fix: thanks ${realName[0]}\n# ${realName[1]} in a comment line is ignored\n`);
  check('a clean commit message passes', scan('--message', join(repo, 'MSG_OK')).code === 0);
  r = scan('--message', join(repo, 'MSG_BAD'));
  check('a commit message with the name is blocked', r.code === 1 && /commit message:1: personal word/.test(r.out), r);

  // a leak that got past the hooks (--no-verify) is still found by the history scan
  stageOnly({ 'README.md': '# Demo\n', 'old.txt': `token ${fakeKey}\n` });
  git('commit', '-q', '-m', 'leak');
  rmSync(join(repo, 'old.txt'));
  git('rm', '-q', '--cached', 'old.txt');
  git('commit', '-q', '-m', 'remove it');
  r = scan('--history');
  check('the history scan finds a key that was removed later', r.code === 1 && /old\.txt:1 \(blob [0-9a-f]{7}\): anthropic key/.test(r.out), r);
  check('the history scan reports the personal identity', /2 commits: personal identity/.test(r.out), r);

  // .git/info/personal-words, when present, is the list: a pseudonymous identity
  // must not turn its common words into findings
  writeFileSync(join(repo, '.git', 'info', 'personal-words'), '# local\nmarmellatone\n');
  git('config', 'user.name', 'agent-world-dev');
  stageOnly({ 'docs/retro.md': 'A note about Marmellatone.\n' });
  r = scan('--staged');
  check('a word from .git/info/personal-words is blocked', r.code === 1 && /personal word/.test(r.out), r);
  stageOnly({ 'docs/agents.md': 'Every agent in the world has a desk.\n' });
  r = scan('--staged');
  check('with the file, the pseudonymous git name is not a personal word', r.code === 0, r);

  // a worktree has a git dir of its own (.git/worktrees/<name>), but the file lives in
  // the repository's common one: committing from a worktree reads the same list
  git('commit', '-q', '-m', 'agents');
  git('worktree', 'add', '-q', '-b', 'wt', 'wt');
  const wt = join(repo, 'wt');
  const inWt = (...args) => execFileSync('git', ['-c', 'core.hooksPath=', ...args], { cwd: wt, stdio: ['ignore', 'pipe', 'pipe'] });
  const scanWt = (...args) => {
    const s = spawnSync(process.execPath, [SCAN, ...args], { cwd: wt, encoding: 'utf8' });
    return { code: s.status, out: `${s.stdout}${s.stderr}` };
  };
  writeFileSync(join(wt, 'desk.md'), 'Every agent in the world has a desk.\n');
  inWt('add', 'desk.md');
  r = scanWt('--staged');
  check('in a worktree, the pseudonymous git name is not a personal word either', r.code === 0, r);
  writeFileSync(join(wt, 'retro.md'), 'A note about Marmellatone.\n');
  inWt('add', 'retro.md');
  r = scanWt('--staged');
  check('in a worktree, a word from the repository list is still blocked', r.code === 1 && /personal word/.test(r.out), r);
} finally {
  await removeDir(repo);
}

// The merges GitHub makes from its web UI ("Merge pull request #N from owner/branch"):
// GitHub commits, the account that clicked is the author, its name is in the subject.
// --history lets those three through in such a commit only; the PR title in its body,
// the files, and every commit that only looks like one are still scanned. A repo of its
// own, so the findings above do not mix in.
const gh = ownedDir('secrets');
let r;
try {
  const g = (env, ...args) => execFileSync('git', ['-c', 'core.hooksPath=', ...args], { cwd: gh, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, ...env } }).toString().trim();
  const scanGh = () => {
    const s = spawnSync(process.execPath, [SCAN, '--history'], { cwd: gh, encoding: 'utf8' });
    return { code: s.status, out: `${s.stdout}${s.stderr}` };
  };
  const me = { GIT_AUTHOR_NAME: 'agent-world-dev', GIT_AUTHOR_EMAIL: 'dev@agent-world.invalid', GIT_COMMITTER_NAME: 'agent-world-dev', GIT_COMMITTER_EMAIL: 'dev@agent-world.invalid' };
  const owner = 'Marmellatone-dev';
  const clicker = { GIT_AUTHOR_NAME: 'Marmellatone Rossi', GIT_AUTHOR_EMAIL: 'marmellatone@example.invalid' };
  const github = { ...clicker, GIT_COMMITTER_NAME: 'GitHub', GIT_COMMITTER_EMAIL: 'noreply@github.com' };
  g(me, 'init', '-q', '-b', 'main');
  writeFileSync(join(gh, '.git', 'info', 'personal-words'), 'marmellatone\n');
  writeFileSync(join(gh, 'a.md'), 'start\n');
  g(me, 'add', 'a.md');
  g(me, 'commit', '-q', '-m', 'start');
  // one feature branch per merge: a merge of an already merged branch would be refused
  const branch = (name, file, text) => {
    g(me, 'switch', '-q', '-c', name, 'main');
    writeFileSync(join(gh, file), text);
    g(me, 'add', file);
    g(me, 'commit', '-q', '-m', `add ${file}`);
    g(me, 'switch', '-q', 'main');
  };
  const merge = (env, name, msg) => {
    g(env, 'merge', '-q', '--no-ff', '-m', msg, name);
    return g(me, 'rev-parse', '--short=7', 'HEAD');
  };
  branch('feat/clean', 'clean.md', 'nothing personal\n');
  const clean = merge(github, 'feat/clean', `Merge pull request #7 from ${owner}/feat/clean\n\nAdd the clean page`);
  r = scanGh();
  check('a standard GitHub merge passes: the account in its subject, the clicker as author, GitHub as committer', r.code === 0, r);

  branch('feat/title', 'title.md', 'nothing personal\n');
  const titled = merge(github, 'feat/title', `Merge pull request #8 from ${owner}/feat/title\n\nNotes for Marmellatone`);
  branch('feat/file', 'leak.md', 'Marmellatone was here\n');
  merge(github, 'feat/file', `Merge pull request #9 from ${owner}/feat/file\n\nAdd a page`);
  branch('feat/local', 'local.md', 'nothing personal\n');
  const local = merge({ ...clicker, GIT_COMMITTER_NAME: 'Marmellatone Rossi', GIT_COMMITTER_EMAIL: 'marmellatone@example.invalid' }, 'feat/local', `Merge pull request #10 from ${owner}/feat/local`);
  writeFileSync(join(gh, 'single.md'), 'nothing personal\n');
  g(me, 'add', 'single.md');
  g(github, 'commit', '-q', '-m', `Merge pull request #11 from ${owner}/feat/single`);
  const single = g(me, 'rev-parse', '--short=7', 'HEAD');
  r = scanGh();
  const lines = r.out.split('\n');
  check('the PR title in the body of a GitHub merge is still scanned', lines.some((l) => l.startsWith(`commit ${titled} message: personal word`)), r);
  check('a file brought in by a GitHub merge is still scanned', lines.some((l) => l.startsWith('leak.md:1') && /personal word/.test(l)), r);
  check('a merge with that subject but not committed by GitHub is not exempt', lines.some((l) => l.startsWith(`commit ${local} message: personal word`)), r);
  check('a single-parent commit with that subject is not exempt', lines.some((l) => l.startsWith(`commit ${single} message: personal word`)), r);
  check('outside the standard merges the clicker is still a personal identity', lines.some((l) => /commits: personal identity in author\/committer \(Marm/.test(l)), r);
  check('the standard merges themselves stay out of the findings', !lines.some((l) => l.startsWith(`commit ${clean} `)), r);
} finally {
  await removeDir(gh);
}

console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
