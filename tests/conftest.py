"""Shared test fixtures for Docketeer."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from docketeer.brain import Brain
from docketeer.config import Config
from docketeer.tools import ToolContext


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def config(tmp_path: Path, workspace: Path) -> Config:
    return Config(
        rocketchat_url="http://localhost:3000",
        rocketchat_username="testbot",
        rocketchat_password="testpass",
        anthropic_api_key="test-key",
        data_dir=tmp_path,
        brave_api_key="brave-test-key",
    )


@pytest.fixture()
def tool_context(config: Config) -> ToolContext:
    return ToolContext(workspace=config.workspace_path, config=config, room_id="room1")


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


class FakeStream:
    def __init__(self, message: FakeMessage) -> None:
        self._message = message

    def __enter__(self) -> "FakeStream":
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def get_final_message(self) -> FakeMessage:
        return self._message


class FakeMessages:
    """Drop-in for anthropic.Anthropic().messages with configurable responses."""

    def __init__(self) -> None:
        self.responses: list[FakeMessage] = [FakeMessage()]
        self._call_count = 0
        self.last_kwargs: dict[str, Any] = {}

    def stream(self, **kwargs: Any) -> FakeStream:
        self.last_kwargs = kwargs
        msg = self.responses[min(self._call_count, len(self.responses) - 1)]
        self._call_count += 1
        return FakeStream(msg)

    def count_tokens(self, **_kwargs: Any) -> MagicMock:
        m = MagicMock()
        m.input_tokens = 1000
        return m

    def create(self, **kwargs: Any) -> FakeMessage:
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
    with patch("docketeer.brain.anthropic.Anthropic", return_value=mock_client):
        yield mock_client


@pytest.fixture()
def brain(
    config: Config, tool_context: ToolContext, mock_anthropic: MagicMock
) -> Brain:
    return Brain(config, tool_context)
