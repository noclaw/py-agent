"""Web tools — fetch a URL as readable text, and run a web search.

Both are read-only (no local mutation) and central to assistant / second-brain agents. They
use ``httpx`` directly:

- ``web_fetch`` GETs a URL and returns its readable text (HTML is reduced to plain text /
  light markdown; text/JSON is returned as-is).
- ``web_search`` runs a query against a simple **keyless DuckDuckGo HTML** backend and
  returns the top results (title / URL / snippet). Swap it for a proper search API
  (Brave, Tavily, …) in production.

Note: these make outbound network requests. They're treated as read-only (auto-allowed); a
``deny`` permission rule can still block by URL/query (e.g. ``web_fetch(*internal*)``).
"""

from __future__ import annotations

import re
import urllib.parse
from html.parser import HTMLParser

import httpx
from pydantic import BaseModel, Field

from ..types import Tool, ToolResult
from .base import truncate_head

__all__ = ["WebFetchTool", "WebSearchTool", "html_to_text"]

_USER_AGENT = "Mozilla/5.0 (compatible; py-agent; +https://github.com/noclaw/py-agent)"
_TIMEOUT = httpx.Timeout(20.0)
_DDG_URL = "https://html.duckduckgo.com/html/"


# --- HTML → text -----------------------------------------------------------


class _TextExtractor(HTMLParser):
    """Reduce HTML to readable text: drop scripts/chrome, mark headings/lists, keep flow."""

    _SKIP = {"script", "style", "head", "noscript", "svg", "nav", "footer", "header", "form"}
    _BLOCK = {"p", "div", "section", "article", "ul", "ol", "table", "tr", "blockquote", "pre", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif self._skip:
            return
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self._out.append("\n- ")
        elif tag in self._BLOCK:
            self._out.append("\n")

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._out.append(data)

    def text(self) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in "".join(self._out).splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def html_to_text(html: str) -> str:
    """Reduce an HTML document to readable plain text."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — malformed HTML shouldn't crash the tool
        pass
    return parser.text()


# --- web_fetch -------------------------------------------------------------


class WebFetchArgs(BaseModel):
    url: str = Field(description="The http(s) URL to fetch.")


class WebFetchTool(Tool):
    name = "web_fetch"
    description = (
        "Fetch a web page or text resource and return its readable content. HTML is reduced "
        "to plain text; text/JSON is returned as-is. Use it to read docs, articles, or APIs."
    )
    parameters = WebFetchArgs
    prompt_snippet = "web_fetch: Fetch a URL and read its content"

    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout=_TIMEOUT) -> None:
        self._transport = transport
        self._timeout = timeout

    async def execute(self, args: WebFetchArgs, *, on_update=None) -> ToolResult:
        if not re.match(r"^https?://", args.url, re.IGNORECASE):
            return ToolResult(content=f"Only http(s) URLs are supported: {args.url}", is_error=True)
        client = httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=True,
            headers={"user-agent": _USER_AGENT},
        )
        try:
            resp = await client.get(args.url)
        except httpx.HTTPError as exc:
            return ToolResult(content=f"Could not fetch {args.url}: {type(exc).__name__}: {exc}", is_error=True)
        finally:
            await client.aclose()

        if resp.status_code >= 400:
            return ToolResult(content=f"HTTP {resp.status_code} fetching {args.url}", is_error=True)
        ctype = resp.headers.get("content-type", "").lower()
        if "html" in ctype:
            body = html_to_text(resp.text)
        elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype or not ctype:
            body = resp.text.strip()
        else:
            return ToolResult(content=f"Unsupported content type {ctype!r} for {args.url}.", is_error=True)

        body, truncated = truncate_head(body or "(empty response)")
        if truncated:
            body += "\n\n[truncated — fetch a more specific URL for the rest]"
        return ToolResult(content=f"# {args.url}\n\n{body}")


# --- web_search ------------------------------------------------------------


def _decode_ddg_href(href: str) -> str:
    """DuckDuckGo wraps result links as ``//duckduckgo.com/l/?uddg=<encoded>``; unwrap it."""
    if "uddg=" not in href:
        return href
    query = urllib.parse.urlparse(href if href.startswith("http") else "https:" + href).query
    return urllib.parse.parse_qs(query).get("uddg", [href])[0]


class _DDGResultParser(HTMLParser):
    """Pull (title, url, snippet) triples from a DuckDuckGo HTML results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._mode: str | None = None
        self._buf: list[str] = []
        self._url = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag != "a":
            return
        cls = dict(attrs).get("class", "") or ""
        if "result__a" in cls:
            self._mode, self._buf = "title", []
            self._url = _decode_ddg_href(dict(attrs).get("href", "") or "")
        elif "result__snippet" in cls:
            self._mode, self._buf = "snippet", []

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._mode is None:
            return
        text = "".join(self._buf).strip()
        if self._mode == "title":
            self.results.append({"title": text, "url": self._url, "snippet": ""})
        elif self._mode == "snippet" and self.results:
            self.results[-1]["snippet"] = text
        self._mode = None

    def handle_data(self, data: str) -> None:
        if self._mode:
            self._buf.append(data)


class WebSearchArgs(BaseModel):
    query: str = Field(description="The search query.")
    max_results: int = Field(default=5, description="Maximum number of results (1–10).")


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the web and return the top results (title, URL, snippet). Use it to find "
        "pages, then web_fetch a result URL for the full content."
    )
    parameters = WebSearchArgs
    prompt_snippet = "web_search: Search the web for information"

    def __init__(self, *, transport: httpx.BaseTransport | None = None, timeout=_TIMEOUT) -> None:
        self._transport = transport
        self._timeout = timeout

    async def execute(self, args: WebSearchArgs, *, on_update=None) -> ToolResult:
        n = max(1, min(args.max_results, 10))
        client = httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, headers={"user-agent": _USER_AGENT}
        )
        try:
            resp = await client.post(_DDG_URL, data={"q": args.query})
        except httpx.HTTPError as exc:
            return ToolResult(content=f"Search failed: {type(exc).__name__}: {exc}", is_error=True)
        finally:
            await client.aclose()
        if resp.status_code >= 400:
            return ToolResult(content=f"Search failed (HTTP {resp.status_code}).", is_error=True)

        parser = _DDGResultParser()
        parser.feed(resp.text)
        results = [r for r in parser.results if r["url"]][:n]
        if not results:
            return ToolResult(content=f"No results for {args.query!r}.")

        lines = [f"Results for {args.query!r}:", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['url']}")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
        return ToolResult(content="\n".join(lines))
