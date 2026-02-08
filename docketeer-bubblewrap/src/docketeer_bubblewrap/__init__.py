from docketeer import environment
from docketeer.toolshed import discover
from docketeer_bubblewrap.executor import BubblewrapExecutor


def create_executor() -> BubblewrapExecutor:
    toolshed = discover(cache_root=environment.DATA_DIR / "toolshed" / "cache")
    return BubblewrapExecutor(toolshed=toolshed)


__all__ = ["BubblewrapExecutor", "create_executor"]
