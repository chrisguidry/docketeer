"""Search index ABC and discovery for semantic workspace search."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from docketeer.plugins import discover_one

log = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A ranked result from a semantic search query."""

    path: str
    score: float
    snippet: str


class SearchIndex(ABC):
    """Abstract base for workspace search indexing and querying."""

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[SearchResult]: ...

    @abstractmethod
    async def index_file(self, path: str, content: str) -> None: ...

    @abstractmethod
    async def remove_file(self, path: str) -> None: ...


class NullSearch(SearchIndex):
    """No-op search index for when no search plugin is installed."""

    async def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        return []

    async def index_file(self, path: str, content: str) -> None:
        pass

    async def remove_file(self, path: str) -> None:
        pass


class SearchCatalog(ABC):
    """A catalog of named search indices."""

    @abstractmethod
    def get_index(self, name: str) -> SearchIndex:
        """Return a SearchIndex for the given namespace.

        Creates the index on first access. Each name gets an independent
        index with its own storage.
        """
        ...


class NullCatalog(SearchCatalog):
    """No-op catalog for when no search plugin is installed."""

    def get_index(self, name: str) -> SearchIndex:
        return NullSearch()


def discover_search(**kwargs: object) -> SearchCatalog:
    """Discover the search catalog via entry_points.

    Returns NullCatalog when no plugin is installed, so callers always
    get a usable SearchCatalog without null checks.
    """
    ep = discover_one("docketeer.search", "SEARCH")
    if ep is None:
        log.info("No search plugin installed — semantic search unavailable")
        return NullCatalog()
    module = ep.load()
    return module.create_search(**kwargs)
