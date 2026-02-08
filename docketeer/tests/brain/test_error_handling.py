"""Tests for Brain error handling — API failures, compaction retries, graceful fallbacks."""

from typing import Any, Never
from unittest.mock import AsyncMock

import pytest
from anthropic import AuthenticationError

from docketeer.brain import APOLOGY, Brain
from docketeer.prompt import MessageContent

from ..conftest import (
    FakeMessage,
    FakeStream,
    make_api_connection_error,
    make_auth_error,
    make_request_too_large_error,
    make_text_block,
)


async def test_process_request_too_large_compacts_and_retries(
    brain: Brain, fake_messages: Any
):
    """413 triggers compaction and a successful retry."""
    for i in range(10):
        brain._conversations["room1"].append(
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        )

    call_count = 0
    original_stream = fake_messages.stream

    def stream_with_413(**kwargs: Any) -> FakeStream:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise make_request_too_large_error()
        return original_stream(**kwargs)

    fake_messages.stream = stream_with_413
    fake_messages.responses = [
        FakeMessage(content=[make_text_block(text="Summary")]),
        FakeMessage(content=[make_text_block(text="Recovered!")]),
    ]
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content)
    assert response.text == "Recovered!"


async def test_process_request_too_large_persistent(brain: Brain, fake_messages: Any):
    """413 persists after compaction — returns apology."""
    for i in range(10):
        brain._conversations["room1"].append(
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
        )

    def stream_always_413(**kwargs: Any) -> Never:
        raise make_request_too_large_error()

    fake_messages.stream = stream_always_413
    fake_messages.responses = [FakeMessage(content=[make_text_block(text="Summary")])]
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content)
    assert response.text == APOLOGY


async def test_process_api_connection_error_returns_apology(
    brain: Brain, fake_messages: Any
):
    """Transient API errors return an apology."""

    def stream_connection_error(**kwargs: Any) -> Never:
        raise make_api_connection_error()

    fake_messages.stream = stream_connection_error
    content = MessageContent(username="chris", text="hello")
    response = await brain.process("room1", content)
    assert response.text == APOLOGY


async def test_process_auth_error_propagates(brain: Brain, fake_messages: Any):
    """AuthenticationError passes through process() unhandled."""

    def stream_auth_error(**kwargs: Any) -> Never:
        raise make_auth_error()

    fake_messages.stream = stream_auth_error
    content = MessageContent(username="chris", text="hello")
    with pytest.raises(AuthenticationError):
        await brain.process("room1", content)


async def test_measure_context_api_error_returns_stale_count(
    brain: Brain, fake_messages: Any
):
    """When count_tokens fails, _measure_context returns the last known count."""
    brain._room_token_counts["room1"] = 5000
    fake_messages.count_tokens = AsyncMock(side_effect=make_api_connection_error())
    result = await brain._measure_context("room1", [], [])
    assert result == 5000


async def test_measure_context_api_error_returns_zero_when_no_stale(
    brain: Brain, fake_messages: Any
):
    """When count_tokens fails and there's no stale count, returns 0."""
    fake_messages.count_tokens = AsyncMock(side_effect=make_api_connection_error())
    result = await brain._measure_context("room1", [], [])
    assert result == 0


async def test_summarize_webpage_api_error_returns_truncated(
    brain: Brain, fake_messages: Any
):
    """When summarization fails, returns truncated raw text."""
    long_text = "x" * 8000
    fake_messages.create = AsyncMock(side_effect=make_api_connection_error())
    result = await brain._summarize_webpage(long_text, "find info")
    assert result == long_text[:4000]


async def test_classify_response_api_error_returns_true(
    brain: Brain, fake_messages: Any
):
    """When classification fails, optimistically returns True."""
    fake_messages.create = AsyncMock(side_effect=make_api_connection_error())
    result = await brain._classify_response(
        "https://example.com", 200, "content-type: text/html"
    )
    assert result is True
