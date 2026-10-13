"""Mirrors server/engine/web.js ("Agent Reach"): what agents can read on the
internet without any key. web_search uses DuckDuckGo's HTML endpoint;
web_fetch has readers for GitHub repositories, Reddit threads, Hacker News
and plain pages.

Deviation: Node threads an AbortSignal into every fetch; the Python port
relies on httpx timeouts plus the run's gates between steps (run.py checks
the abort event before each tool call), so the functions take an optional
httpx.AsyncClient instead -- which also makes them testable offline."""

import asyncio
import re
from urllib.parse import quote, unquote, urlsplit

import httpx

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AgentWorld/0.2"
TIMEOUT_S = 20

_BLOCK_RE = re.compile(r"<(script|style|noscript|svg|nav|footer)[\s\S]*?</\1>", re.IGNORECASE)
_BREAK_RE = re.compile(r"<br\s*/?>|</(p|div|h[1-6]|li|tr|section|article)>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&(nbsp|amp|lt|gt|quot|#39|#x27);")
_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&#x27;": "'"}

_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>[\s\S]*?(?:<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)</a>)?'
)
_UDDG_RE = re.compile(r"[?&]uddg=([^&]+)")


def html_to_text(html: str) -> str:
    text = _BLOCK_RE.sub(" ", html)
    text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = _ENTITY_RE.sub(lambda m: _ENTITIES.get(m.group(0), m.group(0)), text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _client(client) -> tuple[httpx.AsyncClient, bool]:
    return (client, False) if client is not None else (httpx.AsyncClient(timeout=TIMEOUT_S, headers={"user-agent": UA}), True)


async def web_search(query: str, *, client=None) -> str:
    q = str(query or "").strip()
    if not q:
        raise ValueError("Empty query")
    c, own = _client(client)
    try:
        res = await c.get(f"https://html.duckduckgo.com/html/?q={quote(q)}")
        html = res.text
    finally:
        if own:
            await c.aclose()
    results = []
    for m in _RESULT_RE.finditer(html):
        if len(results) >= 8:
            break
        url = _ENTITY_RE.sub(lambda mm: _ENTITIES.get(mm.group(0), mm.group(0)), m.group(1))
        uddg = _UDDG_RE.search(url)
        if uddg:
            url = unquote(uddg.group(1))
        if url.startswith("//"):
            url = f"https:{url}"
        results.append({"title": html_to_text(m.group(2)), "url": url, "snippet": html_to_text(m.group(3) or "")})
    if not results:
        return f'No results for "{q}".'
    return "\n".join(f"{i + 1}. {r['title']}\n   {r['url']}\n   {r['snippet']}" for i, r in enumerate(results))


async def _get_json(c: httpx.AsyncClient, url: str, headers: dict | None = None):
    res = await c.get(url, headers=headers or {})
    if res.status_code >= 400:
        raise Exception(f"HTTP {res.status_code} from {url}")
    return res.json()


async def _github(c: httpx.AsyncClient, u) -> str:
    parts = u.path.split("/")
    owner, repo = parts[1], parts[2]
    meta = await _get_json(c, f"https://api.github.com/repos/{owner}/{repo}", {"accept": "application/vnd.github+json"})
    readme = ""
    try:
        r = await c.get(f"https://api.github.com/repos/{owner}/{repo}/readme", headers={"accept": "application/vnd.github.raw"})
        if r.status_code < 400:
            readme = r.text
    except httpx.HTTPError:
        pass  # no readme
    return f"GitHub {meta['full_name']} · ★{meta['stargazers_count']} · {meta.get('language') or ''} · updated {meta['pushed_at']}\n{meta.get('description') or ''}\n\nREADME:\n{readme[:9000]}"


async def _reddit(c: httpx.AsyncClient, u) -> str:
    data = await _get_json(c, f"https://www.reddit.com{u.path.rstrip('/')}.json?limit=20")
    listing = data if isinstance(data, list) else [data]
    lines = []
    for block in listing:
        for child in ((block or {}).get("data", {}).get("children") or []):
            d = child.get("data", {})
            if d.get("title"):
                lines.append(f"# {d['title']} (▲{d['score']})\n{(d.get('selftext') or '')[:1500]}")
            elif d.get("body"):
                lines.append(f"- {d['author']} (▲{d['score']}): {d['body'][:500]}")
    return "\n".join(lines)[:9000] or "Nothing readable."


async def _hacker_news(c: httpx.AsyncClient, u) -> str:
    from urllib.parse import parse_qs

    ids = parse_qs(u.query).get("id")
    if not ids:
        top = await _get_json(c, "https://hacker-news.firebaseio.com/v0/topstories.json")
        items = await asyncio.gather(*(_get_json(c, f"https://hacker-news.firebaseio.com/v0/item/{i}.json") for i in top[:15]))
        return "\n".join(f"{i + 1}. {it['title']} ({it['score']} pts) {it.get('url') or ''}" for i, it in enumerate(items))
    it = await _get_json(c, f"https://hacker-news.firebaseio.com/v0/item/{ids[0]}.json")
    return f"{it['title']}\n{it.get('url') or ''}\n{html_to_text(it.get('text') or '')}"


async def web_fetch(url: str, *, client=None) -> str:
    try:
        u = urlsplit(str(url))
        if not u.scheme or not u.netloc:
            raise ValueError
    except ValueError:
        raise ValueError(f"Invalid URL: {url}") from None
    if u.scheme not in ("http", "https"):
        raise ValueError("Only http and https URLs can be fetched")
    c, own = _client(client)
    try:
        segments = [s for s in u.path.split("/") if s]
        if u.hostname == "github.com" and len(segments) == 2:
            return await _github(c, u)
        if u.hostname and re.search(r"(^|\.)reddit\.com$", u.hostname):
            return await _reddit(c, u)
        if u.hostname == "news.ycombinator.com":
            return await _hacker_news(c, u)
        res = await c.get(str(url))
        type_ = res.headers.get("content-type", "")
        text = html_to_text(res.text) if "html" in type_ else res.text
        return f"HTTP {res.status_code} {url}\n\n{text[:8000]}"
    finally:
        if own:
            await c.aclose()
