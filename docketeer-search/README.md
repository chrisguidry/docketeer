# docketeer-search

Semantic search plugin for [Docketeer](https://github.com/chrisguidry/docketeer).

Uses [fastembed](https://github.com/qdrant/fastembed) (ONNX-based, CPU-only) for
text embeddings and [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector
storage and retrieval.

## What it provides

- **`docketeer.search` entry point** — a `SearchCatalog` implementation that
  manages named search indices (e.g. `workspace` for files, `mcp-tools` for
  MCP tool discovery)
- **`docketeer.tasks` entry point** — background tasks for async indexing
  via Docket
- **`docketeer-search reindex` CLI** — full workspace reindex for initial setup
  or recovery

The core `search_files` tool automatically uses semantic search when this
plugin is installed, falling back to keyword grep without it.

## Usage

Install alongside docketeer:

```sh
uv add docketeer-search
```

Build the initial index:

```sh
docketeer-search reindex
```

The agent will keep the index current as it writes and deletes files.
