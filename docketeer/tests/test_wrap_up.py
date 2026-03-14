"""Tests for the wrap_up_silently tool."""

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
    return ToolContext(workspace=workspace, chat_room="room1")


@pytest.fixture()
def chat() -> MemoryChat:
    return MemoryChat()


@pytest.fixture()
def _register_tool(chat: MemoryChat) -> None:
    _register_core_chat_tools(chat)


@pytest.mark.usefixtures("_register_tool")
async def test_wrap_up_silently_registered(chat: MemoryChat, tool_context: ToolContext):
    assert "wrap_up_silently" in registry._tools


@pytest.mark.usefixtures("_register_tool")
async def test_wrap_up_silently_no_emoji(chat: MemoryChat, tool_context: ToolContext):
    result = await registry.execute("wrap_up_silently", {}, tool_context)
    assert "no message" in result.lower()
    assert chat.reactions == []
    assert tool_context.silent_wrap_up is True


@pytest.mark.usefixtures("_register_tool")
async def test_wrap_up_silently_with_emoji_and_message_id(
    chat: MemoryChat, tool_context: ToolContext
):
    tool_context.message_id = "msg_42"
    result = await registry.execute(
        "wrap_up_silently", {"emoji": ":thumbsup:"}, tool_context
    )
    assert ":thumbsup:" in result
    assert len(chat.reactions) == 1
    assert chat.reactions[0].message_id == "msg_42"
    assert chat.reactions[0].emoji == ":thumbsup:"
    assert chat.reactions[0].action == "react"
    assert tool_context.silent_wrap_up is True


@pytest.mark.usefixtures("_register_tool")
async def test_wrap_up_silently_with_emoji_but_no_message_id(
    chat: MemoryChat, tool_context: ToolContext
):
    result = await registry.execute(
        "wrap_up_silently", {"emoji": ":thumbsup:"}, tool_context
    )
    assert "no message" in result.lower()
    assert chat.reactions == []
