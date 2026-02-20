"""Tests for build_reply function."""

from typing import Any
from unittest.mock import MagicMock

from anthropic.types import TextBlock
from docketeer_anthropic.loop import build_reply

from docketeer.brain.core import InferenceModel

MODEL = InferenceModel(model_id="claude-sonnet-4-5-20251001", max_output_tokens=64_000)


def make_text_block(text: str = "Hello!") -> MagicMock:
    """Create a mock text block."""
    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def make_response(
    content: Any, stop_reason: str = "end_turn", usage: Any = None
) -> MagicMock:
    """Create a mock response."""
    response = MagicMock()
    response.content = content if isinstance(content, list) else [content]
    response.stop_reason = stop_reason
    response.usage = usage or MagicMock(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return response


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
