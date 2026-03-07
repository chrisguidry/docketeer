"""Shared test fixtures for docketeer-agentskills."""

from pathlib import Path

import pytest

from docketeer.tools import ToolContext


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "memory"
    ws.mkdir()
    return ws


@pytest.fixture()
def skills_dir(workspace: Path) -> Path:
    d = workspace / "skills"
    d.mkdir()
    return d


@pytest.fixture()
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(workspace=workspace, room_id="room1")
