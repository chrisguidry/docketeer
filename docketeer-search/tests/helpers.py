"""Shared test helpers for docketeer-search tests."""

import hashlib

import numpy as np

from docketeer_search.embedding import DIMENSIONS, Embedder


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
