"""Tests for update_cache_breakpoints function."""

from anthropic.types import ToolResultBlockParam
from docketeer_anthropic.loop import update_cache_breakpoints

from docketeer.prompt import CacheControl, MessageParam


def test_update_cache_breakpoints_removes_old() -> None:
    """update_cache_breakpoints removes existing cache_control."""
    messages = [
        MessageParam(
            role="user",
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "result",
                    "cache_control": {"type": "ephemeral", "ttl": "5m"},
                }
            ],
        )
    ]
    tool_results: list[ToolResultBlockParam] = [
        {"type": "tool_result", "tool_use_id": "t2", "content": "new result"}
    ]

    update_cache_breakpoints(messages, tool_results)

    content = messages[0].content
    assert isinstance(content, list)
    block = content[0]
    assert isinstance(block, dict)
    assert "cache_control" not in block


def test_update_cache_breakpoints_adds_new() -> None:
    """update_cache_breakpoints adds cache_control to last tool_result."""
    messages: list[MessageParam] = []
    tool_results: list[ToolResultBlockParam] = [
        {"type": "tool_result", "tool_use_id": "t1", "content": "result"}
    ]

    update_cache_breakpoints(messages, tool_results)

    assert tool_results[-1]["cache_control"] == CacheControl().to_dict()


def test_update_cache_breakpoints_no_existing_cache() -> None:
    """update_cache_breakpoints works when no cache_control exists."""
    messages = [
        MessageParam(
            role="user",
            content=[{"type": "tool_result", "tool_use_id": "t1", "content": "result"}],
        )
    ]
    tool_results: list[ToolResultBlockParam] = [
        {"type": "tool_result", "tool_use_id": "t1", "content": "result"}
    ]

    update_cache_breakpoints(messages, tool_results)

    assert tool_results[-1]["cache_control"] == CacheControl().to_dict()


def test_update_cache_breakpoints_with_non_dict_blocks() -> None:
    """update_cache_breakpoints handles non-dict blocks in content."""
    messages = [
        MessageParam(
            role="user",
            content=[
                "plain string",
                {"type": "text", "text": "some text"},
            ],
        )
    ]
    tool_results: list[ToolResultBlockParam] = [
        {"type": "tool_result", "tool_use_id": "t1", "content": "result"}
    ]

    update_cache_breakpoints(messages, tool_results)

    assert tool_results[-1]["cache_control"] == CacheControl().to_dict()
