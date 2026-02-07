"""Tests for web tools: helpers, search, and download."""

from unittest.mock import patch

import httpx
import pytest
import respx

from docketeer.tools import ToolContext, registry
from docketeer_web.tools import (
    _format_headers,
    _html_to_text,
    _human_size,
    _is_readable_content_type,
)

# --- helper tests ---


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "text/plain",
        "text/html; charset=utf-8",
        "application/json",
        "application/xml",
        "application/ld+json",
    ],
)
def test_is_readable_content_type_true(content_type: str):
    assert _is_readable_content_type(content_type) is True


@pytest.mark.parametrize(
    "content_type",
    [
        "image/png",
        "application/octet-stream",
        "application/zip",
        "video/mp4",
        "audio/mpeg",
    ],
)
def test_is_readable_content_type_false(content_type: str):
    assert _is_readable_content_type(content_type) is False


def test_format_headers():
    headers = httpx.Headers({"content-type": "text/html", "x-custom": "val"})
    formatted = _format_headers(headers)
    assert "content-type: text/html" in formatted
    assert "x-custom: val" in formatted


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (500, "500 bytes"),
        (1024, "1.0 KB"),
        (1_048_576, "1.0 MB"),
        (1_073_741_824, "1.0 GB"),
        (52_400_000, "50.0 MB"),
    ],
)
def test_human_size(size: int, expected: str):
    assert _human_size(size) == expected


# --- _html_to_text tests ---


def test_html_to_text_strips_tags():
    assert _html_to_text("<p>Hello <b>world</b></p>") == "\nHello world"


def test_html_to_text_skips_script_and_style():
    html = (
        "<html><head><style>body{color:red}</style></head>"
        "<body><script>alert('hi')</script><p>visible</p></body></html>"
    )
    result = _html_to_text(html)
    assert "visible" in result
    assert "alert" not in result
    assert "color:red" not in result


def test_html_to_text_adds_newlines_for_blocks():
    html = "<h1>Title</h1><p>Paragraph</p><div>Block</div>"
    result = _html_to_text(html)
    assert "\n" in result
    assert "Title" in result
    assert "Paragraph" in result
    assert "Block" in result


def test_html_to_text_handles_nested_skip_tags():
    html = "<noscript><div><script>nested</script></div></noscript><p>kept</p>"
    result = _html_to_text(html)
    assert "nested" not in result
    assert "kept" in result


def test_html_to_text_plain_text_passthrough():
    assert _html_to_text("just plain text") == "just plain text"


# --- web_search tests ---


@respx.mock
async def test_web_search_success(tool_context: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Result 1",
                            "url": "https://example.com",
                            "description": "desc",
                        }
                    ]
                }
            },
        )
    )
    result = await registry.execute("web_search", {"query": "test"}, tool_context)
    assert "Result 1" in result
    assert "https://example.com" in result


@respx.mock
async def test_web_search_no_api_key(tool_context: ToolContext):
    with patch("docketeer_web.tools.BRAVE_API_KEY", ""):
        result = await registry.execute("web_search", {"query": "test"}, tool_context)
    assert "Brave Search API key not configured" in result


@respx.mock
async def test_web_search_invalid_key(tool_context: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(401)
    )
    result = await registry.execute("web_search", {"query": "test"}, tool_context)
    assert "API key is invalid" in result


@respx.mock
async def test_web_search_rate_limited_then_success(tool_context: ToolContext):
    route = respx.get("https://api.search.brave.com/res/v1/web/search")
    route.side_effect = [
        httpx.Response(429, headers={"retry-after": "0"}),
        httpx.Response(
            200,
            json={
                "web": {"results": [{"title": "OK", "url": "u", "description": "d"}]}
            },
        ),
    ]
    result = await registry.execute("web_search", {"query": "test"}, tool_context)
    assert "OK" in result


@respx.mock
async def test_web_search_rate_limit_exhausted(tool_context: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(429, headers={"retry-after": "0"})
    )
    result = await registry.execute("web_search", {"query": "test"}, tool_context)
    assert "rate limit exceeded" in result


@respx.mock
async def test_web_search_no_results(tool_context: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": []}})
    )
    result = await registry.execute("web_search", {"query": "test"}, tool_context)
    assert "No results" in result


# --- download_file tests ---


@respx.mock
async def test_download_file(tool_context: ToolContext):
    respx.get("https://example.com/file.bin").mock(
        return_value=httpx.Response(200, content=b"binary data")
    )
    result = await registry.execute(
        "download_file",
        {"url": "https://example.com/file.bin", "path": "dl/file.bin"},
        tool_context,
    )
    assert "Downloaded" in result
    assert (tool_context.workspace / "dl" / "file.bin").read_bytes() == b"binary data"
