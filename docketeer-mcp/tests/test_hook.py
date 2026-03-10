"""Tests for the MCP workspace hook."""

from pathlib import Path, PurePosixPath
from unittest.mock import AsyncMock, patch

import pytest

from docketeer_mcp.hook import MCPHook, create_hook
from docketeer_mcp.manager import MCPClientManager


@pytest.fixture()
def hook() -> MCPHook:
    return MCPHook()


async def test_validate_stdio_server(hook: MCPHook):
    content = "---\ncommand: uvx\nargs: [mcp-server-time]\n---\nTime server."
    result = await hook.validate(PurePosixPath("mcp/time.md"), content)
    assert result is not None
    assert "Configured server 'time'" in result.message
    assert "command `uvx`" in result.message


async def test_validate_http_server(hook: MCPHook):
    content = "---\nurl: https://api.example.com/mcp\n---\nAPI server."
    result = await hook.validate(PurePosixPath("mcp/api.md"), content)
    assert result is not None
    assert "Configured server 'api'" in result.message
    assert "url `https://api.example.com/mcp`" in result.message


async def test_validate_no_frontmatter_raises(hook: MCPHook):
    with pytest.raises(ValueError, match="needs YAML frontmatter"):
        await hook.validate(PurePosixPath("mcp/bad.md"), "Plain text only.")


async def test_validate_no_command_or_url_raises(hook: MCPHook):
    content = "---\nnetwork_access: true\n---\nBody."
    with pytest.raises(ValueError, match="must have either"):
        await hook.validate(PurePosixPath("mcp/bad.md"), content)


async def test_validate_non_md_returns_none(hook: MCPHook):
    result = await hook.validate(PurePosixPath("mcp/notes.txt"), "hello")
    assert result is None


async def test_validate_nested_file_returns_none(hook: MCPHook):
    result = await hook.validate(PurePosixPath("mcp/server/config.md"), "hello")
    assert result is None


async def test_commit_is_noop(hook: MCPHook):
    content = "---\ncommand: uvx\n---\nBody."
    await hook.commit(PurePosixPath("mcp/time.md"), content)


async def test_on_delete_returns_message(hook: MCPHook):
    result = await hook.on_delete(PurePosixPath("mcp/time.md"))
    assert result is not None
    assert "Removed server 'time'" in result


async def test_on_delete_disconnects_if_connected(
    hook: MCPHook, fresh_manager: MCPClientManager
):
    fresh_manager._clients["active"] = object()  # type: ignore[assignment]
    fresh_manager._tools["active"] = []
    fresh_manager.disconnect = AsyncMock()  # type: ignore[method-assign]

    with patch("docketeer_mcp.hook.manager", fresh_manager):
        result = await hook.on_delete(PurePosixPath("mcp/active.md"))

    assert result is not None
    assert "Removed server 'active'" in result
    fresh_manager.disconnect.assert_called_once_with("active")  # type: ignore[union-attr]


async def test_on_delete_non_md_returns_none(hook: MCPHook):
    result = await hook.on_delete(PurePosixPath("mcp/notes.txt"))
    assert result is None


async def test_on_delete_nested_returns_none(hook: MCPHook):
    result = await hook.on_delete(PurePosixPath("mcp/server/config.md"))
    assert result is None


async def test_scan_is_noop(hook: MCPHook, workspace: Path):
    await hook.scan(workspace)


def test_create_hook_factory():
    hook = create_hook()
    assert isinstance(hook, MCPHook)
    assert hook.prefix == PurePosixPath("mcp")
