// A probe for the hygiene phase of browser-test.js (spec 03, T1), and the shape of any
// probe: the browser comes from headless.js, never from a copy of its launch.
// Prints one JSON line once the browser answers, then waits:
// - "close" on stdin closes it normally; stdin closed (the runner gone) closes it too;
// - --emit SIGINT --after MS runs the Ctrl+C handler as a test, without a console.
import { close, launch } from './headless.js';

const arg = (name, fallback = null) => {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : fallback;
};

const browser = await launch();
await browser.connect();
console.log(JSON.stringify({ pid: process.pid, profile: browser.profile, swept: browser.swept }));
const done = async () => {
  await close(browser);
  process.exit(0);
};
process.stdin.on('data', (d) => String(d).includes('close') && done());
process.stdin.on('end', done);
if (arg('--emit')) setTimeout(() => process.emit(arg('--emit')), Number(arg('--after', 1500)));
