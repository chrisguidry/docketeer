"""Tests for the web_request tool."""

from unittest.mock import AsyncMock

import httpx
import respx

from docketeer.tools import ToolContext, registry
from docketeer_web.tools import SUMMARIZE_INPUT_SIZE


@respx.mock
async def test_text_html_reads_body(tool_context: ToolContext):
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text="<h1>Hello</h1>",
            headers={"content-type": "text/html"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/page"}, tool_context
    )
    assert "HTTP 200 https://example.com/page" in result
    assert "content-type: text/html" in result
    assert "<h1>Hello</h1>" in result


@respx.mock
async def test_application_json_reads_body(tool_context: ToolContext):
    respx.get("https://example.com/api").mock(
        return_value=httpx.Response(
            200,
            text='{"key": "value"}',
            headers={"content-type": "application/json"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/api"}, tool_context
    )
    assert "HTTP 200" in result
    assert '{"key": "value"}' in result


@respx.mock
async def test_image_skips_body(tool_context: ToolContext):
    respx.get("https://example.com/logo.png").mock(
        return_value=httpx.Response(
            200,
            content=b"\x89PNG fake image data",
            headers={"content-type": "image/png", "content-length": "500"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/logo.png"}, tool_context
    )
    assert "HTTP 200 https://example.com/logo.png" in result
    assert "content-type: image/png" in result
    assert "[body not read: binary content]" in result
    assert "PNG" not in result.split("\n")[-1]


@respx.mock
async def test_too_large_skips_body(tool_context: ToolContext):
    respx.get("https://example.com/big.html").mock(
        return_value=httpx.Response(
            200,
            text="x",
            headers={
                "content-type": "text/html",
                "content-length": str(52_400_000),
            },
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/big.html"}, tool_context
    )
    assert "[body not read: response too large (50.0 MB)]" in result
    assert "HTTP 200" in result


@respx.mock
async def test_classify_overrides_heuristic_to_read(
    tool_context: ToolContext,
):
    tool_context.classify_response = AsyncMock(return_value=True)
    respx.get("https://example.com/data.bin").mock(
        return_value=httpx.Response(
            200,
            text="readable binary format",
            headers={"content-type": "application/octet-stream"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/data.bin"}, tool_context
    )
    assert "readable binary format" in result
    assert "[body not read" not in result
    tool_context.classify_response.assert_awaited_once()


@respx.mock
async def test_classify_overrides_heuristic_to_skip(
    tool_context: ToolContext,
):
    tool_context.classify_response = AsyncMock(return_value=False)
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text="<html>secret</html>",
            headers={"content-type": "text/html"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/page"}, tool_context
    )
    assert "[body not read: binary content]" in result
    assert "secret" not in result


@respx.mock
async def test_classify_failure_falls_back_to_heuristic(
    tool_context: ToolContext,
):
    tool_context.classify_response = AsyncMock(side_effect=Exception("API down"))
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text="<html>fallback</html>",
            headers={"content-type": "text/html"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/page"}, tool_context
    )
    assert "<html>fallback</html>" in result
    assert "[body not read" not in result


@respx.mock
async def test_classify_not_called_when_too_large(
    tool_context: ToolContext,
):
    tool_context.classify_response = AsyncMock(return_value=True)
    respx.get("https://example.com/big.html").mock(
        return_value=httpx.Response(
            200,
            text="x",
            headers={
                "content-type": "text/html",
                "content-length": str(2_000_000),
            },
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/big.html"}, tool_context
    )
    assert "[body not read: response too large" in result
    tool_context.classify_response.assert_not_awaited()


@respx.mock
async def test_with_headers(tool_context: ToolContext):
    respx.get("https://example.com/api").mock(
        return_value=httpx.Response(
            200,
            text="OK",
            headers={"content-type": "text/plain"},
        )
    )
    result = await registry.execute(
        "web_request",
        {"url": "https://example.com/api", "headers": '{"X-Custom": "val"}'},
        tool_context,
    )
    assert "HTTP 200" in result
    assert "OK" in result


@respx.mock
async def test_bad_headers(tool_context: ToolContext):
    result = await registry.execute(
        "web_request",
        {"url": "https://example.com/api", "headers": "not json"},
        tool_context,
    )
    assert "Error: headers must be a valid JSON" in result


@respx.mock
async def test_truncates_when_no_callback(tool_context: ToolContext):
    respx.get("https://example.com/big").mock(
        return_value=httpx.Response(
            200,
            text="x" * 150_000,
            headers={"content-type": "text/html"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/big"}, tool_context
    )
    assert "[truncated from 146.5 KB of text/html]" in result
    assert len(result) < 150_000


@respx.mock
async def test_short_response_skips_summarization(
    tool_context: ToolContext,
):
    tool_context.summarize = AsyncMock(return_value="should not be called")
    respx.get("https://example.com/short").mock(
        return_value=httpx.Response(
            200,
            text="short content",
            headers={"content-type": "text/plain"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/short"}, tool_context
    )
    assert "short content" in result
    tool_context.summarize.assert_not_awaited()


@respx.mock
async def test_long_response_with_callback_summarizes(
    tool_context: ToolContext,
):
    tool_context.summarize = AsyncMock(return_value="summarized content")
    respx.get("https://example.com/long").mock(
        return_value=httpx.Response(
            200,
            text="x" * 150_000,
            headers={"content-type": "text/html"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/long"}, tool_context
    )
    assert "[summarized from 146.5 KB of text/html]" in result
    assert "summarized content" in result
    assert "truncated" not in result
    tool_context.summarize.assert_awaited_once()


@respx.mock
async def test_purpose_flows_to_callback(tool_context: ToolContext):
    captured = {}

    async def fake_summarize(text: str, purpose: str) -> str:
        captured["text"] = text
        captured["purpose"] = purpose
        return "summary"

    tool_context.summarize = fake_summarize
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text="y" * 150_000,
            headers={"content-type": "text/html"},
        )
    )
    await registry.execute(
        "web_request",
        {"url": "https://example.com/page", "purpose": "find pricing info"},
        tool_context,
    )
    assert captured["purpose"] == "find pricing info"


@respx.mock
async def test_caps_input_to_summarizer(tool_context: ToolContext):
    captured = {}

    async def fake_summarize(text: str, purpose: str) -> str:
        captured["text_len"] = len(text)
        return "summary"

    tool_context.summarize = fake_summarize
    big_text = "z" * (SUMMARIZE_INPUT_SIZE + 50_000)
    respx.get("https://example.com/huge").mock(
        return_value=httpx.Response(
            200,
            text=big_text,
            headers={"content-type": "text/plain"},
        )
    )
    await registry.execute(
        "web_request", {"url": "https://example.com/huge"}, tool_context
    )
    assert captured["text_len"] <= SUMMARIZE_INPUT_SIZE


@respx.mock
async def test_strips_html_before_summarizing(tool_context: ToolContext):
    captured = {}

    async def fake_summarize(text: str, purpose: str) -> str:
        captured["text"] = text
        return "summary"

    tool_context.summarize = fake_summarize
    html = (
        "<html><head><style>big{}</style></head><body>"
        + "<p>word</p>" * 20_000
        + "</body></html>"
    )
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    await registry.execute(
        "web_request", {"url": "https://example.com/page"}, tool_context
    )
    assert "<p>" not in captured["text"]
    assert "<style>" not in captured["text"]
    assert "word" in captured["text"]


@respx.mock
async def test_callback_failure_falls_back_to_truncation(
    tool_context: ToolContext,
):
    tool_context.summarize = AsyncMock(side_effect=Exception("API down"))
    respx.get("https://example.com/fail").mock(
        return_value=httpx.Response(
            200,
            text="w" * 150_000,
            headers={"content-type": "text/html"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/fail"}, tool_context
    )
    assert "[truncated from 146.5 KB of text/html]" in result
    assert len(result) < 150_000


@respx.mock
async def test_output_format(tool_context: ToolContext):
    respx.get("https://example.com/page").mock(
        return_value=httpx.Response(
            200,
            text="body text",
            headers={"content-type": "text/plain", "x-test": "yes"},
        )
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/page"}, tool_context
    )
    lines = result.split("\n")
    assert lines[0] == "HTTP 200 https://example.com/page"
    assert lines[1] == ""
    header_section = result.split("\n\n")[1]
    assert "content-type: text/plain" in header_section
    body_section = result.split("\n\n")[2]
    assert "body text" in body_section


@respx.mock
async def test_no_content_type_header(tool_context: ToolContext):
    respx.get("https://example.com/mystery").mock(
        return_value=httpx.Response(200, content=b"mystery content")
    )
    result = await registry.execute(
        "web_request", {"url": "https://example.com/mystery"}, tool_context
    )
    assert "[body not read: binary content]" in result
