"""Tests for usage tracking in the agentic loop."""

from unittest.mock import MagicMock

from docketeer.prompt import MessageParam
from docketeer_deepinfra.loop import stream_message

from .conftest import MODEL, make_chunk, make_stream_mock, make_tool_call, make_usage


async def test_stream_captures_usage_from_final_chunk(mock_client: MagicMock):
    """Usage from the final chunk is captured."""
    usage_chunk = MagicMock()
    usage_chunk.choices = []
    usage_chunk.usage = make_usage(
        prompt_tokens=42, completion_tokens=7, total_tokens=49
    )

    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(content="Hello"),
            make_chunk(content=" world", finish_reason="stop"),
            usage_chunk,
        ]
    )

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.content == "Hello world"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 42
    assert result.usage.completion_tokens == 7
    assert result.usage.total_tokens == 49


async def test_stream_captures_cached_tokens(mock_client: MagicMock):
    """Cached tokens are captured from prompt_tokens_details."""
    usage_chunk = MagicMock()
    usage_chunk.choices = []
    usage_chunk.usage = make_usage(
        prompt_tokens=100, completion_tokens=20, total_tokens=120, cached_tokens=80
    )

    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(content="Hi", finish_reason="stop"),
            usage_chunk,
        ]
    )

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.usage is not None
    assert result.usage.prompt_tokens == 100
    assert result.usage.prompt_tokens_details is not None
    assert result.usage.prompt_tokens_details.cached_tokens == 80


async def test_stream_falls_back_to_zero_usage_without_usage_chunk(
    mock_client: MagicMock,
):
    """Fallback when no usage chunk is present."""
    mock_client.chat.completions.create = make_stream_mock(
        [make_chunk(content="test", finish_reason="stop")]
    )

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.usage is not None
    assert result.usage.prompt_tokens == 0
    assert result.usage.completion_tokens == 0


async def test_tool_call_with_none_index_skipped(mock_client: MagicMock):
    """Tool calls with None index are skipped."""
    mock_client.chat.completions.create = make_stream_mock(
        [
            make_chunk(
                tool_calls=[
                    make_tool_call(
                        index=None,  # type: ignore[arg-type]
                        call_id="call_123",
                        name="test",
                        arguments="{}",
                    )
                ],
                finish_reason="tool_calls",
            ),
        ]
    )

    result = await stream_message(
        client=mock_client,
        model=MODEL,
        system=[],
        messages=[MessageParam(role="user", content="test")],
        tools=[],
        on_first_text=None,
        default_model="test-model",
    )
    assert result.choices[0].message.tool_calls is None
