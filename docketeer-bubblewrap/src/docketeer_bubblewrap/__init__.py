from docketeer_bubblewrap.executor import BubblewrapExecutor


def create_executor() -> BubblewrapExecutor:
    return BubblewrapExecutor()


__all__ = ["BubblewrapExecutor", "create_executor"]
