"""OAuth helpers for MCP server authentication.

Standalone functions that handle the OAuth discovery, registration, PKCE,
and token exchange steps. The agent orchestrates these via tools — no
subclassing of FastMCP's OAuthClientProvider needed.
"""

import hashlib
import secrets
import string
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse

import httpx
from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata

REDIRECT_URI = "http://127.0.0.1:3141/callback"


@dataclass
class PendingOAuth:
    """State held between the start and completion of an OAuth flow."""

    server_url: str
    authorization_endpoint: str
    token_endpoint: str
    code_verifier: str
    code_challenge: str
    state: str
    redirect_uri: str
    client_id: str
    client_secret: str = ""
    scopes: str = ""


def _generate_pkce() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = "".join(
        secrets.choice(string.ascii_letters + string.digits + "-._~")
        for _ in range(128)
    )
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


async def discover_oauth_metadata(
    server_url: str,
) -> tuple[str, str, str | None, str | None]:
    """Discover authorization and token endpoints for an MCP server.

    Tries RFC 9728 Protected Resource Metadata first, then falls back to
    legacy OASM discovery (/.well-known/oauth-authorization-server).

    Returns (authorization_endpoint, token_endpoint, registration_endpoint, scopes).
    """
    parsed = urlparse(server_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    async with httpx.AsyncClient() as client:
        # Try Protected Resource Metadata (path-aware, then root)
        prm_urls = []
        if parsed.path and parsed.path != "/":
            prm_urls.append(
                f"{base_url}/.well-known/oauth-protected-resource{parsed.path}"
            )
        prm_urls.append(f"{base_url}/.well-known/oauth-protected-resource")

        auth_server_url: str | None = None
        scopes: str | None = None

        for url in prm_urls:
            resp = await client.get(url)
            if resp.status_code == 200:
                prm = ProtectedResourceMetadata.model_validate_json(resp.content)
                auth_server_url = str(prm.authorization_servers[0])
                if prm.scopes_supported:
                    scopes = " ".join(prm.scopes_supported)
                break

        # Discover OAuth Authorization Server Metadata
        oasm_urls = []
        if auth_server_url:
            oasm_parsed = urlparse(auth_server_url)
            oasm_base = f"{oasm_parsed.scheme}://{oasm_parsed.netloc}"
            if oasm_parsed.path and oasm_parsed.path != "/":
                oasm_urls.append(
                    f"{oasm_base}/.well-known/oauth-authorization-server{oasm_parsed.path}"
                )
            oasm_urls.append(f"{oasm_base}/.well-known/oauth-authorization-server")
        else:
            oasm_urls.append(f"{base_url}/.well-known/oauth-authorization-server")

        for url in oasm_urls:
            resp = await client.get(url)
            if resp.status_code == 200:
                oasm = OAuthMetadata.model_validate_json(resp.content)
                reg_ep = (
                    str(oasm.registration_endpoint)
                    if oasm.registration_endpoint
                    else None
                )
                if not scopes and oasm.scopes_supported:
                    scopes = " ".join(oasm.scopes_supported)
                return (
                    str(oasm.authorization_endpoint),
                    str(oasm.token_endpoint),
                    reg_ep,
                    scopes,
                )

    raise RuntimeError(f"Could not discover OAuth metadata for {server_url}")


async def register_client(
    registration_endpoint: str,
    redirect_uri: str,
    client_name: str,
    scopes: str = "",
) -> tuple[str, str]:
    """Dynamic client registration (RFC 7591).

    Returns (client_id, client_secret).
    """
    body: dict[str, object] = {
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    if scopes:
        body["scope"] = scopes

    async with httpx.AsyncClient() as client:
        resp = await client.post(registration_endpoint, json=body)

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"Client registration failed ({resp.status_code}): {resp.text}"
        )

    data = resp.json()
    return data["client_id"], data.get("client_secret", "")


def build_authorization_url(pending: PendingOAuth) -> str:
    """Build the full authorization URL with PKCE and state."""
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": pending.client_id,
        "redirect_uri": pending.redirect_uri,
        "state": pending.state,
        "code_challenge": pending.code_challenge,
        "code_challenge_method": "S256",
    }
    if pending.scopes:
        params["scope"] = pending.scopes

    return f"{pending.authorization_endpoint}?{urlencode(params)}"


async def exchange_code(pending: PendingOAuth, code: str) -> dict[str, object]:
    """Exchange an authorization code for tokens.

    Returns the full token response dict (access_token, token_type, etc.).
    """
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": pending.redirect_uri,
        "client_id": pending.client_id,
        "code_verifier": pending.code_verifier,
    }
    if pending.client_secret:
        data["client_secret"] = pending.client_secret

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            pending.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Token exchange failed ({resp.status_code}): {resp.text}")

    return resp.json()


async def refresh_access_token(
    token_endpoint: str,
    refresh_token: str,
    client_id: str,
    client_secret: str = "",
) -> dict[str, object]:
    """Refresh an access token. Returns the new token response dict."""
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Token refresh failed ({resp.status_code}): {resp.text}")

    return resp.json()
