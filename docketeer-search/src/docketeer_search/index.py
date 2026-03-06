"""FastembedCatalog — the SearchCatalog implementation."""

from pathlib import Path

from docket import Docket

from docketeer import environment
from docketeer.search import SearchCatalog, SearchIndex, SearchResult
from docketeer_search.embedding import Embedder
from docketeer_search.store import VectorStore

INDEX_TASK = "do_index_file"
REMOVE_TASK = "do_remove_file"


class FastembedIndex(SearchIndex):
    """A single named search index backed by fastembed + sqlite-vec.

    Queries run inline (embedding + KNN lookup). Indexing is dispatched as
    docket tasks so write_file/delete_file return immediately.
    """

    def __init__(
        self, name: str, docket: Docket, embedder: Embedder, db_path: Path
    ) -> None:
        self._name = name
        self._docket = docket
        self._embedder = embedder
        self._store = VectorStore(db_path)

    def close(self) -> None:
        self._store.__exit__()

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        vector = self._embedder.embed([query])[0]
        return self._store.query(vector, limit)

    async def index_file(self, path: str, content: str) -> None:
        schedule = self._docket.add(INDEX_TASK, key=f"search:index:{self._name}:{path}")
        await schedule(index_name=self._name, path=path)

    async def remove_file(self, path: str) -> None:
        schedule = self._docket.add(
            REMOVE_TASK, key=f"search:remove:{self._name}:{path}"
        )
        await schedule(index_name=self._name, path=path)


class FastembedCatalog(SearchCatalog):
    """Fastembed-backed catalog of named search indices."""

    def __init__(self, docket: Docket) -> None:
        self._docket = docket
        self._embedder = Embedder()
        self._indices: dict[str, FastembedIndex] = {}

    def get_index(self, name: str) -> FastembedIndex:
        if name not in self._indices:
            db_path = environment.DATA_DIR / "search" / f"{name}.db"
            self._indices[name] = FastembedIndex(
                name, self._docket, self._embedder, db_path
            )
        return self._indices[name]

    def __enter__(self) -> "FastembedCatalog":
        return self

    def __exit__(self, *_exc: object) -> None:
        for index in self._indices.values():
            index.close()
