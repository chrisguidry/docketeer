"""Web tools: search, request, and download."""

import asyncio
import json
import logging
from html.parser import HTMLParser
from importlib.metadata import version

import httpx

from docketeer import environment
from docketeer.tools import ToolContext, _safe_path, registry

log = logging.getLogger(__name__)

BRAVE_API_KEY = environment.get_str("BRAVE_API_KEY", "")
USER_AGENT = (
    f"docketeer-web/{version('docketeer-web')}"
    " (https://github.com/chrisguidry/docketeer)"
)

MAX_BODY_SIZE = 1_000_000
SUMMARIZE_THRESHOLD = 100_000
SUMMARIZE_INPUT_SIZE = 500_000


class _HTMLTextExtractor(HTMLParser):
    """Extract visible text from HTML, skipping scripts and styles."""

    _SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "head"})

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in ("br", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)


def _html_to_text(html: str) -> str:
    """Extract visible text from HTML."""
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


READABLE_CONTENT_TYPES = {
    "text/html",
    "text/plain",
    "text/css",
    "text/csv",
    "text/xml",
    "text/javascript",
    "application/json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/javascript",
    "application/ld+json",
}


def _is_readable_content_type(content_type: str) -> bool:
    """Check if a content type looks like readable text."""
    media_type = content_type.split(";")[0].strip().lower()
    return media_type in READABLE_CONTENT_TYPES


def _format_headers(headers: httpx.Headers) -> str:
    """Format response headers for display."""
    return "\n".join(f"{k}: {v}" for k, v in headers.items())


def _human_size(n: int) -> str:
    """Format a byte count as a human-readable string."""
    for unit in ("bytes", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            if unit == "bytes":
                return f"{n} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n} bytes"  # pragma: no cover


@registry.tool
async def web_search(ctx: ToolContext, query: str, count: int = 5) -> str:
    """Search the web using Brave Search.

    query: search query
    count: number of results (default 5)
    """
    if not BRAVE_API_KEY:
        return (
            "Error: Brave Search API key not configured (set DOCKETEER_BRAVE_API_KEY)"
        )

    max_retries = 3
    async with httpx.AsyncClient(headers={"user-agent": USER_AGENT}) as client:
        for attempt in range(max_retries):
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={"X-Subscription-Token": BRAVE_API_KEY},
                timeout=30,
            )
            if response.status_code == 429:
                retry_after = int(response.headers.get("retry-after", 1))
                log.info(
                    "Brave rate limited, retrying in %ds (attempt %d/%d)",
                    retry_after,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(retry_after)
                continue
            if response.status_code == 401:
                return "Error: Brave Search API key is invalid"
            response.raise_for_status()
            break
        else:
            return "Error: Brave Search rate limit exceeded, try again shortly"

        data = response.json()

    results = data.get("web", {}).get("results", [])
    if not results:
        return f"No results for '{query}'"

    lines = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "")
        url = r.get("url", "")
        desc = r.get("description", "")
        lines.append(f"{i}. {title}\n   {url}\n   {desc}")

    return "\n\n".join(lines)


@registry.tool
async def web_request(
    ctx: ToolContext,
    url: str,
    method: str = "GET",
    headers: str = "",
    body: str = "",
    purpose: str = "",
) -> str:
    """Make an HTTP request to a URL.

    url: the URL to request
    method: HTTP method (default GET)
    headers: optional JSON string of headers
    body: optional request body
    purpose: why you're fetching this page (guides summarization of long responses)
    """
    parsed_headers = {}
    if headers:
        try:
            parsed_headers = json.loads(headers)
        except json.JSONDecodeError:
            return "Error: headers must be a valid JSON string"

    async with httpx.AsyncClient(headers={"user-agent": USER_AGENT}) as client:
        async with client.stream(
            method=method,
            url=url,
            headers=parsed_headers,
            content=body or None,
            timeout=30,
        ) as response:
            status_line = f"HTTP {response.status_code} {url}"
            resp_headers = _format_headers(response.headers)
            content_type = response.headers.get("content-type", "")

            # Check content-length before reading
            content_length = int(response.headers.get("content-length", "0"))
            if content_length > MAX_BODY_SIZE:
                size = _human_size(content_length)
                note = f"[body not read: response too large ({size})]"
                return f"{status_line}\n\n{resp_headers}\n\n{note}"

            # Classify: callback with fallback to heuristic
            readable = _is_readable_content_type(content_type)
            if ctx.classify_response:
                try:
                    readable = await ctx.classify_response(
                        url, response.status_code, resp_headers
                    )
                except Exception:
                    log.exception("classify_response failed, falling back to heuristic")

            if not readable:
                note = "[body not read: binary content]"
                return f"{status_line}\n\n{resp_headers}\n\n{note}"

            text = (await response.aread()).decode("utf-8", errors="replace")

    if len(text) > SUMMARIZE_THRESHOLD:
        media_type = content_type.split(";")[0].strip() if content_type else "text"
        original_size = _human_size(len(text))
        if ctx.summarize:
            try:
                summarize_text = text[:MAX_BODY_SIZE]
                if "html" in media_type:
                    summarize_text = _html_to_text(summarize_text)
                text = await ctx.summarize(
                    summarize_text[:SUMMARIZE_INPUT_SIZE], purpose
                )
                text = f"[summarized from {original_size} of {media_type}]\n{text}"
            except Exception:
                log.exception(
                    "Web page summarization failed, falling back to truncation"
                )
                text = (
                    f"[truncated from {original_size} of {media_type}]\n"
                    + text[:SUMMARIZE_THRESHOLD]
                )
        else:
            text = (
                f"[truncated from {original_size} of {media_type}]\n"
                + text[:SUMMARIZE_THRESHOLD]
            )

    return f"{status_line}\n\n{resp_headers}\n\n{text}"


@registry.tool
async def download_file(ctx: ToolContext, url: str, path: str) -> str:
    """Download a file from a URL to the workspace.

    url: the URL to download
    path: relative path in workspace to save the file
    """
    target = _safe_path(ctx.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(
        headers={"user-agent": USER_AGENT}, follow_redirects=True
    ) as client:
        response = await client.get(url, timeout=60)
        response.raise_for_status()

    target.write_bytes(response.content)
    return f"Downloaded {len(response.content)} bytes to {path}"
