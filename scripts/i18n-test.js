// Spec 06: the UI dictionaries stay in lockstep. Every language of LANGS has the
// English keys (Italian minus the team.* labels, D3) and the same {placeholders}, is
// really translated, and has a voice locale; index.html carries the English words of
// the dictionary, so the first paint before main.js matches the default language.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
globalThis.document = { documentElement: {} }; // setLang() sets <html lang>
const { DEFAULT_LANG, LANGS, dictionaries, locale, setLang } = await import('../public/js/i18n.js');

let failures = 0;
const check = (name, fn) => {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (err) {
    failures++;
    console.log(`FAIL ${name}\n     ${err.message.split('\n').join('\n     ')}`);
  }
};

const d = dictionaries();
const en = d[DEFAULT_LANG];
const fields = (s) => [...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const expected = (lang) => Object.keys(en).filter((k) => lang !== 'it' || !k.startsWith('team.') || k === 'team.ceo');

check('English first and default, five languages', () => {
  assert.equal(DEFAULT_LANG, 'en');
  assert.deepEqual(Object.keys(LANGS), ['en', 'it', 'es', 'fr', 'de']);
  assert.deepEqual(Object.keys(d).sort(), Object.keys(LANGS).sort());
});

for (const lang of Object.keys(LANGS)) {
  check(`${lang}: the English keys, no more, no less`, () => {
    const keys = new Set(Object.keys(d[lang]));
    const want = expected(lang);
    assert.deepEqual(want.filter((k) => !keys.has(k)), [], 'missing');
    assert.deepEqual([...keys].filter((k) => !want.includes(k)), [], 'extra');
  });
  check(`${lang}: the same placeholders as English`, () => {
    const bad = expected(lang).filter((k) => typeof en[k] === 'string' && fields(d[lang][k]).join() !== fields(en[k]).join());
    assert.deepEqual(bad, []);
    assert.equal(d[lang].examples.length, en.examples.length, 'examples');
  });
  check(`${lang}: a voice and date locale of its own`, () => {
    setLang(lang);
    assert.match(locale(), new RegExp(`^${lang}-[A-Z]{2}$`));
    assert.equal(document.documentElement.lang, lang);
  });
}

for (const lang of Object.keys(LANGS).filter((l) => l !== DEFAULT_LANG)) {
  // a copy of English would pass the key check; Brain, Router, Chat… are the same word
  check(`${lang}: really translated (at most 15% of the texts equal to English)`, () => {
    const same = Object.keys(en).filter((k) => typeof en[k] === 'string' && d[lang][k] === en[k]);
    assert.ok(same.length <= 0.15 * Object.keys(en).length, `${same.length}: ${same.join(', ')}`);
  });
}

check('an unknown language falls back to English', () => {
  assert.equal(setLang('xx'), 'en');
});

check('index.html carries the English words of the dictionary', () => {
  const html = readFileSync(join(ROOT, 'public', 'index.html'), 'utf8');
  assert.match(html, /<html lang="en">/);
  const wrong = [];
  for (const m of html.matchAll(/data-i18n="([^"]+)">([^<]*)</g)) if (en[m[1]] !== m[2]) wrong.push(`${m[1]}: "${m[2]}"`);
  for (const m of html.matchAll(/(title|placeholder)="([^"]*)" data-i18n-(title|placeholder)="([^"]+)"/g)) if (en[m[4]] !== m[2].replace(/&#39;/g, "'")) wrong.push(`${m[4]}: "${m[2]}"`);
  assert.deepEqual(wrong, []);
  assert.match(html, />Start the company</, 'the start button');
});

console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
