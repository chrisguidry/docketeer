"""Tests for system prompt construction and extension point."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer.prompt import (
    CacheControl,
    MessageParam,
    SystemBlock,
    _load_prompt_providers,
    build_system_blocks,
    format_message_time,
)


def test_build_system_blocks_empty_without_providers(workspace: Path):
    with patch("docketeer.prompt._prompt_providers", []):
        blocks = build_system_blocks(workspace)
    assert blocks == []


def test_build_system_blocks_calls_prompt_providers(workspace: Path):
    def fake_provider(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text=f"Skills from {ws.name}")]

    with patch("docketeer.prompt._prompt_providers", [fake_provider]):
        blocks = build_system_blocks(workspace)

    assert blocks[0].text == f"Skills from {workspace.name}"
    assert blocks[-1].cache_control == CacheControl()


def test_build_system_blocks_provider_error_is_swallowed(workspace: Path):
    def bad_provider(ws: Path) -> list[SystemBlock]:
        raise RuntimeError("boom")

    with patch("docketeer.prompt._prompt_providers", [bad_provider]):
        blocks = build_system_blocks(workspace)

    assert blocks == []


def test_build_system_blocks_multiple_providers(workspace: Path):
    def provider_a(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text="block-a")]

    def provider_b(ws: Path) -> list[SystemBlock]:
        return [SystemBlock(text="block-b")]

    with patch("docketeer.prompt._prompt_providers", [provider_a, provider_b]):
        blocks = build_system_blocks(workspace)

    assert blocks[0].text == "block-a"
    assert blocks[1].text == "block-b"
    assert blocks[-1].cache_control == CacheControl()


def test_system_block_to_dict():
    block = SystemBlock(text="hello")
    assert block.to_dict() == {"type": "text", "text": "hello"}


def test_system_block_to_dict_with_cache_control():
    block = SystemBlock(text="hello", cache_control=CacheControl())
    api_dict = block.to_dict()
    assert api_dict == {
        "type": "text",
        "text": "hello",
        "cache_control": {"type": "ephemeral", "ttl": "5m"},
    }


def test_load_prompt_providers_delegates_to_discover_all():
    import docketeer.prompt as prompt_mod

    fake_provider = lambda ws: []  # noqa: E731
    prompt_mod._prompt_providers = None
    with patch("docketeer.prompt.discover_all", return_value=[fake_provider]) as mock:
        providers = _load_prompt_providers()
    mock.assert_called_once_with("docketeer.prompt")
    assert providers == [fake_provider]
    prompt_mod._prompt_providers = None


# --- format_message_time ---


def test_format_message_time_absolute_without_previous():
    ts = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    result = format_message_time(ts)
    # ISO 8601 with timezone offset
    assert result == ts.astimezone().isoformat(timespec="seconds")


def test_format_message_time_seconds():
    t1 = datetime(2026, 2, 6, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 10, 0, 30, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+30s"


def test_format_message_time_minutes():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 10, 5, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+5m"


def test_format_message_time_hours_and_minutes():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 12, 15, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+2h 15m"


def test_format_message_time_days_and_hours():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 7, 13, 0, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+1d 3h"


def test_format_message_time_days_only():
    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 9, 10, 0, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+3d"


@pytest.mark.parametrize(
    ("delta_seconds", "expected"),
    [
        (0, "+0s"),
        (1, "+1s"),
        (59, "+59s"),
        (60, "+1m"),
        (90, "+1m 30s"),
        (3_600, "+1h"),
        (3_661, "+1h 1m"),
        (86_400, "+1d"),
        (90_061, "+1d 1h"),
    ],
)
def test_format_message_time_parametrized(delta_seconds: int, expected: str):
    from datetime import timedelta

    t1 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    t2 = t1 + timedelta(seconds=delta_seconds)
    assert format_message_time(t2, t1) == expected


def test_format_message_time_negative_clamped():
    t1 = datetime(2026, 2, 6, 10, 5, tzinfo=UTC)
    t2 = datetime(2026, 2, 6, 10, 0, tzinfo=UTC)
    assert format_message_time(t2, t1) == "+0s"


def test_format_message_time_two_unit_max():
    t1 = datetime(2026, 2, 6, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 2, 7, 11, 15, 30, tzinfo=UTC)
    result = format_message_time(t2, t1)
    assert result == "+1d 1h"


def test_message_param_to_dict_str_content():
    msg = MessageParam(role="user", content="hello")
    assert msg.to_dict() == {"role": "user", "content": "hello"}


def test_message_param_to_dict_list_with_to_dict():
    from docketeer.prompt import TextBlockParam

    msg = MessageParam(role="user", content=[TextBlockParam(text="hello")])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "hello"}]


def test_message_param_to_dict_list_with_dict():
    msg = MessageParam(role="user", content=[{"type": "text", "text": "hello"}])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "hello"}]


def test_message_param_to_dict_list_with_other():
    msg = MessageParam(role="user", content=["plain string"])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "plain string"}]


def test_message_param_to_dict_list_unknown_object_falls_back_to_str():
    """Unknown objects in content are stringified as text blocks."""

    class CustomBlock:
        def __str__(self) -> str:
            return "custom text"

    msg = MessageParam(role="user", content=[CustomBlock()])
    result = msg.to_dict()
    assert result["role"] == "user"
    assert result["content"] == [{"type": "text", "text": "custom text"}]


def test_text_block_param_to_dict():
    from docketeer.prompt import TextBlockParam

    block = TextBlockParam(text="hello")
    assert block.to_dict() == {"type": "text", "text": "hello"}


def test_image_block_param_to_dict():
    from docketeer.prompt import Base64ImageSourceParam, ImageBlockParam

    source = Base64ImageSourceParam(media_type="image/png", data="abc123")
    block = ImageBlockParam(source=source)
    result = block.to_dict()
    assert result == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "abc123"},
    }


def test_base64_image_source_param_to_dict():
    from docketeer.prompt import Base64ImageSourceParam

    source = Base64ImageSourceParam(media_type="image/jpeg", data="xyz789")
    result = source.to_dict()
    assert result == {"type": "base64", "media_type": "image/jpeg", "data": "xyz789"}


def test_message_param_to_dict_fallback():
    msg = MessageParam(role="user", content=b"bytes")  # type: ignore[arg-type]
    result = msg.to_dict()
    assert result == {"role": "user", "content": b"bytes"}


def test_message_param_to_dict_with_tool_call_id():
    """Test tool_call_id field is serialized correctly."""
    msg = MessageParam(role="tool", content="tool result", tool_call_id="call_123")
    result = msg.to_dict()
    assert result == {
        "role": "tool",
        "content": "tool result",
        "tool_call_id": "call_123",
    }


def test_message_param_to_dict_with_tool_calls():
    """Test tool_calls field is serialized correctly."""
    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "test", "arguments": "{}"},
        }
    ]
    msg = MessageParam(role="assistant", content="", tool_calls=tool_calls)
    result = msg.to_dict()
    assert result["role"] == "assistant"
    assert result["content"] == ""
    assert result["tool_calls"] == tool_calls


def test_message_param_to_dict_with_tool_and_tool_call_id():
    """Test tool role with tool_call_id."""
    msg = MessageParam(role="tool", content="result", tool_call_id="call_abc")
    result = msg.to_dict()
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "call_abc"
    assert result["content"] == "result"
