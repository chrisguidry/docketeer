"""Tests for the Unix socket MCP transport."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from docketeer.brain.mcp_transport import accept_mcp_connection, bind_mcp_socket


@pytest.fixture()
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sock"


async def test_bind_creates_listening_socket(socket_path: Path):
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        assert socket_path.exists()
        assert mcp_server.is_serving
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_bind_cleans_up_stale_socket(socket_path: Path):
    socket_path.touch()
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        assert mcp_server.is_serving
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_client_message_arrives_on_read_stream(socket_path: Path):
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        msg = {"jsonrpc": "2.0", "method": "test", "id": 1}

        async def connect_and_send() -> None:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write((json.dumps(msg) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        task = asyncio.create_task(connect_and_send())
        async with accept_mcp_connection(mcp_server) as (read_stream, write_stream):
            received = await read_stream.receive()
            assert isinstance(received, SessionMessage)
            data = json.loads(
                received.message.model_dump_json(by_alias=True, exclude_none=True)
            )
            assert data["method"] == "test"
            await task
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_write_stream_sends_to_client(socket_path: Path):
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        msg = {"jsonrpc": "2.0", "method": "response", "id": 1}
        received_lines: list[str] = []

        async def connect_and_read() -> None:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            line = await reader.readline()
            received_lines.append(line.decode().strip())
            writer.close()
            await writer.wait_closed()

        task = asyncio.create_task(connect_and_read())
        async with accept_mcp_connection(mcp_server) as (read_stream, write_stream):
            await asyncio.sleep(0.02)
            session_msg = SessionMessage(JSONRPCMessage.model_validate(msg))
            await write_stream.send(session_msg)
            await task

        assert len(received_lines) == 1
        parsed = json.loads(received_lines[0])
        assert parsed["method"] == "response"
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_bidirectional_exchange(socket_path: Path):
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        reply_lines: list[str] = []

        async def client_exchange() -> None:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            request = {"jsonrpc": "2.0", "method": "ping", "id": 1}
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()
            line = await reader.readline()
            reply_lines.append(line.decode().strip())
            writer.close()
            await writer.wait_closed()

        task = asyncio.create_task(client_exchange())
        async with accept_mcp_connection(mcp_server) as (read_stream, write_stream):
            incoming = await read_stream.receive()
            assert isinstance(incoming, SessionMessage)
            pong = {"jsonrpc": "2.0", "result": {"status": "pong"}, "id": 1}
            await write_stream.send(SessionMessage(JSONRPCMessage.model_validate(pong)))
            await task

        assert json.loads(reply_lines[0])["result"]["status"] == "pong"
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_invalid_json_sent_as_exception(socket_path: Path):
    mcp_server = await bind_mcp_socket(socket_path)
    try:

        async def send_garbage() -> None:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write(b"not valid json\n")
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        task = asyncio.create_task(send_garbage())
        async with accept_mcp_connection(mcp_server) as (read_stream, write_stream):
            received = await read_stream.receive()
            assert isinstance(received, Exception)
            await task
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_blank_lines_are_skipped(socket_path: Path):
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        msg = {"jsonrpc": "2.0", "method": "real", "id": 1}

        async def send_with_blanks() -> None:
            reader, writer = await asyncio.open_unix_connection(str(socket_path))
            writer.write(b"\n\n")
            writer.write((json.dumps(msg) + "\n").encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        task = asyncio.create_task(send_with_blanks())
        async with accept_mcp_connection(mcp_server) as (read_stream, write_stream):
            received = await read_stream.receive()
            assert isinstance(received, SessionMessage)
            data = json.loads(
                received.message.model_dump_json(by_alias=True, exclude_none=True)
            )
            assert data["method"] == "real"
            await task
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()


async def test_sequential_connections(socket_path: Path):
    """The same MCPSocketServer can accept multiple sequential connections."""
    mcp_server = await bind_mcp_socket(socket_path)
    try:
        for i in range(3):
            msg = {"jsonrpc": "2.0", "method": f"call-{i}", "id": i}

            async def connect_and_send(m: dict) -> None:
                reader, writer = await asyncio.open_unix_connection(str(socket_path))
                writer.write((json.dumps(m) + "\n").encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()

            task = asyncio.create_task(connect_and_send(msg))
            async with accept_mcp_connection(mcp_server) as (read_stream, _):
                received = await read_stream.receive()
                assert isinstance(received, SessionMessage)
                data = json.loads(
                    received.message.model_dump_json(by_alias=True, exclude_none=True)
                )
                assert data["method"] == f"call-{i}"
                await task
    finally:
        mcp_server.close()
        await mcp_server.wait_closed()
