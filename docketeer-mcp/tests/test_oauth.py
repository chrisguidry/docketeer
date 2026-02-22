"""Tests for MCP OAuth helpers."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from docketeer_mcp.oauth import (
    PendingOAuth,
    build_authorization_url,
    discover_oauth_metadata,
    exchange_code,
    refresh_access_token,
    register_client,
)


def _mock_response(
    status_code: int = 200, json_data: dict | None = None
) -> httpx.Response:
    """Build a fake httpx.Response."""
    content = json.dumps(json_data or {}).encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "https://example.com"),
    )


async def test_discover_with_prm_and_oasm(mock_http: AsyncMock):
    prm_response = _mock_response(
        json_data={
            "resource": "https://mcp.example.com/mcp",
            "authorization_servers": ["https://auth.example.com"],
        }
    )
    oasm_response = _mock_response(
        json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "registration_endpoint": "https://auth.example.com/register",
            "scopes_supported": ["read", "write"],
        }
    )

    responses = iter([prm_response, oasm_response])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(
        "https://mcp.example.com/mcp"
    )

    assert auth_ep == "https://auth.example.com/authorize"
    assert token_ep == "https://auth.example.com/token"
    assert reg_ep == "https://auth.example.com/register"
    assert scopes == "read write"


async def test_discover_prm_no_scopes(mock_http: AsyncMock):
    """PRM without scopes_supported still works, scopes come from OASM."""
    prm_response = _mock_response(
        json_data={
            "resource": "https://mcp.example.com/mcp",
            "authorization_servers": ["https://auth.example.com"],
        }
    )
    oasm_response = _mock_response(
        json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "scopes_supported": ["api"],
        }
    )

    responses = iter([prm_response, oasm_response])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(
        "https://mcp.example.com/mcp"
    )

    assert scopes == "api"


async def test_discover_with_pathed_auth_server(mock_http: AsyncMock):
    """Auth server URL with a path uses path-aware OASM discovery."""
    prm_response = _mock_response(
        json_data={
            "resource": "https://mcp.example.com/mcp",
            "authorization_servers": ["https://auth.example.com/tenant/abc"],
        }
    )
    oasm_response = _mock_response(
        json_data={
            "issuer": "https://auth.example.com/tenant/abc",
            "authorization_endpoint": "https://auth.example.com/tenant/abc/authorize",
            "token_endpoint": "https://auth.example.com/tenant/abc/token",
        }
    )

    responses = iter([prm_response, oasm_response])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(
        "https://mcp.example.com/mcp"
    )

    assert auth_ep == "https://auth.example.com/tenant/abc/authorize"
    assert token_ep == "https://auth.example.com/tenant/abc/token"


async def test_discover_root_url_no_path(mock_http: AsyncMock):
    """Server at root URL (no path) only tries root PRM."""
    prm_response = _mock_response(
        json_data={
            "resource": "https://mcp.example.com/",
            "authorization_servers": ["https://auth.example.com"],
        }
    )
    oasm_response = _mock_response(
        json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }
    )

    responses = iter([prm_response, oasm_response])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(
        "https://mcp.example.com/"
    )

    assert auth_ep == "https://auth.example.com/authorize"


async def test_discover_legacy_no_prm(mock_http: AsyncMock):
    """When PRM returns 404, fall back to legacy OASM discovery."""
    prm_404_a = _mock_response(status_code=404)
    prm_404_b = _mock_response(status_code=404)
    oasm_response = _mock_response(
        json_data={
            "issuer": "https://mcp.example.com",
            "authorization_endpoint": "https://mcp.example.com/authorize",
            "token_endpoint": "https://mcp.example.com/token",
        }
    )

    responses = iter([prm_404_a, prm_404_b, oasm_response])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(
        "https://mcp.example.com/mcp"
    )

    assert auth_ep == "https://mcp.example.com/authorize"
    assert token_ep == "https://mcp.example.com/token"
    assert reg_ep is None
    assert scopes is None


async def test_discover_prm_with_scopes(mock_http: AsyncMock):
    """PRM includes scopes_supported — scopes come from PRM."""
    prm_response = _mock_response(
        json_data={
            "resource": "https://mcp.example.com/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "scopes_supported": ["read", "write", "admin"],
        }
    )
    oasm_response = _mock_response(
        json_data={
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }
    )

    responses = iter([prm_response, oasm_response])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    auth_ep, token_ep, reg_ep, scopes = await discover_oauth_metadata(
        "https://mcp.example.com/mcp"
    )

    assert scopes == "read write admin"
    assert auth_ep == "https://auth.example.com/authorize"


async def test_discover_oasm_fails(mock_http: AsyncMock):
    """When both PRM and OASM return 404, raise."""
    prm_404_a = _mock_response(status_code=404)
    prm_404_b = _mock_response(status_code=404)
    oasm_404 = _mock_response(status_code=404)

    responses = iter([prm_404_a, prm_404_b, oasm_404])

    async def mock_get(url: str, **kwargs: object) -> httpx.Response:
        return next(responses)

    mock_http.get = mock_get

    with pytest.raises(RuntimeError, match="Could not discover"):
        await discover_oauth_metadata("https://mcp.example.com/mcp")


async def test_register_client(mock_http: AsyncMock):
    response = _mock_response(
        json_data={
            "client_id": "abc123",
            "client_secret": "secret456",
        }
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    client_id, client_secret = await register_client(
        "https://auth.example.com/register",
        "http://127.0.0.1:3141/callback",
        "docketeer",
        "read write",
    )

    assert client_id == "abc123"
    assert client_secret == "secret456"


async def test_register_client_no_secret(mock_http: AsyncMock):
    response = _mock_response(
        json_data={
            "client_id": "abc123",
        }
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    client_id, client_secret = await register_client(
        "https://auth.example.com/register",
        "http://127.0.0.1:3141/callback",
        "docketeer",
    )

    assert client_id == "abc123"
    assert client_secret == ""


async def test_register_client_failure(mock_http: AsyncMock):
    response = _mock_response(
        status_code=400, json_data={"error": "invalid_client_metadata"}
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    with pytest.raises(RuntimeError, match="Client registration failed"):
        await register_client(
            "https://auth.example.com/register",
            "http://127.0.0.1:3141/callback",
            "docketeer",
        )


def test_build_authorization_url():
    pending = PendingOAuth(
        server_url="https://mcp.example.com/mcp",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        code_verifier="test_verifier_that_is_long_enough_for_pkce_requirements_43chars",
        code_challenge="test_challenge",
        state="random_state",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="abc123",
        scopes="read write",
    )
    url = build_authorization_url(pending)

    assert "https://auth.example.com/authorize?" in url
    assert "response_type=code" in url
    assert "client_id=abc123" in url
    assert "state=random_state" in url
    assert "code_challenge=test_challenge" in url
    assert "code_challenge_method=S256" in url
    assert "scope=read+write" in url
    assert "redirect_uri=" in url


def test_build_authorization_url_no_scopes():
    pending = PendingOAuth(
        server_url="https://mcp.example.com/mcp",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        code_verifier="test_verifier_that_is_long_enough_for_pkce_requirements_43chars",
        code_challenge="test_challenge",
        state="random_state",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="abc123",
    )
    url = build_authorization_url(pending)

    assert "scope=" not in url


async def test_exchange_code(mock_http: AsyncMock):
    response = _mock_response(
        json_data={
            "access_token": "at_123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "rt_456",
        }
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    pending = PendingOAuth(
        server_url="https://mcp.example.com/mcp",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        code_verifier="verifier_long_enough_for_pkce_requirements_here_43chars",
        code_challenge="challenge",
        state="state123",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="abc123",
        client_secret="secret",
    )

    tokens = await exchange_code(pending, "auth_code_xyz")

    assert tokens["access_token"] == "at_123"
    assert tokens["refresh_token"] == "rt_456"
    assert tokens["expires_in"] == 3600


async def test_exchange_code_failure(mock_http: AsyncMock):
    response = _mock_response(status_code=400, json_data={"error": "invalid_grant"})

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    pending = PendingOAuth(
        server_url="https://mcp.example.com/mcp",
        authorization_endpoint="https://auth.example.com/authorize",
        token_endpoint="https://auth.example.com/token",
        code_verifier="verifier_long_enough_for_pkce_requirements_here_43chars",
        code_challenge="challenge",
        state="state123",
        redirect_uri="http://127.0.0.1:3141/callback",
        client_id="abc123",
    )

    with pytest.raises(RuntimeError, match="Token exchange failed"):
        await exchange_code(pending, "bad_code")


async def test_refresh_access_token(mock_http: AsyncMock):
    response = _mock_response(
        json_data={
            "access_token": "new_at",
            "token_type": "Bearer",
            "expires_in": 7200,
            "refresh_token": "new_rt",
        }
    )

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    tokens = await refresh_access_token(
        "https://auth.example.com/token",
        "old_refresh_token",
        "abc123",
        "secret",
    )

    assert tokens["access_token"] == "new_at"
    assert tokens["refresh_token"] == "new_rt"


async def test_refresh_access_token_failure(mock_http: AsyncMock):
    response = _mock_response(status_code=400, json_data={"error": "invalid_grant"})

    async def mock_post(url: str, **kwargs: object) -> httpx.Response:
        return response

    mock_http.post = mock_post

    with pytest.raises(RuntimeError, match="Token refresh failed"):
        await refresh_access_token(
            "https://auth.example.com/token",
            "bad_refresh",
            "abc123",
        )
