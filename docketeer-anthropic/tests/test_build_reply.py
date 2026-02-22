"""Tests for build_reply function."""

from docketeer_anthropic.loop import build_reply

from .conftest import make_response, make_text_block


def test_build_reply_with_text() -> None:
    """build_reply joins text blocks."""
    text_block = make_text_block("Hello")
    response = make_response([text_block])

    result = build_reply(response, had_tool_use=False, rounds=1)
    assert "Hello" in result


def test_build_reply_max_tokens_suffix() -> None:
    """build_reply adds suffix for max_tokens without tool use."""
    text_block = make_text_block("Partial")
    response = make_response([text_block], stop_reason="max_tokens")

    result = build_reply(response, had_tool_use=False, rounds=1)
    assert "cut off" in result.lower()


def test_build_reply_tool_only_returns_empty() -> None:
    """build_reply returns empty string for tool-only response."""
    response = make_response([], stop_reason="end_turn")

    result = build_reply(response, had_tool_use=True, rounds=1)
    assert result == ""


def test_build_reply_no_text_no_tools() -> None:
    """build_reply returns placeholder for empty response without tools."""
    response = make_response([], stop_reason="end_turn")

    result = build_reply(response, had_tool_use=False, rounds=1)
    assert result == "(no response)"


def test_build_reply_multiple_text_blocks() -> None:
    """build_reply joins multiple text blocks."""
    block1 = make_text_block("Hello")
    block2 = make_text_block("World")

    response = make_response([block1, block2])

    result = build_reply(response, had_tool_use=False, rounds=1)
    assert "Hello" in result
    assert "World" in result
