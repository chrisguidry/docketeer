"""CommandExecutor ABC and supporting types for sandboxed process execution."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Mount:
    """A filesystem mount to expose inside the sandbox."""

    source: Path
    target: Path
    writable: bool = False


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

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
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
