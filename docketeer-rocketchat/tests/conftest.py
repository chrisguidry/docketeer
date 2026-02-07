"""Shared fixtures for docketeer-rocketchat tests."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from docketeer.tools import ToolContext, registry
from docketeer_rocketchat.client import RocketChatClient


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")


@pytest.fixture()
def rc() -> RocketChatClient:
    """RocketChatClient with pre-configured httpx client (no real connect)."""
    client = RocketChatClient()
    client._user_id = "bot_uid"
    client._http = httpx.AsyncClient(base_url="http://localhost:3000/api/v1", timeout=5)
    return client


@pytest.fixture(autouse=True)
def _save_registry() -> Iterator[None]:
    """Save and restore the tool registry around each test."""
    original_tools = registry._tools.copy()
    original_schemas = registry._schemas.copy()
    yield
    registry._tools = original_tools
    registry._schemas = original_schemas
