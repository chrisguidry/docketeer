"""Shared test helpers for docketeer-autonomy."""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

from anthropic.types import TextBlock, ToolUseBlock

from docketeer.brain.backend import BackendAuthError


def make_backend_auth_error() -> BackendAuthError:
    return BackendAuthError("invalid api key")


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


class _AsyncTextIterator:  # pragma: no cover — called by docketeer_anthropic
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


class FakeStream:  # pragma: no cover — called by docketeer_anthropic
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

    async def create(self, **kwargs: Any) -> FakeMessage:  # pragma: no cover
        self.last_kwargs = kwargs
        msg = self.responses[min(self._call_count, len(self.responses) - 1)]
        self._call_count += 1
        return msg
