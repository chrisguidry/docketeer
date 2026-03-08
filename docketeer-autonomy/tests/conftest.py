"""Shared test fixtures for docketeer-autonomy."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer import environment
from docketeer.tools import ToolContext, registry


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path) -> Iterator[None]:
    """Isolate tests from the real data directory."""
    data_dir = tmp_path / "data"
    ws_dir = data_dir / "memory"
    registry.template_vars.setdefault("workspace", str(ws_dir))
    registry.template_vars.setdefault("scratch", "/tmp")
    with (
        patch.object(environment, "DATA_DIR", data_dir),
        patch.object(environment, "WORKSPACE_PATH", ws_dir),
        patch.object(environment, "AUDIT_PATH", data_dir / "audit"),
        patch.object(environment, "USAGE_PATH", data_dir / "token-usage"),
    ):
        yield


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "data" / "memory"
    ws.mkdir(parents=True)
    return ws


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, chat_room="room1")
