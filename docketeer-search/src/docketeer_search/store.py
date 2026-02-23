"""Vector storage and retrieval backed by SQLite + numpy cosine similarity."""

import sqlite3
from pathlib import Path

import numpy as np

from docketeer.search import SearchResult
from docketeer_search.embedding import DIMENSIONS


class VectorStore:
    """SQLite-backed vector store with numpy brute-force search.

    Vectors are stored as raw float32 blobs in a regular SQLite table.
    Queries load all vectors and compute cosine similarity in numpy,
    which is sub-millisecond at workspace scale (hundreds of files).
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._ensure_tables()

    def __enter__(self) -> "VectorStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self._db.close()

    def _ensure_tables(self) -> None:
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                path TEXT PRIMARY KEY,
                snippet TEXT NOT NULL,
                embedding BLOB NOT NULL
            )
        """)
        self._db.commit()

    def upsert(self, path: str, vector: np.ndarray, snippet: str) -> None:
        blob = vector.astype(np.float32).tobytes()
        self._db.execute(
            "INSERT OR REPLACE INTO documents (path, snippet, embedding) "
            "VALUES (?, ?, ?)",
            (path, snippet, blob),
        )
        self._db.commit()

    def remove(self, path: str) -> None:
        self._db.execute("DELETE FROM documents WHERE path = ?", (path,))
        self._db.commit()

    def query(self, vector: np.ndarray, limit: int = 10) -> list[SearchResult]:
        rows = self._db.execute(
            "SELECT path, snippet, embedding FROM documents"
        ).fetchall()
        if not rows:
            return []

        paths = [r[0] for r in rows]
        snippets = [r[1] for r in rows]
        vectors = np.array([np.frombuffer(r[2], dtype=np.float32) for r in rows])

        query_vec = vector.astype(np.float32).reshape(1, DIMENSIONS)
        norms = np.linalg.norm(vectors, axis=1) * np.linalg.norm(query_vec)
        norms = np.where(norms == 0, 1.0, norms)
        similarities = (vectors @ query_vec.T).squeeze() / norms

        top_indices = np.argsort(-similarities)[:limit]
        return [
            SearchResult(
                path=paths[i], score=float(similarities[i]), snippet=snippets[i]
            )
            for i in top_indices
            if similarities[i] > 0
        ]

    def list_paths(self) -> set[str]:
        rows = self._db.execute("SELECT path FROM documents").fetchall()
        return {row[0] for row in rows}
