"""Tests for web tools (search, request, download) using respx."""

from unittest.mock import patch

import httpx
import respx

from docketeer.tools import ToolContext, registry


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
    with patch("docketeer.tools.BRAVE_API_KEY", ""):
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


@respx.mock
async def test_web_request_get(tool_context: ToolContext):
    respx.get("https://example.com/api").mock(
        return_value=httpx.Response(200, text="OK response")
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/api"}, tool_context
    )
    assert "HTTP 200" in result
    assert "OK response" in result


@respx.mock
async def test_web_request_with_headers(tool_context: ToolContext):
    respx.get("https://example.com/api").mock(
        return_value=httpx.Response(200, text="OK")
    )
    result = await registry.execute(
        "web_request",
        {"url": "https://example.com/api", "headers": '{"X-Custom": "val"}'},
        tool_context,
    )
    assert "HTTP 200" in result


@respx.mock
async def test_web_request_bad_headers(tool_context: ToolContext):
    result = await registry.execute(
        "web_request",
        {"url": "https://example.com/api", "headers": "not json"},
        tool_context,
    )
    assert "Error: headers must be a valid JSON" in result


@respx.mock
async def test_web_request_truncates_long_response(tool_context: ToolContext):
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, text="x" * 15_000)
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/big"}, tool_context
    )
    assert "truncated" in result
    assert len(result) < 15_000


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
