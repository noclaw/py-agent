"""Web tools: HTML→text, web_fetch over httpx.MockTransport, web_search DDG parsing."""

from __future__ import annotations

import httpx
import pytest

from agent.permissions import Permissions
from agent.tools.web import (
    WebFetchArgs,
    WebFetchTool,
    WebSearchArgs,
    WebSearchTool,
    _decode_ddg_href,
    html_to_text,
)


def _transport(body, *, status=200, ctype="text/html"):
    data = body.encode() if isinstance(body, str) else body

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=data, headers={"content-type": ctype})

    return httpx.MockTransport(handler)


# --- HTML -> text -----------------------------------------------------------

_HTML = """
<html><head><style>.x{}</style><title>t</title></head>
<body>
  <h1>Main Title</h1>
  <p>Hello <b>world</b>, this is text.</p>
  <script>doEvil()</script>
  <ul><li>first</li><li>second</li></ul>
</body></html>
"""


def test_html_to_text_structure_and_skips():
    text = html_to_text(_HTML)
    assert "# Main Title" in text
    assert "Hello world, this is text." in text
    assert "- first" in text and "- second" in text
    assert "doEvil" not in text and ".x{}" not in text  # script/style dropped


# --- web_fetch --------------------------------------------------------------


async def _fetch(tool, url):
    return await tool.execute(WebFetchArgs(url=url))


@pytest.mark.asyncio
async def test_web_fetch_html_returns_readable_text():
    tool = WebFetchTool(transport=_transport(_HTML))
    res = await _fetch(tool, "https://example.com/page")
    assert not res.is_error
    assert res.content.startswith("# https://example.com/page")
    assert "# Main Title" in res.content and "doEvil" not in res.content


@pytest.mark.asyncio
async def test_web_fetch_plaintext_passthrough():
    tool = WebFetchTool(transport=_transport("just some text", ctype="text/plain"))
    res = await _fetch(tool, "https://example.com/raw.txt")
    assert "just some text" in res.content and not res.is_error


@pytest.mark.asyncio
async def test_web_fetch_http_error():
    tool = WebFetchTool(transport=_transport("nope", status=404))
    res = await _fetch(tool, "https://example.com/missing")
    assert res.is_error and "404" in res.content


@pytest.mark.asyncio
async def test_web_fetch_rejects_non_http_scheme():
    res = await _fetch(WebFetchTool(), "file:///etc/passwd")
    assert res.is_error and "http(s)" in res.content


# --- web_search -------------------------------------------------------------


def test_decode_ddg_href():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert _decode_ddg_href(href) == "https://example.com/page"
    assert _decode_ddg_href("https://plain.example/x") == "https://plain.example/x"


_DDG = """
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=1">First Result</a>
  <a class="result__snippet" href="#">Snippet for the first result.</a>
</div>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fb&rut=2">Second Result</a>
  <a class="result__snippet" href="#">Second snippet.</a>
</div>
"""


@pytest.mark.asyncio
async def test_web_search_parses_results():
    tool = WebSearchTool(transport=_transport(_DDG))
    res = await tool.execute(WebSearchArgs(query="example", max_results=5))
    assert not res.is_error
    assert "First Result" in res.content and "https://example.com/a" in res.content
    assert "Snippet for the first result." in res.content
    assert "Second Result" in res.content


@pytest.mark.asyncio
async def test_web_search_respects_max_results():
    tool = WebSearchTool(transport=_transport(_DDG))
    res = await tool.execute(WebSearchArgs(query="example", max_results=1))
    assert "First Result" in res.content and "Second Result" not in res.content


@pytest.mark.asyncio
async def test_web_search_no_results():
    tool = WebSearchTool(transport=_transport("<html><body>nothing</body></html>"))
    res = await tool.execute(WebSearchArgs(query="zzz"))
    assert "No results" in res.content and not res.is_error


# --- permissions ------------------------------------------------------------


def test_web_tools_are_read_only_but_deny_can_block_by_url():
    assert Permissions().decide("web_fetch", {"url": "https://x.com"}) == "allow"
    assert Permissions().decide("web_search", {"query": "hi"}) == "allow"
    gated = Permissions(deny=["web_fetch(*internal*)"])
    assert gated.decide("web_fetch", {"url": "https://internal.local/x"}) == "deny"
    assert gated.decide("web_fetch", {"url": "https://example.com"}) == "allow"
