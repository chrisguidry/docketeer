"""Edge case tests for MCP OAuth-related tools."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from docketeer.tools import ToolContext, registry
from docketeer.vault import Vault
from docketeer_mcp.manager import MCPClientManager
from docketeer_mcp.oauth import PendingOAuth


@pytest.fixture(autouse=True)
def fresh_manager() -> Generator[MCPClientManager]:
    """Replace the module-level manager with a fresh instance for each test."""
    fresh = MCPClientManager()
    with (
        patch("docketeer_mcp.tools.manager", fresh),
        patch("docketeer_mcp.prompt.manager", fresh),
    ):
        yield fresh


@pytest.fixture()
def data_dir(tmp_path: Path) -> Generator[Path]:
    d = tmp_path / "data"
    d.mkdir()
    with patch("docketeer_mcp.config.environment") as mock_env:
        mock_env.DATA_DIR = d
        yield d


@pytest.fixture()
def mcp_dir(data_dir: Path) -> Path:
    d = data_dir / "mcp"
    d.mkdir()
    return d


def _write_server(mcp_dir: Path, name: str, data: dict) -> None:
    (mcp_dir / f"{name}.json").write_text(json.dumps(data))


async def test_connect_with_auth_vault_resolve_error(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When vault.resolve fails, return error message."""
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )

    mock_vault = AsyncMock(spec=Vault)
    mock_vault.resolve = AsyncMock(side_effect=RuntimeError("secret not found"))
    tool_context.vault = mock_vault

    result = await registry.execute("connect_mcp_server", {"name": "api"}, tool_context)
    assert "Failed to resolve" in result
    assert "secret not found" in result


async def test_connect_with_auth_connect_failure(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When vault resolves but connect() fails, return error."""
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )

    mock_vault = AsyncMock(spec=Vault)
    mock_vault.resolve = AsyncMock(return_value="token_123")
    tool_context.vault = mock_vault

    fresh_manager.connect = AsyncMock(side_effect=RuntimeError("connection failed"))  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "api"}, tool_context)
    assert "Failed to connect" in result


async def test_connect_with_auth_no_tools(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When auth connect succeeds but no tools found."""
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )

    mock_vault = AsyncMock(spec=Vault)
    mock_vault.resolve = AsyncMock(return_value="token_123")
    tool_context.vault = mock_vault

    fresh_manager.connect = AsyncMock(return_value=[])  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "api"}, tool_context)
    assert "no tools found" in result


