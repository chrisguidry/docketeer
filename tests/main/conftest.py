"""Fixtures unique to main module tests."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from docketeer.testing import MemoryChat
from docketeer.tools import registry


@pytest.fixture()
def chat() -> MemoryChat:
    return MemoryChat()


@pytest.fixture(autouse=True)
def _save_registry() -> Iterator[None]:
    """Save and restore the tool registry around each test."""
    original_tools = registry._tools.copy()
    original_schemas = registry._schemas.copy()
    yield
    registry._tools = original_tools
    registry._schemas = original_schemas


@pytest.fixture(autouse=True)
def _reset_lock_file() -> Iterator[None]:
    """Reset the global _lock_file between tests."""
    import docketeer.main as m

    original = m._lock_file
    m._lock_file = None
    yield
    if m._lock_file is not None:
        m._lock_file.close()
    m._lock_file = original


@pytest.fixture()
def mock_docket() -> MagicMock:
    docket = MagicMock()
    docket.replace.return_value = AsyncMock()
    docket.add.return_value = AsyncMock()
    docket.cancel = AsyncMock()
    docket.snapshot = AsyncMock()
    return docket
