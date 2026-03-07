from docketeer_subprocess.executor import SubprocessExecutor


def create_executor() -> SubprocessExecutor:
    return SubprocessExecutor()


__all__ = ["SubprocessExecutor", "create_executor"]
