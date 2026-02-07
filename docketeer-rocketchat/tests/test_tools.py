"""Tests for Rocket Chat plugin entry points and tools (send_file)."""

from docketeer.testing import MemoryChat
from docketeer.tools import ToolContext, registry
from docketeer_rocketchat import create_client, register_tools
from docketeer_rocketchat.client import RocketChatClient


def test_create_client():
    client = create_client()
    assert isinstance(client, RocketChatClient)


async def test_send_file(tool_context: ToolContext):
    chat = MemoryChat()
    (tool_context.workspace / "test.txt").write_text("hello")
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "test.txt"}, tool_context)
    assert "Sent" in result
    assert len(chat.uploaded_files) == 1


async def test_send_file_not_found(tool_context: ToolContext):
    chat = MemoryChat()
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "nope.txt"}, tool_context)
    assert "File not found" in result


async def test_send_file_is_dir(tool_context: ToolContext):
    chat = MemoryChat()
    (tool_context.workspace / "subdir").mkdir()
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "subdir"}, tool_context)
    assert "Cannot send a directory" in result