async def test_connect_http_auth_discovery_failure(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When OAuth discovery fails, return error."""
    _write_server(mcp_dir, "api", {"url": "https://api.example.com/mcp"})

    with (
        patch("docketeer_mcp.tools._check_auth_required", return_value=True),
        patch(
            "docketeer_mcp.tools.discover_oauth_metadata",
            side_effect=RuntimeError("no metadata"),
        ),
    ):
        result = await registry.execute(
            "connect_mcp_server", {"name": "api"}, tool_context
        )

    assert "OAuth discovery failed" in result


async def test_connect_http_auth_no_reg_no_client_id(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When no registration endpoint and no client_id provided, return error."""
    _write_server(mcp_dir, "api", {"url": "https://api.example.com/mcp"})

    with (
        patch("docketeer_mcp.tools._check_auth_required", return_value=True),
        patch(
            "docketeer_mcp.tools.discover_oauth_metadata",
            return_value=(
                "https://api.example.com/authorize",
                "https://api.example.com/token",
                None,
                None,
            ),
        ),
    ):
        result = await registry.execute(
            "connect_mcp_server", {"name": "api"}, tool_context
        )

    assert "no registration endpoint" in result.lower()
    assert "client_id" in result.lower()


async def test_connect_http_auth_registration_failure(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When client registration fails, return error."""
    _write_server(mcp_dir, "api", {"url": "https://api.example.com/mcp"})

    with (
        patch("docketeer_mcp.tools._check_auth_required", return_value=True),
        patch(
            "docketeer_mcp.tools.discover_oauth_metadata",
            return_value=(
                "https://api.example.com/authorize",
                "https://api.example.com/token",
                "https://api.example.com/register",
                "read",
            ),
        ),
        patch(
            "docketeer_mcp.tools.register_client",
            side_effect=RuntimeError("reg failed"),
        ),
    ):
        result = await registry.execute(
            "connect_mcp_server", {"name": "api"}, tool_context
        )

    assert "registration failed" in result.lower()


async def test_mcp_oauth_complete_no_code_in_url(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    """When redirect URL has no code parameter, return error."""
    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["s"] = PendingOAuth(
        server_url="https://example.com/mcp",
        authorization_endpoint="https://example.com/authorize",
        token_endpoint="https://example.com/token",
        code_verifier="v",
        code_challenge="c",
        state="st",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="cid",
    )

    result = await registry.execute(
        "mcp_oauth_complete",
        {
            "server": "s",
            "redirect_url": "http://127.0.0.1:3141/callback?state=st",
            "token_secret": "mcp/s/token",
        },
        tool_context,
    )
    assert "no authorization code" in result.lower()


async def test_mcp_oauth_complete_exchange_failure(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    """When exchange_code raises, return error."""
    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["s"] = PendingOAuth(
        server_url="https://example.com/mcp",
        authorization_endpoint="https://example.com/authorize",
        token_endpoint="https://example.com/token",
        code_verifier="v",
        code_challenge="c",
        state="st",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="cid",
    )

    with patch(
        "docketeer_mcp.tools.exchange_code", side_effect=RuntimeError("invalid_grant")
    ):
        result = await registry.execute(
            "mcp_oauth_complete",
            {
                "server": "s",
                "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=st",
                "token_secret": "mcp/s/token",
            },
            tool_context,
        )
    assert "token exchange failed" in result.lower()


async def test_mcp_oauth_complete_no_access_token(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    """When token response has no access_token, return error."""
    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["s"] = PendingOAuth(
        server_url="https://example.com/mcp",
        authorization_endpoint="https://example.com/authorize",
        token_endpoint="https://example.com/token",
        code_verifier="v",
        code_challenge="c",
        state="st",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="cid",
    )

    with patch(
        "docketeer_mcp.tools.exchange_code",
        return_value={
            "token_type": "Bearer",
        },
    ):
        result = await registry.execute(
            "mcp_oauth_complete",
            {
                "server": "s",
                "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=st",
                "token_secret": "mcp/s/token",
            },
            tool_context,
        )
    assert "no access_token" in result.lower()


async def test_mcp_oauth_complete_server_not_in_config(
    tool_context: ToolContext, data_dir: Path, fresh_manager: MCPClientManager
):
    """When server is not in config during complete, still succeeds."""
    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["ghost"] = PendingOAuth(
        server_url="https://ghost.example.com/mcp",
        authorization_endpoint="https://ghost.example.com/authorize",
        token_endpoint="https://ghost.example.com/token",
        code_verifier="v",
        code_challenge="c",
        state="st",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="cid",
    )

    with patch(
        "docketeer_mcp.tools.exchange_code",
        return_value={
            "access_token": "at_123",
            "token_type": "Bearer",
        },
    ):
        result = await registry.execute(
            "mcp_oauth_complete",
            {
                "server": "ghost",
                "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=st",
                "token_secret": "mcp/ghost/token",
            },
            tool_context,
        )

    assert "complete" in result.lower()
    mock_vault.store.assert_any_call("mcp/ghost/token", "at_123")
    assert "ghost" not in fresh_manager._pending_oauth


async def test_mcp_oauth_complete_schedule_refresh_failure(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When scheduling refresh fails, complete still succeeds."""
    _write_server(mcp_dir, "api", {"url": "https://api.example.com/mcp"})

    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["api"] = PendingOAuth(
        server_url="https://api.example.com/mcp",
        authorization_endpoint="https://api.example.com/authorize",
        token_endpoint="https://api.example.com/token",
        code_verifier="v",
        code_challenge="c",
        state="st",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="cid",
        client_secret="csecret",
    )

    with (
        patch(
            "docketeer_mcp.tools.exchange_code",
            return_value={
                "access_token": "at_new",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rt_new",
            },
        ),
        patch(
            "docketeer_mcp.tools._schedule_token_refresh",
            side_effect=RuntimeError("no docket"),
        ),
    ):
        result = await registry.execute(
            "mcp_oauth_complete",
            {
                "server": "api",
                "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=st",
                "token_secret": "mcp/api/token",
            },
            tool_context,
        )

    assert "complete" in result.lower()
    mock_vault.store.assert_any_call("mcp/api/token", "at_new")
    mock_vault.store.assert_any_call("mcp/api/token/refresh", "rt_new")
