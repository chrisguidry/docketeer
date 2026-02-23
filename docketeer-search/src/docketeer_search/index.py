"""FastembedSearch — the SearchIndex implementation."""

from docket import Docket

from docketeer import environment
from docketeer.search import SearchIndex, SearchResult
from docketeer_search.embedding import Embedder
from docketeer_search.store import VectorStore

INDEX_TASK = "docketeer_search.tasks:do_index_file"
REMOVE_TASK = "docketeer_search.tasks:do_remove_file"


class FastembedSearch(SearchIndex):
    """Semantic search index using fastembed embeddings and sqlite-vec storage.

    Queries run inline (embedding + KNN lookup). Indexing is dispatched as
    docket tasks so write_file/delete_file return immediately.
    """

    def __init__(self, docket: Docket) -> None:
        self._docket = docket
        db_path = environment.DATA_DIR / "search" / "index.db"
        self._embedder = Embedder()
        self._store = VectorStore(db_path)

    def __enter__(self) -> "FastembedSearch":
        return self

    def __exit__(self, *_exc: object) -> None:
        self._store.__exit__()

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        vector = self._embedder.embed([query])[0]
        return self._store.query(vector, limit)

    async def index_file(self, path: str, content: str) -> None:
        schedule = self._docket.add(INDEX_TASK, key=f"search:index:{path}")
        await schedule(path=path)

    async def remove_file(self, path: str) -> None:
        schedule = self._docket.add(REMOVE_TASK, key=f"search:remove:{path}")
        await schedule(path=path)
