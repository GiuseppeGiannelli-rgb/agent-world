"""Contract tests for backend/web.py ("Agent Reach"), ported from
server/engine/web.js. Network is exercised through httpx.MockTransport, so
no test touches the real internet."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Spec 07: web_fetch resolves a name before it connects (no SSRF). The
    names of these tests are public: they resolve to a public address
    without asking any DNS server."""
    import backend.web as web

    async def resolve(host, port):
        return ["93.184.216.34"]

    monkeypatch.setattr(web, "_resolve", resolve)


def client_returning(routes: dict):
    """routes: url substring -> httpx.Response (or list of them, consumed in order).
    A plain page is fetched at its checked address, so the name is in Host."""

    def handler(request: httpx.Request) -> httpx.Response:
        target = f"{request.headers.get('host', '')}{request.url.raw_path.decode()} {request.url}"
        for key, value in routes.items():
            if key in target:
                if isinstance(value, list):
                    return value.pop(0)
                return value
        return httpx.Response(404, text="not found")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestHtmlToText:
    def test_strips_scripts_and_styles(self):
        from backend.web import html_to_text

        # script/style become a single space each (not newlines), so the two
        # paragraphs end up separated by "\n " -- exactly as Node produces.
        assert html_to_text("<p>ok</p><script>var x=1;</script><style>a{}</style><p>fine</p>") == "ok\n fine"

    def test_br_and_blocks_become_newlines(self):
        from backend.web import html_to_text

        # "<div>" becomes a space (tag strip), so the space before "c" stays:
        # traced against Node's htmlToText, which produces the same string.
        assert html_to_text("a<br>b</p><div>c</div>") == "a\nb\n c"

    def test_entities_are_decoded(self):
        from backend.web import html_to_text

        assert html_to_text("a &amp; b &lt;tag&gt; &#39;q&#39;") == "a & b <tag> 'q'"

    def test_whitespace_collapses(self):
        from backend.web import html_to_text

        # the space before the newline run survives: Node's /\n\s*\n+/ cannot
        # start on a space, and this matches its output exactly.
        assert html_to_text("  a   b \n\n\n\nc  ") == "a b \n\nc"


DDG_HTML = """
<a class="result__a" href="https://example.com/one">Primo &amp; risultato</a><a class="result__snippet">Snippet <b>uno</b></a>
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ftwo&amp;rut=abc">Secondo</a>
<a class="result__snippet">Snippet due</a>
"""


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_parses_results_and_decodes_uddg(self):
        from backend.web import web_search

        client = client_returning({"duckduckgo.com": httpx.Response(200, text=DDG_HTML)})
        out = await web_search("test query", client=client)
        lines = out.split("\n")
        assert lines[0] == "1. Primo & risultato"
        assert lines[1] == "   https://example.com/one"
        assert lines[2] == "   Snippet uno"
        assert lines[3] == "2. Secondo"
        assert lines[4] == "   https://example.com/two"
        # Node quirk, kept for parity: the lazy [\s\S]*? plus the optional
        # snippet group captures a snippet only when it is adjacent to the
        # result anchor -- on the next line it is skipped, as here.
        assert lines[5] == "   "

    @pytest.mark.asyncio
    async def test_empty_query_raises(self):
        from backend.web import web_search

        with pytest.raises(ValueError, match="Empty query"):
            await web_search("   ")

    @pytest.mark.asyncio
    async def test_no_results_message(self):
        from backend.web import web_search

        client = client_returning({"duckduckgo.com": httpx.Response(200, text="<html>niente</html>")})
        assert await web_search("qualcosa", client=client) == 'No results for "qualcosa".'


class TestWebFetch:
    @pytest.mark.asyncio
    async def test_invalid_url_and_scheme(self):
        from backend.web import web_fetch

        with pytest.raises(ValueError, match="Invalid URL"):
            await web_fetch("not a url")
        with pytest.raises(ValueError, match="Only http and https"):
            await web_fetch("ftp://example.com/x")

    @pytest.mark.asyncio
    async def test_plain_html_page_is_converted(self):
        from backend.web import web_fetch

        client = client_returning({"example.com": httpx.Response(200, text="<html><body><p>Ciao mondo</p><script>x()</script></body></html>", headers={"content-type": "text/html"})})
        out = await web_fetch("https://example.com/page", client=client)
        assert out.startswith("HTTP 200 https://example.com/page")
        assert "Ciao mondo" in out and "x()" not in out

    @pytest.mark.asyncio
    async def test_non_html_passes_through_raw(self):
        from backend.web import web_fetch

        client = client_returning({"example.com": httpx.Response(200, text='{"a": 1}', headers={"content-type": "application/json"})})
        out = await web_fetch("https://example.com/data.json", client=client)
        assert '{"a": 1}' in out

    @pytest.mark.asyncio
    async def test_github_repo_reader(self):
        from backend.web import web_fetch

        meta = httpx.Response(200, json={"full_name": "o/r", "stargazers_count": 42, "language": "Python", "pushed_at": "2026-01-01", "description": "Una repo"})
        readme = httpx.Response(200, text="# Titolo\n\nTesto del readme.")
        client = client_returning({"api.github.com/repos/o/r/readme": readme, "api.github.com/repos/o/r": meta})
        out = await web_fetch("https://github.com/o/r", client=client)
        assert out.startswith("GitHub o/r · ★42 · Python · updated 2026-01-01")
        assert "Una repo" in out and "Testo del readme." in out

    @pytest.mark.asyncio
    async def test_hackernews_item(self):
        from backend.web import web_fetch

        item = httpx.Response(200, json={"title": "Show HN", "url": "https://x.dev", "text": "<p>bello</p>"})
        client = client_returning({"hacker-news.firebaseio.com": item})
        out = await web_fetch("https://news.ycombinator.com/item?id=123", client=client)
        assert out == "Show HN\nhttps://x.dev\nbello"

    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        from backend.web import web_fetch

        client = client_returning({"api.github.com": httpx.Response(500, text="boom")})
        with pytest.raises(Exception, match="HTTP 500"):
            await web_fetch("https://github.com/o/r", client=client)
