"""CommandExecutor ABC and supporting types for sandboxed process execution."""

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from docketeer.plugins import discover_one

log = logging.getLogger(__name__)


@dataclass
class Mount:
    """A filesystem mount to expose inside the sandbox."""

    source: Path
    target: Path
    writable: bool = False


@dataclass
class ClaudeInvocation:
    """Everything the executor needs to launch claude -p in a sandbox."""

    claude_args: list[str] = field(default_factory=list)
    claude_dir: Path = Path()
    workspace: Path = Path()
    mcp_socket_path: Path | None = None


@dataclass
class CompletedProcess:
    """Result of a finished subprocess."""

    returncode: int
    stdout: bytes
    stderr: bytes


class RunningProcess:
    """Wrapper around an asyncio subprocess, providing a clean interface."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process

    @property
    def pid(self) -> int | None:
        return self._process.pid

    @property
    def stdin(self) -> asyncio.StreamWriter | None:
        return self._process.stdin

    @property
    def stdout(self) -> asyncio.StreamReader | None:
        return self._process.stdout

    @property
    def stderr(self) -> asyncio.StreamReader | None:
        return self._process.stderr

    @property
    def returncode(self) -> int | None:
        return self._process.returncode

    async def wait(self) -> CompletedProcess:
        stdout, stderr = await self._process.communicate()
        return CompletedProcess(
            returncode=self._process.returncode or 0,
            stdout=stdout or b"",
            stderr=stderr or b"",
        )

    async def wait_for_exit(self) -> int:
        """Wait for the process to exit without consuming stdout/stderr.

        Use this when stdout has already been consumed (e.g. by stream_response).
        """
        await self._process.wait()
        return self._process.returncode or 0

    def terminate(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self._process.terminate()

    def kill(self) -> None:
        with contextlib.suppress(ProcessLookupError):
            self._process.kill()


class CommandExecutor(ABC):
    """Abstract base for sandboxed command execution."""

    @abstractmethod
    async def start(
        self,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
        username: str | None = None,
    ) -> RunningProcess: ...

    async def start_claude(
        self,
        invocation: ClaudeInvocation,
        *,
        env: dict[str, str] | None = None,
    ) -> RunningProcess:
        raise NotImplementedError(
            f"{type(self).__name__} does not support running Claude Code"
        )


def discover_executor() -> CommandExecutor | None:
    """Discover the command executor via entry_points (optional)."""
    ep = discover_one("docketeer.executor", "EXECUTOR")
    if ep is None:
        log.info("No executor plugin installed — sandboxed execution unavailable")
        return None
    module = ep.load()
    return module.create_executor()
