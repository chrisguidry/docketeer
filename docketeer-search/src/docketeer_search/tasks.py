"""Docket task handlers for search indexing."""

import logging
from pathlib import Path

from docketeer.dependencies import WorkspacePath
from docketeer_search.embedding import Embedder
from docketeer_search.store import VectorStore

log = logging.getLogger(__name__)

SNIPPET_LENGTH = 500


def _db_path(index_name: str) -> Path:
    """Derive the index DB path from the index name."""
    from docketeer import environment

    return environment.DATA_DIR / "search" / f"{index_name}.db"


async def do_index_file(
    path: str,
    index_name: str = "workspace",
    workspace: Path = WorkspacePath(),
) -> None:
    """Embed and store a single file."""
    full_path = workspace / path
    if not full_path.exists():
        log.debug("Skipping missing file: %s", path)
        return

    try:
        content = full_path.read_text()
    except UnicodeDecodeError:
        log.debug("Skipping binary file: %s", path)
        return

    if not content.strip():
        log.debug("Skipping empty file: %s", path)
        return

    embedder = Embedder()
    with VectorStore(_db_path(index_name)) as store:
        vector = embedder.embed([content])[0]
        store.upsert(path, vector, content[:SNIPPET_LENGTH])
        log.info("Indexed: %s (index=%s)", path, index_name)


async def do_remove_file(
    path: str,
    index_name: str = "workspace",
    workspace: Path = WorkspacePath(),
) -> None:
    """Remove a file from the search index."""
    with VectorStore(_db_path(index_name)) as store:
        store.remove(path)
        log.info("Removed from index: %s (index=%s)", path, index_name)


search_tasks = [do_index_file, do_remove_file]
