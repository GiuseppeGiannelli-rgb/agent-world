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
  writeFileSync(join(repo, '.git', 'info', 'personal-words'), '# local\nmarmellatone\n');

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

  stageOnly({ 'docs/retro.md': 'A note about Marmellatone.\n' });
  r = scan('--staged');
  check('a word from .git/info/personal-words is blocked', r.code === 1 && /personal word/.test(r.out), r);

  stageOnly({ 'config/local.json': '{}\n', 'data/runs/x.json': '{}\n' });
  r = scan('--staged');
  check('local config and runtime data are blocked', r.code === 1 && /local config/.test(r.out) && /runtime data/.test(r.out), r);

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
} finally {
  await removeDir(repo);
}

console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
