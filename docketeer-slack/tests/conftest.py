from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from docketeer.tools import ToolContext, registry
from docketeer_slack.client import SlackClient


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, chat_room="C1")


@pytest.fixture()
def slack_client() -> SlackClient:
    client = SlackClient()
    client._user_id = "U_BOT"
    client._team_id = "T1"
    client.username = "dobby"
    client._http = httpx.AsyncClient(timeout=5)
    return client


@pytest.fixture(autouse=True)
def _save_registry() -> Iterator[None]:
    original_tools = registry._tools.copy()
    original_schemas = registry._schemas.copy()
    yield
    registry._tools = original_tools
    registry._schemas = original_schemas
