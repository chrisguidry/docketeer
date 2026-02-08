"""Custom MCP transport using the CommandExecutor abstraction."""

import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from fastmcp.client.transports import ClientTransport
from mcp import ClientSession
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from docketeer.executor import CommandExecutor, Mount, RunningProcess

log = logging.getLogger(__name__)


class ExecutorTransport(ClientTransport):
    """Launches an MCP server through a CommandExecutor and speaks stdio JSONRPC."""

    def __init__(
        self,
        executor: CommandExecutor,
        command: list[str],
        env: dict[str, str] | None = None,
        mounts: list[Mount] | None = None,
        network_access: bool = False,
    ) -> None:
        self._executor = executor
        self._command = command
        self._env = env
        self._mounts = mounts
        self._network_access = network_access

    @contextlib.asynccontextmanager
    async def connect_session(
        self, **session_kwargs: Any
    ) -> AsyncIterator[ClientSession]:
        label = self._command[0] if self._command else "unknown"
        log.info("Starting MCP server: %s", " ".join(self._command))

        process = await self._executor.start(
            self._command,
            env=self._env or None,
            mounts=self._mounts or None,
            network_access=self._network_access,
        )
        try:
            read_send, read_recv = anyio.create_memory_object_stream[
                SessionMessage | Exception
            ](0)
            write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](
                0
            )

            async with anyio.create_task_group() as tg:
                tg.start_soon(_stdout_reader, process, read_send)
                tg.start_soon(_stdin_writer, process, write_recv)
                tg.start_soon(_stderr_logger, process, label)

                try:
                    async with read_recv, write_send:
                        async with ClientSession(
                            read_recv, write_send, **session_kwargs
                        ) as session:
                            yield session
                finally:
                    tg.cancel_scope.cancel()
        finally:
            log.info("Terminating MCP server: %s", " ".join(self._command))
            process.terminate()


async def _stdout_reader(
    process: RunningProcess,
    send_stream: MemoryObjectSendStream[SessionMessage | Exception],
) -> None:
    """Read newline-delimited JSONRPC from the process stdout into the memory stream."""
    assert process.stdout is not None
    async with send_stream:
        buffer = b""
        while True:
            chunk = await process.stdout.read(65_536)
            if not chunk:
                break
            lines = (buffer + chunk).split(b"\n")
            buffer = lines.pop()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    message = JSONRPCMessage.model_validate_json(line)
                except Exception as exc:
                    await send_stream.send(exc)
                    continue
                await send_stream.send(SessionMessage(message))


async def _stdin_writer(
    process: RunningProcess,
    recv_stream: MemoryObjectReceiveStream[SessionMessage],
) -> None:
    """Read SessionMessages from the memory stream and write as JSONRPC to process stdin."""
    assert process.stdin is not None
    async with recv_stream:
        async for session_message in recv_stream:
            data = session_message.message.model_dump_json(
                by_alias=True, exclude_none=True
            )
            process.stdin.write((data + "\n").encode())
            await process.stdin.drain()


async def _stderr_logger(
    process: RunningProcess,
    label: str,
) -> None:
    """Read stderr from the MCP server process and log it."""
    if not process.stderr:
        return
    while True:
        chunk = await process.stderr.read(65_536)
        if not chunk:
            break
        for line in chunk.decode(errors="replace").splitlines():
            line = line.strip()
            if line:
                log.info("[%s] %s", label, line)
