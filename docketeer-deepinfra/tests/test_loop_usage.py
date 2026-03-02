"""Tests for usage tracking in the agentic loop."""

from unittest.mock import MagicMock

from docketeer.prompt import MessageParam
from docketeer_deepinfra.loop import stream_message

from .conftest import MODEL, make_chunks, make_usage


async def test_stream_captures_usage(mock_client: MagicMock):
    usage = make_usage(prompt_tokens=42, completion_tokens=7, total_tokens=49)
    mock_client.chat.completions.create.return_value = make_chunks(
        content="Hello world", usage=usage
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
    usage = make_usage(
        prompt_tokens=100, completion_tokens=20, total_tokens=120, cached_tokens=80
    )
    mock_client.chat.completions.create.return_value = make_chunks(
        content="Hi", usage=usage
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
