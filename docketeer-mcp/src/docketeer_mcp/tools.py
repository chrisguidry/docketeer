"""Agent-facing MCP tools."""

import json
import logging
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
from docket import Docket

from docketeer.tools import ToolContext, registry

from . import config
from .manager import manager
from .oauth import (
    REDIRECT_URI,
    PendingOAuth,
    _generate_pkce,
    build_authorization_url,
    discover_oauth_metadata,
    exchange_code,
    register_client,
)

log = logging.getLogger(__name__)


async def _check_auth_required(url: str) -> bool:
    """Probe an HTTP MCP server to see if it returns 401."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, timeout=10)
            return resp.status_code == 401
    except Exception:
        return False


def current_docket() -> Docket:
    """Resolve the current Docket from dependencies."""
    from docketeer.dependencies import _docket_var

    return _docket_var.get()


@registry.tool
async def list_mcp_servers(ctx: ToolContext) -> str:
    """List configured MCP servers and their connection status."""
    servers = config.load_servers()
    if not servers:
        return "No MCP servers configured."

    connected = manager.connected_servers()
    lines = []
    for name, cfg in servers.items():
        kind = cfg.command if cfg.is_stdio else cfg.url
        status = (
            f"connected ({connected[name]} tools)"
            if name in connected
            else "disconnected"
        )
        lines.append(f"- **{name}**: `{kind}` — {status}")
    return "\n".join(lines)


@registry.tool
async def connect_mcp_server(
    ctx: ToolContext,
    name: str,
    client_id: str = "",
    client_secret: str = "",
    scopes: str = "",
) -> str:
    """Connect to a configured MCP server and discover its tools. If the
    server requires OAuth, returns an authorization URL for the user.

    name: server name from the configuration
    client_id: pre-configured OAuth client ID (optional, skips registration)
    client_secret: pre-configured OAuth client secret (optional)
    scopes: OAuth scopes to request (optional)
    """
    if manager.is_connected(name):
        return f"Already connected to {name!r}."

    servers = config.load_servers()
    cfg = servers.get(name)
    if not cfg:
        return f"No server configured with name {name!r}."

    # If config has an auth secret, resolve from vault and connect with bearer
    if cfg.auth:
        if not ctx.vault:
            return f"Server {name!r} requires auth but no vault is configured."
        try:
            token = await ctx.vault.resolve(cfg.auth)
        except Exception as e:
            return f"Failed to resolve auth secret {cfg.auth!r}: {e}"

        try:
            tools = await manager.connect(
                name, cfg, ctx.executor, ctx.workspace, auth=token
            )
        except Exception as e:
            log.warning("Failed to connect to MCP server %r", name, exc_info=True)
            return f"Failed to connect to {name!r}: {e}"

        if not tools:
            return f"Connected to {name!r} — no tools found."
        lines = [f"Connected to {name!r} — {len(tools)} tools:"]
        for t in tools:
            lines.append(f"- **{t.name}**: {t.description}")
        return "\n".join(lines)

    # For HTTP servers without auth config, check if auth is required
    if cfg.is_http:
        auth_required = await _check_auth_required(cfg.url)
        if auth_required:
            return await _start_oauth_flow(name, cfg, client_id, client_secret, scopes)

    # No auth needed — connect normally
    try:
        tools = await manager.connect(name, cfg, ctx.executor, ctx.workspace)
    except Exception as e:
        log.warning("Failed to connect to MCP server %r", name, exc_info=True)
        return f"Failed to connect to {name!r}: {e}"

    if not tools:
        return f"Connected to {name!r} — no tools found."

    lines = [f"Connected to {name!r} — {len(tools)} tools:"]
    for t in tools:
        lines.append(f"- **{t.name}**: {t.description}")
    return "\n".join(lines)


async def _start_oauth_flow(
    name: str,
    cfg: config.MCPServerConfig,
    client_id: str,
    client_secret: str,
    scopes: str,
) -> str:
    """Discover OAuth metadata, register if needed, store pending state."""
    try:
        auth_ep, token_ep, reg_ep, discovered_scopes = await discover_oauth_metadata(
            cfg.url
        )
    except Exception as e:
        return f"OAuth discovery failed for {name!r}: {e}"

    effective_scopes = scopes or discovered_scopes or ""

    if not client_id:
        if reg_ep:
            try:
                client_id, client_secret = await register_client(
                    reg_ep, REDIRECT_URI, f"docketeer-{name}", effective_scopes
                )
            except Exception as e:
                return f"Client registration failed for {name!r}: {e}"
        else:
            return (
                f"Server {name!r} requires OAuth but has no registration endpoint. "
                f"Provide client_id (and client_secret) when connecting."
            )

    verifier, challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)

    pending = PendingOAuth(
        server_url=cfg.url,
        authorization_endpoint=auth_ep,
        token_endpoint=token_ep,
        code_verifier=verifier,
        code_challenge=challenge,
        state=state,
        redirect_uri=REDIRECT_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=effective_scopes,
    )

    manager._pending_oauth[name] = pending
    auth_url = build_authorization_url(pending)

    return (
        f"Authorization needed for {name!r}.\n\n"
        f"Send this URL to the user:\n{auth_url}\n\n"
        f"After they authorize, use `mcp_oauth_complete` with the redirect URL."
    )


@registry.tool
async def mcp_oauth_complete(
    ctx: ToolContext,
    server: str,
    redirect_url: str,
    token_secret: str,
) -> str:
    """Complete an OAuth flow by exchanging the authorization code for tokens.

    server: the MCP server name from the pending OAuth flow
    redirect_url: the full redirect URL the user was sent to (contains code and state)
    token_secret: vault secret path to store the access token (e.g. mcp/github/token)
    """
    if not ctx.vault:
        return "No vault configured — cannot store OAuth tokens."

    pending = manager._pending_oauth.get(server)
    if not pending:
        return f"No pending OAuth flow found for {server!r}."

    # Parse code and state from redirect URL
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]

    if not code:
        return "No authorization code found in the redirect URL."

    if not secrets.compare_digest(state, pending.state):
        return "State mismatch — the redirect URL doesn't match the pending flow."

    # Exchange code for tokens
    try:
        tokens = await exchange_code(pending, code)
    except Exception as e:
        return f"Token exchange failed: {e}"

    access_token = str(tokens.get("access_token", ""))
    if not access_token:
        return "Token exchange succeeded but no access_token in response."

    # Store access token in vault
    await ctx.vault.store(token_secret, access_token)

    # Update server config with auth secret path
    servers = config.load_servers()
    cfg = servers.get(server)
    if cfg:
        cfg.auth = token_secret
        config.save_server(cfg)

    # Clean up pending state
    del manager._pending_oauth[server]

    # Handle refresh token if present
    refresh_token = str(tokens.get("refresh_token", ""))
    if refresh_token:
        await ctx.vault.store(f"{token_secret}/refresh", refresh_token)
        await ctx.vault.store(f"{token_secret}/client_id", pending.client_id)
        await ctx.vault.store(f"{token_secret}/client_secret", pending.client_secret)
        await ctx.vault.store(f"{token_secret}/token_endpoint", pending.token_endpoint)

        expires_in = int(str(tokens.get("expires_in", 3600)))
        try:
            await _schedule_token_refresh(
                token_secret,
                pending.token_endpoint,
                pending.client_id,
                pending.client_secret,
                expires_in,
            )
        except Exception:
            log.warning("Could not schedule token refresh", exc_info=True)

    return f"OAuth complete for {server!r}. Token stored at {token_secret!r}."


async def _schedule_token_refresh(
    token_secret: str,
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    expires_in: int,
) -> None:
    """Schedule a one-shot refresh task before the token expires."""
    from datetime import datetime, timedelta

    from .tasks import mcp_oauth_refresh

    docket = current_docket()
    fire_at = datetime.now().astimezone() + timedelta(seconds=max(expires_in - 300, 60))
    await docket.add(
        mcp_oauth_refresh, when=fire_at, key=f"mcp-refresh-{token_secret}"
    )(
        token_secret=token_secret,
        token_endpoint=token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        expires_in=expires_in,
    )


@registry.tool
async def disconnect_mcp_server(ctx: ToolContext, name: str) -> str:
    """Disconnect from a connected MCP server.

    name: server name to disconnect
    """
    if not manager.is_connected(name):
        return f"Not connected to {name!r}."
    await manager.disconnect(name)
    return f"Disconnected from {name!r}."


@registry.tool
async def search_mcp_tools(ctx: ToolContext, query: str, server: str = "") -> str:
    """Search connected MCP servers for tools matching a query.

    query: search term to match against tool names and descriptions
    server: optional server name to limit the search to
    """
    results = manager.search_tools(query, server=server)
    if not results:
        return f"No tools matching {query!r}."

    lines = []
    for t in results:
        lines.append(f"### {t.server} / {t.name}")
        if t.description:
            lines.append(t.description)
        lines.append(f"```json\n{json.dumps(t.input_schema, indent=2)}\n```")
        lines.append("")
    return "\n".join(lines)


@registry.tool
async def use_mcp_tool(
    ctx: ToolContext, server: str, tool: str, arguments: str = "{}"
) -> str:
    """Call a tool on a connected MCP server.

    server: server name
    tool: tool name on that server
    arguments: JSON string of tool arguments
    """
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError as e:
        return f"Invalid JSON arguments: {e}"

    try:
        return await manager.call_tool(server, tool, args)
    except Exception as e:
        return f"Error calling {server}/{tool}: {e}"


@registry.tool
async def add_mcp_server(
    ctx: ToolContext,
    name: str,
    command: str = "",
    args: str = "[]",
    env: str = "{}",
    url: str = "",
    headers: str = "{}",
    network_access: bool = False,
) -> str:
    """Save a new MCP server configuration.

    name: identifier for the server
    command: executable to run (for stdio servers)
    args: JSON array of command arguments
    env: JSON object of environment variables
    url: server URL (for HTTP servers)
    headers: JSON object of HTTP headers
    network_access: whether the server needs network access (stdio only)
    """
    try:
        args_list = json.loads(args)
    except json.JSONDecodeError as e:
        return f"Invalid args JSON: {e}"

    try:
        env_dict = json.loads(env)
    except json.JSONDecodeError as e:
        return f"Invalid env JSON: {e}"

    try:
        headers_dict = json.loads(headers)
    except json.JSONDecodeError as e:
        return f"Invalid headers JSON: {e}"

    if not command and not url:
        return "Must provide either command (stdio) or url (HTTP)."

    cfg = config.MCPServerConfig(
        name=name,
        command=command,
        args=args_list,
        env=env_dict,
        url=url,
        headers=headers_dict,
        network_access=network_access,
    )
    try:
        config.save_server(cfg)
    except ValueError as e:
        return str(e)

    kind = f"command `{command}`" if command else f"url `{url}`"
    return f"Saved server {name!r} ({kind})."


@registry.tool
async def remove_mcp_server(ctx: ToolContext, name: str) -> str:
    """Remove an MCP server configuration.

    name: server name to remove
    """
    if manager.is_connected(name):
        await manager.disconnect(name)

    servers = config.load_servers()
    cfg = servers.get(name)
    if cfg and cfg.auth:
        try:
            docket = current_docket()
            await docket.cancel(f"mcp-refresh-{cfg.auth}")
        except Exception:
            log.debug("Could not cancel refresh task for %s", name, exc_info=True)

    if config.remove_server(name):
        return f"Removed server {name!r}."
    return f"No server configured with name {name!r}."
