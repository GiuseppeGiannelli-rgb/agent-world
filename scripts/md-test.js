// The small Markdown renderer of the UI (public/js/md.js): what the agents and the
// tools write (REPORT.md, blueprint.md with its tables, PARITY.md) must read as it
// is meant to in the file viewer, and nothing in it may become live HTML.
import assert from 'node:assert/strict';

const { markdown } = await import('../public/js/md.js');

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

// the shape tools.blueprint_markdown() writes for the data models and the endpoints
const BLUEPRINT = `## Endpoint

| Metodo | Percorso | Scopo | Accesso |
|---|---|---|---|
| GET | \`/api/todos\` |  |  |
| PATCH | \`/api/todos/{id}\` | cambia un todo |  |

## Regole di business

1. Una richiesta con dati non validi viene rifiutata.`;

check('a GFM table becomes a table: header cells, one row per line, inline code in the cells', () => {
  const html = markdown(BLUEPRINT);
  assert.match(html, /<table>/);
  assert.equal((html.match(/<th>/g) ?? []).length, 4);
  assert.equal((html.match(/<tr>/g) ?? []).length, 3);
  assert.match(html, /<td><code>\/api\/todos\/\{id\}<\/code><\/td><td>cambia un todo<\/td>/);
  assert.doesNotMatch(html, /\|---/);
});

check('the table ends where the table lines end: the heading and the list after it stay theirs', () => {
  const html = markdown(BLUEPRINT);
  assert.match(html, /<\/table>\n<h2>Regole di business<\/h2>\n<ol><li>/);
});

check('alignment colons and outer pipes are optional in the separator', () => {
  const html = markdown('a | b\n:---|---:\n1 | 2');
  assert.match(html, /<th>a<\/th><th>b<\/th>/);
  assert.match(html, /<td>1<\/td><td>2<\/td>/);
});

check('pipes without a separator line stay a paragraph', () => {
  const html = markdown('| not | a table |\nstill text');
  assert.doesNotMatch(html, /<table>/);
  assert.match(html, /<p>\| not \| a table \| still text<\/p>/);
});

check('a row shorter or longer than the header still has as many cells as the header', () => {
  const html = markdown('| a | b | c |\n|---|---|---|\n| 1 |\n| 1 | 2 | 3 | 4 |');
  const rows = html.match(/<tr>.*?<\/tr>/g);
  assert.equal(rows.length, 3);
  for (const r of rows.slice(1)) assert.equal((r.match(/<td>/g) ?? []).length, 3, r);
});

check('nothing in a cell becomes live HTML', () => {
  const html = markdown('| x |\n|---|\n| <img src=x onerror=alert(1)> |');
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

check('the constructs of before are unchanged', () => {
  assert.equal(markdown('# T\n\n- a\n- b\n\ntext **bold**'), '<h1>T</h1>\n<ul><li>a</li><li>b</li></ul>\n<p>text <strong>bold</strong></p>');
  assert.equal(markdown('```\n| a |\n|---|\n```'), '<pre><code>| a |\n|---|</code></pre>');
});

console.log(failures ? `${failures} FAILED` : 'ALL OK');
process.exit(failures ? 1 : 0);
