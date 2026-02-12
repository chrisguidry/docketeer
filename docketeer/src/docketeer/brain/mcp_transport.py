"""Unix domain socket transport for the MCP server.

Mirrors the structure of mcp.server.stdio.stdio_server() but listens on a
Unix socket instead of stdin/stdout.  Provides a two-phase API so the caller
can bind the socket before launching the guest process, then accept after.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

log = logging.getLogger(__name__)


@dataclass
class MCPSocketServer:
    """A Unix socket server that accepts sequential MCP connections."""

    _server: asyncio.Server
    _connections: asyncio.Queue[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        field(default_factory=asyncio.Queue)
    )

    @property
    def is_serving(self) -> bool:
        return self._server.is_serving()

    def close(self) -> None:
        self._server.close()

    async def wait_closed(self) -> None:
        await self._server.wait_closed()


async def bind_mcp_socket(socket_path: Path) -> MCPSocketServer:
    """Bind a Unix domain socket and start listening.

    Cleans up any stale socket file first.  Returns an MCPSocketServer
    so the caller can accept connections later with accept_mcp_connection().
    """
    if socket_path.exists():
        socket_path.unlink()

    connections: asyncio.Queue[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = (
        asyncio.Queue()
    )

    def on_connect(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        connections.put_nowait((reader, writer))

    server = await asyncio.start_unix_server(on_connect, path=str(socket_path))
    mcp_server = MCPSocketServer(_server=server, _connections=connections)
    log.info("MCP socket bound at %s", socket_path)
    return mcp_server


@asynccontextmanager
async def accept_mcp_connection(
    mcp_server: MCPSocketServer,
) -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
    ]
]:
    """Accept one connection and yield the MCP stream pair.

    Blocks until a client connects, then spawns reader/writer tasks that
    relay between the socket and the anyio memory streams that Server.run()
    expects.  Can be called multiple times on the same MCPSocketServer to
    handle sequential connections.
    """
    reader, writer = await mcp_server._connections.get()

    read_send, read_recv = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    write_send, write_recv = anyio.create_memory_object_stream[SessionMessage](0)

    async def socket_reader() -> None:
        async with read_send:
            while True:
                line = await reader.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    message = JSONRPCMessage.model_validate_json(line)
                except Exception as exc:
                    await read_send.send(exc)
                    continue
                await read_send.send(SessionMessage(message))

    async def socket_writer() -> None:
        async with write_recv:
            async for session_message in write_recv:
                data = session_message.message.model_dump_json(
                    by_alias=True, exclude_none=True
                )
                writer.write((data + "\n").encode())
                await writer.drain()

    async with anyio.create_task_group() as tg:
        tg.start_soon(socket_reader)
        tg.start_soon(socket_writer)
        try:
            async with read_recv, write_send:
                yield read_recv, write_send
        finally:
            writer.close()
            tg.cancel_scope.cancel()
