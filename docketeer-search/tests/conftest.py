"""Shared fixtures for docketeer-search tests."""

import hashlib
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from docketeer import environment
from docketeer_search.embedding import DIMENSIONS, Embedder
from docketeer_search.store import VectorStore


class FakeEmbedder(Embedder):
    """Deterministic embedder for tests — no model loading."""

    def __init__(self) -> None:
        pass

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._hash_to_vector(t) for t in texts]

    @staticmethod
    def _hash_to_vector(text: str) -> np.ndarray:
        digest = hashlib.sha256(text.encode()).digest()
        raw = np.frombuffer(digest, dtype=np.uint8).astype(np.float32)
        tiled = np.tile(raw, DIMENSIONS // len(raw) + 1)[:DIMENSIONS]
        return tiled / np.linalg.norm(tiled)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path: Path) -> Iterator[None]:
    data_dir = tmp_path / "data"
    ws_dir = data_dir / "memory"
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
def vector_store(tmp_path: Path) -> Iterator[VectorStore]:
    db_path = tmp_path / "data" / "search" / "index.db"
    with VectorStore(db_path) as store:
        yield store
