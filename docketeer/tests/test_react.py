"""Tests for the react tool."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from docketeer.main import _register_core_chat_tools
from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry


@pytest.fixture(autouse=True)
def _save_registry() -> Iterator[None]:
    original_tools = registry._tools.copy()
    original_schemas = registry._schemas.copy()
    yield
    registry._tools = original_tools
    registry._schemas = original_schemas


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")


@pytest.fixture()
def chat() -> MemoryChat:
    return MemoryChat()


@pytest.fixture()
def _register_tool(chat: MemoryChat) -> None:
    _register_core_chat_tools(chat)


@pytest.mark.usefixtures("_register_tool")
async def test_react_adds_reaction(chat: MemoryChat, tool_context: ToolContext):
    result = await registry.execute(
        "react", {"message_id": "msg1", "emoji": ":thumbsup:"}, tool_context
    )
    assert "Added" in result
    assert len(chat.reactions) == 1
    assert chat.reactions[0].message_id == "msg1"
    assert chat.reactions[0].emoji == ":thumbsup:"
    assert chat.reactions[0].action == "react"


@pytest.mark.usefixtures("_register_tool")
async def test_react_removes_reaction(chat: MemoryChat, tool_context: ToolContext):
    result = await registry.execute(
        "react",
        {"message_id": "msg1", "emoji": ":thumbsup:", "remove": True},
        tool_context,
    )
    assert "Removed" in result
    assert len(chat.reactions) == 1
    assert chat.reactions[0].action == "unreact"
