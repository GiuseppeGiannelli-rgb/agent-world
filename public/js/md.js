// Small, safe Markdown renderer: everything is escaped first, then a few
// constructs (headings, lists, tables, code, emphasis, links) are turned into HTML.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function inline(text) {
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

// a GFM table: a row of cells, then a separator row with as many cells (|---|:--:|)
const SEPARATOR = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
const cells = (row) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

export function markdown(src) {
  const lines = esc(src).split(/\r?\n/);
  const out = [];
  let list = null;
  let para = [];
  let code = null;
  const flushPara = () => {
    if (para.length) out.push(`<p>${inline(para.join(' '))}</p>`);
    para = [];
  };
  const flushList = () => {
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`);
    list = null;
  };
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n];
    if (code) {
      if (/^```/.test(line)) {
        out.push(`<pre><code>${code.join('\n')}</code></pre>`);
        code = null;
      } else code.push(line);
      continue;
    }
    if (/^```/.test(line)) {
      flushPara();
      flushList();
      code = [];
      continue;
    }
    const next = lines[n + 1];
    if (line.includes('|') && next !== undefined && SEPARATOR.test(next) && cells(next).length === cells(line).length) {
      flushPara();
      flushList();
      const head = cells(line);
      const rows = [];
      for (n += 2; n < lines.length && lines[n].trim() && lines[n].includes('|') && !/^```/.test(lines[n]); n++) rows.push(cells(lines[n]));
      n--;
      const row = (r, tag) => `<tr>${head.map((_, k) => `<${tag}>${inline(r[k] ?? '')}</${tag}>`).join('')}</tr>`;
      out.push(`<table><thead>${row(head, 'th')}</thead><tbody>${rows.map((r) => row(r, 'td')).join('')}</tbody></table>`);
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      flushPara();
      flushList();
      const level = Math.min(3, h[1].length);
      out.push(`<h${level}>${inline(h[2])}</h${level}>`);
      continue;
    }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const tag = ul ? 'ul' : 'ol';
      if (list && list.tag !== tag) flushList();
      if (!list) list = { tag, items: [] };
      list.items.push((ul ?? ol)[1]);
      continue;
    }
    if (/^&gt;\s?/.test(line)) {
      flushPara();
      flushList();
      out.push(`<blockquote>${inline(line.replace(/^&gt;\s?/, ''))}</blockquote>`);
      continue;
    }
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }
    flushList();
    para.push(line.trim());
  }
  if (code) out.push(`<pre><code>${code.join('\n')}</code></pre>`);
  flushPara();
  flushList();
  return out.join('\n');
}
