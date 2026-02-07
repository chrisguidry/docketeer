"""Tests for web tools (search, request, download) using respx."""

import httpx
import respx

from docketeer.tools import ToolContext, registry


@respx.mock
async def test_web_search_success(ctx: ToolContext):
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
    result = await registry.execute("web_search", {"query": "test"}, ctx)
    assert "Result 1" in result
    assert "https://example.com" in result


@respx.mock
async def test_web_search_no_api_key(ctx: ToolContext):
    ctx.config.brave_api_key = ""
    result = await registry.execute("web_search", {"query": "test"}, ctx)
    assert "Brave Search API key not configured" in result


@respx.mock
async def test_web_search_invalid_key(ctx: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(401)
    )
    result = await registry.execute("web_search", {"query": "test"}, ctx)
    assert "API key is invalid" in result


@respx.mock
async def test_web_search_rate_limited_then_success(ctx: ToolContext):
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
    result = await registry.execute("web_search", {"query": "test"}, ctx)
    assert "OK" in result


@respx.mock
async def test_web_search_rate_limit_exhausted(ctx: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(429, headers={"retry-after": "0"})
    )
    result = await registry.execute("web_search", {"query": "test"}, ctx)
    assert "rate limit exceeded" in result


@respx.mock
async def test_web_search_no_results(ctx: ToolContext):
    respx.get("https://api.search.brave.com/res/v1/web/search").mock(
        return_value=httpx.Response(200, json={"web": {"results": []}})
    )
    result = await registry.execute("web_search", {"query": "test"}, ctx)
    assert "No results" in result


@respx.mock
async def test_web_request_get(ctx: ToolContext):
    respx.get("https://example.com/api").mock(
        return_value=httpx.Response(200, text="OK response")
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/api"}, ctx
    )
    assert "HTTP 200" in result
    assert "OK response" in result


@respx.mock
async def test_web_request_with_headers(ctx: ToolContext):
    respx.get("https://example.com/api").mock(
        return_value=httpx.Response(200, text="OK")
    )
    result = await registry.execute(
        "web_request",
        {"url": "https://example.com/api", "headers": '{"X-Custom": "val"}'},
        ctx,
    )
    assert "HTTP 200" in result


@respx.mock
async def test_web_request_bad_headers(ctx: ToolContext):
    result = await registry.execute(
        "web_request",
        {"url": "https://example.com/api", "headers": "not json"},
        ctx,
    )
    assert "Error: headers must be a valid JSON" in result


@respx.mock
async def test_web_request_truncates_long_response(ctx: ToolContext):
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(200, text="x" * 15_000)
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/big"}, ctx
    )
    assert "truncated" in result
    assert len(result) < 15_000


@respx.mock
async def test_download_file(ctx: ToolContext):
    respx.get("https://example.com/file.bin").mock(
        return_value=httpx.Response(200, content=b"binary data")
    )
    result = await registry.execute(
        "download_file",
        {"url": "https://example.com/file.bin", "path": "dl/file.bin"},
        ctx,
    )
    assert "Downloaded" in result
    assert (ctx.workspace / "dl" / "file.bin").read_bytes() == b"binary data"
