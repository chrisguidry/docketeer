"""Shared fixtures for chat tests."""

import httpx
import pytest

from docketeer.chat import RocketClient


@pytest.fixture()
def rc() -> RocketClient:
    """RocketClient with pre-configured httpx client (no real connect)."""
    client = RocketClient("http://localhost:3000", "bot", "pass")
    client._user_id = "bot_uid"
    client._http = httpx.AsyncClient(base_url="http://localhost:3000/api/v1", timeout=5)
    return client
