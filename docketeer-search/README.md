# docketeer-search

Semantic workspace search plugin for [Docketeer](https://github.com/chrisguidry/docketeer).

Uses [fastembed](https://github.com/qdrant/fastembed) (ONNX-based, CPU-only) for
text embeddings and [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector
storage and retrieval.

## What it provides

- **`docketeer.search` entry point** — a `SearchIndex` implementation that
  hooks into `write_file`/`delete_file` for automatic async indexing via docket
- **`semantic_search` tool** — lets the agent search workspace files by meaning
- **`docketeer-search reindex` CLI** — full workspace reindex for initial setup
  or recovery

## Usage

Install alongside docketeer:

```sh
uv add docketeer-search
```

Build the initial index:

```sh
docketeer-search reindex
```

The agent will keep the index current as it writes and deletes files. The
`semantic_search` tool is automatically available.
