"""Shared test fixtures for docketeer-git."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from docketeer import environment


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path) -> Iterator[None]:
    """Isolate tests from the real data directory."""
    with patch.object(environment, "DATA_DIR", tmp_path / "data"):
        yield
