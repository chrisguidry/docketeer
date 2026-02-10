"""Tests for MCP OAuth-related tools (connect with auth, mcp_oauth_complete)."""

import json
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from docket import Docket

from docketeer.tools import ToolContext, registry
from docketeer.vault import Vault
from docketeer_mcp.manager import MCPClientManager, MCPToolInfo
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


async def test_connect_with_vault_auth(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When config has auth and vault is available, resolve token and connect."""
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )

    mock_vault = AsyncMock(spec=Vault)
    mock_vault.resolve = AsyncMock(return_value="bearer_token_123")
    tool_context.vault = mock_vault

    tools = [
        MCPToolInfo(server="api", name="query", description="Query", input_schema={})
    ]
    fresh_manager.connect = AsyncMock(return_value=tools)  # type: ignore[method-assign]

    result = await registry.execute("connect_mcp_server", {"name": "api"}, tool_context)
    assert "1 tools" in result
    fresh_manager.connect.assert_called_once()  # type: ignore[union-attr]
    call_kwargs = fresh_manager.connect.call_args  # type: ignore[union-attr]
    assert call_kwargs.kwargs.get("auth") == "bearer_token_123"


async def test_connect_with_auth_no_vault(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When config has auth but no vault, return error."""
    _write_server(
        mcp_dir, "api", {"url": "https://api.example.com/mcp", "auth": "mcp/api/token"}
    )
    tool_context.vault = None

    result = await registry.execute("connect_mcp_server", {"name": "api"}, tool_context)
    assert "vault" in result.lower()


async def test_connect_http_auth_required(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When HTTP server requires auth, return authorization URL."""
    _write_server(mcp_dir, "github", {"url": "https://mcp.github.com/mcp"})

    with (
        patch("docketeer_mcp.tools._check_auth_required", return_value=True),
        patch(
            "docketeer_mcp.tools.discover_oauth_metadata",
            return_value=(
                "https://auth.github.com/authorize",
                "https://auth.github.com/token",
                "https://auth.github.com/register",
                "read write",
            ),
        ),
        patch(
            "docketeer_mcp.tools.register_client",
            return_value=("client_abc", "secret_xyz"),
        ),
    ):
        result = await registry.execute(
            "connect_mcp_server", {"name": "github"}, tool_context
        )

    assert "Authorization needed" in result
    assert "mcp_oauth_complete" in result
    assert "github" in fresh_manager._pending_oauth


async def test_connect_http_auth_required_no_registration(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When no registration endpoint, use provided client_id."""
    _write_server(mcp_dir, "api", {"url": "https://api.example.com/mcp"})

    with (
        patch("docketeer_mcp.tools._check_auth_required", return_value=True),
        patch(
            "docketeer_mcp.tools.discover_oauth_metadata",
            return_value=(
                "https://api.example.com/authorize",
                "https://api.example.com/token",
                None,
                "read",
            ),
        ),
    ):
        result = await registry.execute(
            "connect_mcp_server",
            {"name": "api", "client_id": "my_client", "client_secret": "my_secret"},
            tool_context,
        )

    assert "Authorization needed" in result
    pending = fresh_manager._pending_oauth["api"]
    assert pending.client_id == "my_client"
    assert pending.client_secret == "my_secret"


async def test_connect_http_no_auth_required(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When HTTP server doesn't require auth, connect normally."""
    _write_server(mcp_dir, "open", {"url": "https://open.example.com/mcp"})
    tools = [
        MCPToolInfo(server="open", name="ping", description="Ping", input_schema={})
    ]
    fresh_manager.connect = AsyncMock(return_value=tools)  # type: ignore[method-assign]

    with patch("docketeer_mcp.tools._check_auth_required", return_value=False):
        result = await registry.execute(
            "connect_mcp_server", {"name": "open"}, tool_context
        )

    assert "1 tools" in result


async def test_mcp_oauth_complete_success(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """Happy path: exchange code, store token, update config."""
    _write_server(mcp_dir, "github", {"url": "https://mcp.github.com/mcp"})

    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["github"] = PendingOAuth(
        server_url="https://mcp.github.com/mcp",
        authorization_endpoint="https://auth.github.com/authorize",
        token_endpoint="https://auth.github.com/token",
        code_verifier="verifier",
        code_challenge="challenge",
        state="state123",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="client_abc",
    )

    with patch(
        "docketeer_mcp.tools.exchange_code",
        return_value={
            "access_token": "at_new",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    ):
        result = await registry.execute(
            "mcp_oauth_complete",
            {
                "server": "github",
                "redirect_url": "http://127.0.0.1:3141/callback?code=authcode&state=state123",
                "token_secret": "mcp/github/token",
            },
            tool_context,
        )

    assert (
        "stored" in result.lower()
        or "success" in result.lower()
        or "complete" in result.lower()
    )
    mock_vault.store.assert_any_call("mcp/github/token", "at_new")
    assert "github" not in fresh_manager._pending_oauth


async def test_mcp_oauth_complete_with_refresh(
    tool_context: ToolContext, mcp_dir: Path, fresh_manager: MCPClientManager
):
    """When refresh_token present, store it and schedule refresh task."""
    _write_server(mcp_dir, "api", {"url": "https://api.example.com/mcp"})

    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    mock_docket = AsyncMock()
    mock_docket.add = lambda *a, **kw: AsyncMock()

    fresh_manager._pending_oauth["api"] = PendingOAuth(
        server_url="https://api.example.com/mcp",
        authorization_endpoint="https://api.example.com/authorize",
        token_endpoint="https://api.example.com/token",
        code_verifier="verifier",
        code_challenge="challenge",
        state="mystate",
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
        patch("docketeer_mcp.tools.current_docket", return_value=mock_docket),
    ):
        await registry.execute(
            "mcp_oauth_complete",
            {
                "server": "api",
                "redirect_url": "http://127.0.0.1:3141/callback?code=code1&state=mystate",
                "token_secret": "mcp/api/token",
            },
            tool_context,
        )

    mock_vault.store.assert_any_call("mcp/api/token", "at_new")
    mock_vault.store.assert_any_call("mcp/api/token/refresh", "rt_new")
    mock_vault.store.assert_any_call("mcp/api/token/client_id", "cid")
    mock_vault.store.assert_any_call("mcp/api/token/client_secret", "csecret")
    mock_vault.store.assert_any_call(
        "mcp/api/token/token_endpoint", "https://api.example.com/token"
    )


async def test_mcp_oauth_complete_state_mismatch(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    """State mismatch returns error."""
    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    fresh_manager._pending_oauth["s"] = PendingOAuth(
        server_url="https://example.com/mcp",
        authorization_endpoint="https://example.com/authorize",
        token_endpoint="https://example.com/token",
        code_verifier="v",
        code_challenge="c",
        state="expected_state",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="cid",
    )

    result = await registry.execute(
        "mcp_oauth_complete",
        {
            "server": "s",
            "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=wrong_state",
            "token_secret": "mcp/s/token",
        },
        tool_context,
    )
    assert "state" in result.lower()


async def test_mcp_oauth_complete_no_pending(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    """No pending OAuth for server returns error."""
    mock_vault = AsyncMock(spec=Vault)
    tool_context.vault = mock_vault

    result = await registry.execute(
        "mcp_oauth_complete",
        {
            "server": "unknown",
            "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=y",
            "token_secret": "mcp/x/token",
        },
        tool_context,
    )
    assert "no pending" in result.lower() or "not found" in result.lower()


async def test_mcp_oauth_complete_no_vault(
    tool_context: ToolContext, fresh_manager: MCPClientManager
):
    """No vault returns error."""
    tool_context.vault = None

    result = await registry.execute(
        "mcp_oauth_complete",
        {
            "server": "s",
            "redirect_url": "http://127.0.0.1:3141/callback?code=x&state=y",
            "token_secret": "mcp/s/token",
        },
        tool_context,
    )
    assert "vault" in result.lower()


async def test_check_auth_required_401():
    """Returns True when server responds with 401."""
    from docketeer_mcp.tools import _check_auth_required

    mock_response = httpx.Response(
        status_code=401,
        request=httpx.Request("POST", "https://example.com/mcp"),
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return mock_response

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("docketeer_mcp.tools.httpx.AsyncClient", return_value=mock_client):
        assert await _check_auth_required("https://example.com/mcp") is True


async def test_check_auth_required_200():
    """Returns False when server responds with 200."""
    from docketeer_mcp.tools import _check_auth_required

    mock_response = httpx.Response(
        status_code=200,
        request=httpx.Request("POST", "https://example.com/mcp"),
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return mock_response

    mock_client = AsyncMock()
    mock_client.post = mock_post
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("docketeer_mcp.tools.httpx.AsyncClient", return_value=mock_client):
        assert await _check_auth_required("https://example.com/mcp") is False


async def test_check_auth_required_exception():
    """Returns False when request raises an exception."""
    from docketeer_mcp.tools import _check_auth_required

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("docketeer_mcp.tools.httpx.AsyncClient", return_value=mock_client):
        assert await _check_auth_required("https://example.com/mcp") is False


def test_current_docket():
    """Resolves docket from context var."""
    from contextvars import copy_context

    from docketeer.dependencies import set_docket
    from docketeer_mcp.tools import current_docket

    mock_docket = AsyncMock()

    def _run() -> Docket:
        set_docket(mock_docket)
        return current_docket()

    ctx = copy_context()
    result = ctx.run(_run)
    assert result is mock_docket
