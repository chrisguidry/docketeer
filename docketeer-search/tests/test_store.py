"""Tests for SQLite + numpy vector storage."""

import numpy as np

from docketeer_search.embedding import DIMENSIONS
from docketeer_search.store import VectorStore


def _random_vector(seed: int = 42) -> np.ndarray:
    v = np.random.default_rng(seed).random(DIMENSIONS, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_upsert_and_query(vector_store: VectorStore):
    vec = _random_vector()
    vector_store.upsert("notes/hello.md", vec, "hello world")

    results = vector_store.query(vec, limit=5)
    assert len(results) == 1
    assert results[0].path == "notes/hello.md"
    assert results[0].snippet == "hello world"
    assert results[0].score > 0.99


def test_upsert_replaces_existing(vector_store: VectorStore):
    vec = _random_vector()
    vector_store.upsert("file.md", vec, "original")
    vector_store.upsert("file.md", vec, "updated")

    results = vector_store.query(vec, limit=5)
    assert len(results) == 1
    assert results[0].snippet == "updated"


def test_remove_deletes_entry(vector_store: VectorStore):
    vec = _random_vector()
    vector_store.upsert("gone.md", vec, "bye")
    vector_store.remove("gone.md")

    results = vector_store.query(vec, limit=5)
    assert len(results) == 0


def test_remove_nonexistent_is_safe(vector_store: VectorStore):
    vector_store.remove("nope.md")


def test_list_paths(vector_store: VectorStore):
    vec = _random_vector()
    vector_store.upsert("a.md", vec, "a")
    vector_store.upsert("b.md", vec, "b")

    assert vector_store.list_paths() == {"a.md", "b.md"}


def test_list_paths_empty(vector_store: VectorStore):
    assert vector_store.list_paths() == set()


def test_query_respects_limit(vector_store: VectorStore):
    for i in range(5):
        v = _random_vector(seed=i)
        vector_store.upsert(f"file{i}.md", v, f"content {i}")

    results = vector_store.query(_random_vector(), limit=2)
    assert len(results) == 2


def test_query_empty_store(vector_store: VectorStore):
    results = vector_store.query(_random_vector(), limit=5)
    assert results == []


def test_query_results_ordered_by_similarity(vector_store: VectorStore):
    target = _random_vector(seed=100)
    close = (
        target + np.random.default_rng(1).random(DIMENSIONS, dtype=np.float32) * 0.01
    )
    close = close / np.linalg.norm(close)
    far = _random_vector(seed=200)

    vector_store.upsert("close.md", close, "close")
    vector_store.upsert("far.md", far, "far")

    results = vector_store.query(target, limit=5)
    assert results[0].path == "close.md"
    assert results[0].score > results[1].score
