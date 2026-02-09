"""Shared test fixtures for Docketeer."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from anthropic import APIConnectionError, AuthenticationError
from anthropic._exceptions import RequestTooLargeError
from anthropic.types import TextBlock, ToolUseBlock

from docketeer import environment
from docketeer.brain import Brain
from docketeer.tools import ToolContext

_FAKE_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def make_auth_error() -> AuthenticationError:
    response = httpx.Response(401, request=_FAKE_REQUEST)
    return AuthenticationError(message="invalid api key", response=response, body=None)


def make_request_too_large_error() -> RequestTooLargeError:
    response = httpx.Response(413, request=_FAKE_REQUEST)
    return RequestTooLargeError(
        message="request too large", response=response, body=None
    )


def make_api_connection_error() -> APIConnectionError:
    return APIConnectionError(request=_FAKE_REQUEST)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path) -> Iterator[None]:
    """Isolate tests from the real data directory."""
    data_dir = tmp_path / "data"
    with (
        patch.object(environment, "DATA_DIR", data_dir),
        patch.object(environment, "WORKSPACE_PATH", data_dir / "memory"),
        patch.object(environment, "AUDIT_PATH", data_dir / "audit"),
    ):
        yield


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")


def make_text_block(text: str = "Hello!") -> TextBlock:
    return TextBlock(type="text", text=text)


def make_tool_use_block(
    name: str = "read_file", input: dict | None = None, id: str = "tool_1"
) -> ToolUseBlock:
    return ToolUseBlock(type="tool_use", id=id, name=name, input=input or {})


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 10
    cache_creation_input_tokens: int = 5


@dataclass
class FakeMessage:
    content: list = field(default_factory=lambda: [make_text_block()])
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


class _AsyncTextIterator:
    """Async iterator over text blocks in a FakeMessage."""

    def __init__(self, content: list) -> None:
        self._texts = [b.text for b in content if hasattr(b, "text")]
        self._index = 0

    def __aiter__(self) -> "_AsyncTextIterator":
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._texts):
            raise StopAsyncIteration
        text = self._texts[self._index]
        self._index += 1
        return text


class FakeStream:
    def __init__(self, message: FakeMessage) -> None:
        self._message = message

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    @property
    def text_stream(self) -> _AsyncTextIterator:
        return _AsyncTextIterator(self._message.content)

    async def get_final_message(self) -> FakeMessage:
        return self._message


class FakeMessages:
    """Drop-in for anthropic.AsyncAnthropic().messages with configurable responses."""

    def __init__(self) -> None:
        self.responses: list[FakeMessage] = [FakeMessage()]
        self._call_count = 0
        self.last_kwargs: dict[str, Any] = {}

    def stream(self, **kwargs: Any) -> FakeStream:
        self.last_kwargs = kwargs
        msg = self.responses[min(self._call_count, len(self.responses) - 1)]
        self._call_count += 1
        return FakeStream(msg)

    async def count_tokens(self, **_kwargs: Any) -> MagicMock:
        m = MagicMock()
        m.input_tokens = 1000
        return m

    async def create(self, **kwargs: Any) -> FakeMessage:
        self.last_kwargs = kwargs
        msg = self.responses[min(self._call_count, len(self.responses) - 1)]
        self._call_count += 1
        return msg


@pytest.fixture()
def fake_messages() -> FakeMessages:
    return FakeMessages()


@pytest.fixture()
def mock_anthropic(fake_messages: FakeMessages) -> Iterator[MagicMock]:
    mock_client = MagicMock()
    mock_client.messages = fake_messages
    with patch(
        "docketeer.brain.core.anthropic.AsyncAnthropic", return_value=mock_client
    ):
        yield mock_client


@pytest.fixture()
def brain(tool_context: ToolContext, mock_anthropic: MagicMock) -> Brain:
    return Brain(tool_context)
