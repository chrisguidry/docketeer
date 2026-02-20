"""Tests for MCP OAuth refresh task."""

from unittest.mock import AsyncMock, patch

from docketeer_mcp.tasks import mcp_oauth_refresh


def test_mcp_task_collections_exported():
    from docketeer_mcp.tasks import mcp_task_collections

    assert "docketeer_mcp.tasks:mcp_tasks" in mcp_task_collections


async def test_mcp_oauth_refresh_success():
    """Happy path: resolve refresh token, call refresh, store new tokens."""
    mock_vault = AsyncMock()
    mock_vault.resolve = AsyncMock(return_value="old_refresh_token")

    mock_docket = AsyncMock()
    mock_docket.add = lambda *a, **kw: AsyncMock()

    with patch(
        "docketeer_mcp.tasks.refresh_access_token",
        return_value={
            "access_token": "new_at",
            "token_type": "Bearer",
            "expires_in": 7200,
        },
    ):
        await mcp_oauth_refresh(
            token_secret="mcp/api/token",
            token_endpoint="https://api.example.com/token",
            client_id="cid",
            client_secret="csecret",
            expires_in=3600,
            vault=mock_vault,
            docket=mock_docket,
        )

    mock_vault.store.assert_any_call("mcp/api/token", "new_at")


async def test_mcp_oauth_refresh_with_rotated_refresh():
    """When server returns a new refresh token, store it."""
    mock_vault = AsyncMock()
    mock_vault.resolve = AsyncMock(return_value="old_refresh_token")

    mock_docket = AsyncMock()
    mock_docket.add = lambda *a, **kw: AsyncMock()

    with patch(
        "docketeer_mcp.tasks.refresh_access_token",
        return_value={
            "access_token": "new_at",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "new_rt",
        },
    ):
        await mcp_oauth_refresh(
            token_secret="mcp/api/token",
            token_endpoint="https://api.example.com/token",
            client_id="cid",
            vault=mock_vault,
            docket=mock_docket,
        )

    mock_vault.store.assert_any_call("mcp/api/token", "new_at")
    mock_vault.store.assert_any_call("mcp/api/token/refresh", "new_rt")


async def test_mcp_oauth_refresh_no_access_token():
    """When response has no access_token, skip storing it."""
    mock_vault = AsyncMock()
    mock_vault.resolve = AsyncMock(return_value="old_refresh_token")

    mock_docket = AsyncMock()
    mock_docket.add = lambda *a, **kw: AsyncMock()

    with patch(
        "docketeer_mcp.tasks.refresh_access_token",
        return_value={
            "token_type": "Bearer",
            "expires_in": 7200,
        },
    ):
        await mcp_oauth_refresh(
            token_secret="mcp/api/token",
            token_endpoint="https://api.example.com/token",
            client_id="cid",
            vault=mock_vault,
            docket=mock_docket,
        )

    # Should not store an empty access token
    for call in (
        mock_vault.store.call_args_list
    ):  # pragma: no cover - empty when no access_token
        assert call.args[0] != "mcp/api/token" or call.args[1] != ""


async def test_mcp_oauth_refresh_resolve_failure():
    """When refresh token can't be resolved, log and return without crashing."""
    mock_vault = AsyncMock()
    mock_vault.resolve = AsyncMock(side_effect=RuntimeError("vault error"))

    mock_docket = AsyncMock()

    # Should not raise
    await mcp_oauth_refresh(
        token_secret="mcp/api/token",
        token_endpoint="https://api.example.com/token",
        client_id="cid",
        vault=mock_vault,
        docket=mock_docket,
    )

    mock_vault.store.assert_not_called()


async def test_mcp_oauth_refresh_api_failure():
    """When the refresh API call fails, log and return without crashing."""
    mock_vault = AsyncMock()
    mock_vault.resolve = AsyncMock(return_value="old_refresh_token")

    mock_docket = AsyncMock()

    with patch(
        "docketeer_mcp.tasks.refresh_access_token",
        side_effect=RuntimeError("refresh failed"),
    ):
        await mcp_oauth_refresh(
            token_secret="mcp/api/token",
            token_endpoint="https://api.example.com/token",
            client_id="cid",
            vault=mock_vault,
            docket=mock_docket,
        )

    mock_vault.store.assert_not_called()
