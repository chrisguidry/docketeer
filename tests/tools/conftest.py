"""Fixtures unique to tool tests."""

import pytest

from docketeer.tools import ToolContext


@pytest.fixture()
def ctx(tool_context: ToolContext) -> ToolContext:
    return tool_context
