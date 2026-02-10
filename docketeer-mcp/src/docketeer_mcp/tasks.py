"""Docket task functions for MCP OAuth token refresh."""

import logging
from datetime import datetime, timedelta

from docket import Docket

from docketeer.dependencies import CurrentDocket, CurrentVault
from docketeer.vault import Vault

from .oauth import refresh_access_token

log = logging.getLogger(__name__)


async def mcp_oauth_refresh(
    token_secret: str,
    token_endpoint: str,
    client_id: str,
    client_secret: str = "",
    expires_in: int = 3600,
    vault: Vault = CurrentVault(),
    docket: Docket = CurrentDocket(),
) -> None:
    """Refresh an OAuth access token and reschedule for the next refresh."""
    try:
        refresh_token = await vault.resolve(f"{token_secret}/refresh")
    except Exception:
        log.exception("Could not resolve refresh token for %s", token_secret)
        return

    try:
        tokens = await refresh_access_token(
            token_endpoint, refresh_token, client_id, client_secret
        )
    except Exception:
        log.exception("Token refresh failed for %s", token_secret)
        return

    access_token = str(tokens.get("access_token", ""))
    if access_token:
        await vault.store(token_secret, access_token)

    new_refresh = str(tokens.get("refresh_token", ""))
    if new_refresh:
        await vault.store(f"{token_secret}/refresh", new_refresh)

    new_expires = int(str(tokens.get("expires_in", expires_in)))

    fire_at = datetime.now().astimezone() + timedelta(
        seconds=max(new_expires - 300, 60)
    )
    await docket.add(
        mcp_oauth_refresh, when=fire_at, key=f"mcp-refresh-{token_secret}"
    )(
        token_secret=token_secret,
        token_endpoint=token_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        expires_in=new_expires,
    )


mcp_tasks = [mcp_oauth_refresh]

mcp_task_collections = ["docketeer_mcp.tasks:mcp_tasks"]
