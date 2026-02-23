# docketeer-search

Semantic workspace search plugin. Registers `docketeer.search` (single-select),
`docketeer.tools` for the `semantic_search` tool, and `docketeer.tasks` for
async file indexing via docket.

## Architecture

Three layers, bottom-up:

- **`embedding.py`** — thin wrapper around fastembed's `TextEmbedding` with
  lazy model loading. Uses `BAAI/bge-small-en-v1.5` (384 dims, ~50MB).
- **`store.py`** — `VectorStore` backed by plain SQLite + numpy cosine
  similarity. No SQLite extensions needed. Brute-force search is
  sub-millisecond at workspace scale.
- **`index.py`** — `FastembedSearch(SearchIndex)` composes the above two.
  Search queries run inline. Writes dispatch docket tasks for async indexing.

Supporting modules:

- **`tasks.py`** — docket task handlers (`do_index_file`, `do_remove_file`).
  Each invocation creates its own `Embedder` and `VectorStore`.
- **`tools.py`** — registers the `semantic_search` agent tool.
- **`cli.py`** — `docketeer-search reindex` for full workspace rebuilds.

## Data flow

```
write_file → ctx.search.index_file(path, content)
           → docket.add(do_index_file, key="search:index:{path}")
           → [async worker] embed + store in SQLite

semantic_search → ctx.search.search(query)
               → embed query → numpy cosine sim → ranked results
```

## Testing

All tests use `FakeEmbedder` (in conftest.py) — deterministic SHA-256-based
vectors, no model download. The `VectorStore` uses real SQLite via `tmp_path`.
Mock the `Embedder` class when testing tasks and CLI, not the store.

The `_db_path` helper in tasks.py exists so tests can redirect the DB location
without patching `environment.DATA_DIR` in every test.
