"""CLI for search index management."""

import argparse
import logging
import sys
from pathlib import Path

from docketeer import environment
from docketeer_search.embedding import Embedder
from docketeer_search.store import VectorStore

log = logging.getLogger(__name__)

SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".mypy_cache", ".venv", "node_modules", "tmp"}
)


def _is_text_file(path: Path) -> bool:
    """Check whether a file is likely a text file by reading a small sample."""
    try:
        with path.open("rb") as f:
            chunk = f.read(8_192)
        chunk.decode("utf-8")
    except (UnicodeDecodeError, OSError):
        return False
    return True


def _walk_workspace(workspace: Path) -> list[Path]:
    """Walk workspace for indexable text files, skipping noise directories."""
    files: list[Path] = []
    for entry in sorted(workspace.rglob("*")):
        rel = entry.relative_to(workspace)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if entry.is_file() and _is_text_file(entry):
            files.append(entry)
    return files


def reindex(workspace: Path) -> int:
    """Rebuild the search index from scratch."""
    db_path = environment.DATA_DIR / "search" / "workspace.db"

    files = _walk_workspace(workspace)
    if not files:
        print("No text files found in workspace.")
        return 0

    embedder = Embedder()

    with VectorStore(db_path) as store:
        existing = store.list_paths()
        current: set[str] = set()
        indexed = 0

        for file_path in files:
            rel = str(file_path.relative_to(workspace))
            current.add(rel)
            content = file_path.read_text()
            if not content.strip():
                continue
            vector = embedder.embed([content])[0]
            store.upsert(rel, vector, content[:500])
            indexed += 1
            print(f"  indexed: {rel}")

        stale = existing - current
        for path in sorted(stale):
            store.remove(path)
            print(f"  removed: {path}")

    print(f"Indexed {indexed} file(s), removed {len(stale)} stale entries.")
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="docketeer-search",
        description="Manage the Docketeer semantic search index",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("reindex", help="Rebuild the search index from scratch")

    args = parser.parse_args()

    if args.command == "reindex":
        logging.basicConfig(level=logging.INFO)
        workspace = environment.WORKSPACE_PATH
        if not workspace.exists():
            print(f"Workspace not found: {workspace}", file=sys.stderr)
            sys.exit(1)
        reindex(workspace)
    else:
        parser.print_help()
