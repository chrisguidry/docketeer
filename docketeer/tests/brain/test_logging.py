"""Tests for brain logging functions and profile loading."""

from docketeer.brain.core import (
    _format_message_content,
    _format_message_for_log,
)
from docketeer.prompt import MessageParam


def test_format_message_content_string():
    """String content is returned as-is."""
    result = _format_message_content("hello world")
    assert result == "hello world"


def test_format_message_content_string_truncates():
    """Long string content is truncated."""
    long_text = "a" * 600
    result = _format_message_content(long_text)
    assert len(result) == 503  # 500 + "..."
    assert result.endswith("...")


def test_format_message_content_list_with_text_blocks():
    """List content with text blocks extracts text."""
    content = [
        {"type": "text", "text": "hello"},
        {"type": "text", "text": "world"},
    ]
    result = _format_message_content(content)
    assert result == "hello\nworld"


def test_format_message_content_list_with_mixed_blocks():
    """List content with mixed blocks extracts only text."""
    content = [
        {"type": "text", "text": "hello"},
        {"type": "image", "source": "data:image/png;base64,..."},
        {"type": "text", "text": "world"},
    ]
    result = _format_message_content(content)
    assert result == "hello\nworld"


def test_format_message_content_with_object_with_text():
    """Content blocks with .text attribute are handled."""

    class MockBlock:
        def __init__(self) -> None:
            self.text = "from object"

    result = _format_message_content([MockBlock()])
    assert result == "from object"


def test_format_message_content_other():
    """Other content types are converted to string."""
    result = _format_message_content(None)  # type: ignore[arg-type]
    assert result == "None"


def test_format_message_for_log_user_message_strips_prefix():
    """User message strips the @username: prefix."""
    msg = MessageParam(role="user", content="@chris: hello world")
    result = _format_message_for_log(msg)
    assert result == "hello world"


def test_format_message_for_log_assistant_message():
    """Assistant message content is returned as-is."""
    msg = MessageParam(role="assistant", content="Hello there!")
    result = _format_message_for_log(msg)
    assert result == "Hello there!"


def test_format_message_for_log_with_tool_calls():
    """Messages with tool_calls show tool names."""
    msg = MessageParam(
        role="assistant",
        content="Using tool",
        tool_calls=[
            {"function": {"name": "list_files"}},
            {"function": {"name": "read_file"}},
        ],
    )
    result = _format_message_for_log(msg)
    assert "list_files" in result
    assert "read_file" in result
