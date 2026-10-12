// "Agent Reach": what agents can read on the internet without any key.
// web_search uses DuckDuckGo's HTML endpoint; web_fetch has readers for
// GitHub repositories, Reddit threads, Hacker News and plain pages.

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AgentWorld/0.2';

function timeout(signal, ms = 20000) {
  return signal ? AbortSignal.any([signal, AbortSignal.timeout(ms)]) : AbortSignal.timeout(ms);
}

const ENTITIES = { '&nbsp;': ' ', '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&#x27;': "'" };
const decode = (s) => s.replace(/&(nbsp|amp|lt|gt|quot|#39|#x27);/g, (m) => ENTITIES[m] ?? m);

export function htmlToText(html) {
  return decode(
    html
      .replace(/<(script|style|noscript|svg|nav|footer)[\s\S]*?<\/\1>/gi, ' ')
      .replace(/<br\s*\/?>|<\/(p|div|h[1-6]|li|tr|section|article)>/gi, '\n')
      .replace(/<[^>]+>/g, ' '),
  )
    .replace(/[ \t]+/g, ' ')
    .replace(/\n\s*\n+/g, '\n\n')
    .trim();
}

export async function webSearch(query, signal) {
  const q = String(query ?? '').trim();
  if (!q) throw new Error('Empty query');
  const res = await fetch(`https://html.duckduckgo.com/html/?q=${encodeURIComponent(q)}`, { headers: { 'user-agent': UA }, signal: timeout(signal) });
  const html = await res.text();
  const results = [];
  const re = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>[\s\S]*?(?:<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>)?/g;
  let m;
  while ((m = re.exec(html)) && results.length < 8) {
    let url = decode(m[1]);
    const uddg = url.match(/[?&]uddg=([^&]+)/);
    if (uddg) url = decodeURIComponent(uddg[1]);
    if (url.startsWith('//')) url = `https:${url}`;
    results.push({ title: htmlToText(m[2]), url, snippet: htmlToText(m[3] ?? '') });
  }
  if (!results.length) return `No results for "${q}".`;
  return results.map((r, i) => `${i + 1}. ${r.title}\n   ${r.url}\n   ${r.snippet}`).join('\n');
}

async function getJson(url, signal, headers = {}) {
  const res = await fetch(url, { headers: { 'user-agent': UA, ...headers }, signal: timeout(signal) });
  if (!res.ok) throw new Error(`HTTP ${res.status} from ${url}`);
  return res.json();
}

async function github(u, signal) {
  const [, owner, repo] = u.pathname.split('/');
  const meta = await getJson(`https://api.github.com/repos/${owner}/${repo}`, signal, { accept: 'application/vnd.github+json' });
  let readme = '';
  try {
    const r = await fetch(`https://api.github.com/repos/${owner}/${repo}/readme`, { headers: { 'user-agent': UA, accept: 'application/vnd.github.raw' }, signal: timeout(signal) });
    if (r.ok) readme = await r.text();
  } catch {
    // no readme
  }
  return `GitHub ${meta.full_name} · ★${meta.stargazers_count} · ${meta.language ?? ''} · updated ${meta.pushed_at}\n${meta.description ?? ''}\n\nREADME:\n${readme.slice(0, 9000)}`;
}

async function reddit(u, signal) {
  const data = await getJson(`https://www.reddit.com${u.pathname.replace(/\/$/, '')}.json?limit=20`, signal);
  const listing = Array.isArray(data) ? data : [data];
  const lines = [];
  for (const block of listing) {
    for (const c of block?.data?.children ?? []) {
      const d = c.data;
      if (d.title) lines.push(`# ${d.title} (▲${d.score})\n${(d.selftext ?? '').slice(0, 1500)}`);
      else if (d.body) lines.push(`- ${d.author} (▲${d.score}): ${d.body.slice(0, 500)}`);
    }
  }
  return lines.join('\n').slice(0, 9000) || 'Nothing readable.';
}

async function hackerNews(u, signal) {
  const id = u.searchParams.get('id');
  if (!id) {
    const top = await getJson('https://hacker-news.firebaseio.com/v0/topstories.json', signal);
    const items = await Promise.all(top.slice(0, 15).map((i) => getJson(`https://hacker-news.firebaseio.com/v0/item/${i}.json`, signal)));
    return items.map((it, i) => `${i + 1}. ${it.title} (${it.score} pts) ${it.url ?? ''}`).join('\n');
  }
  const it = await getJson(`https://hacker-news.firebaseio.com/v0/item/${id}.json`, signal);
  return `${it.title}\n${it.url ?? ''}\n${htmlToText(it.text ?? '')}`;
}

export async function webFetch(url, signal) {
  let u;
  try {
    u = new URL(url);
  } catch {
    throw new Error(`Invalid URL: ${url}`);
  }
  if (!/^https?:$/.test(u.protocol)) throw new Error('Only http and https URLs can be fetched');
  if (u.hostname === 'github.com' && u.pathname.split('/').filter(Boolean).length === 2) return github(u, signal);
  if (/(^|\.)reddit\.com$/.test(u.hostname)) return reddit(u, signal);
  if (u.hostname === 'news.ycombinator.com') return hackerNews(u, signal);
  const res = await fetch(u, { headers: { 'user-agent': UA }, signal: timeout(signal) });
  const type = res.headers.get('content-type') ?? '';
  const body = await res.text();
  const text = type.includes('html') ? htmlToText(body) : body;
  return `HTTP ${res.status} ${u.href}\n\n${text.slice(0, 8000)}`;
}
