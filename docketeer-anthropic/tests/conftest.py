"""Shared test fixtures and helpers for docketeer-anthropic plugin tests."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from docketeer.brain.core import InferenceModel
from docketeer.tools import ToolContext

MODEL = InferenceModel(model_id="claude-sonnet-4-5-20251001", max_output_tokens=64_000)

MAX_TOOL_ROUNDS = 10


@pytest.fixture()
def mock_client() -> MagicMock:  # pragma: no cover
    """Create a mock Anthropic client."""
    client = MagicMock()
    client.messages = MagicMock()
    return client


@pytest.fixture()
def tool_context(tmp_path: Path) -> ToolContext:  # pragma: no cover
    """Create a test tool context."""
    return ToolContext(workspace=tmp_path, username="test-user")


def make_response(
    content: Any, stop_reason: str = "end_turn", usage: Any = None
) -> MagicMock:  # pragma: no cover
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


def make_text_block(text: str = "Hello!") -> MagicMock:  # pragma: no cover
    """Create a mock text block."""
    block = MagicMock(spec=TextBlock)
    block.text = text
    return block


def make_tool_block(
    name: str = "test_tool",
    tool_id: str = "tool_1",
    input_data: dict[str, Any] | None = None,
) -> MagicMock:  # pragma: no cover
    """Create a mock tool use block."""
    block = MagicMock(spec=ToolUseBlock)
    block.name = name
    block.id = tool_id
    block.input = input_data or {}
    return block


class FakeStream:  # pragma: no cover
    """Fake stream context manager for testing."""

    def __init__(self, response: MagicMock) -> None:
        self._response = response
        self.text_stream = self._make_text_stream()

    def _make_text_stream(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for block in self._response.content:
                if hasattr(block, "text"):
                    yield block.text[:5] if len(block.text) > 5 else block.text

        return gen()

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def get_final_message(self) -> MagicMock:
        return self._response
