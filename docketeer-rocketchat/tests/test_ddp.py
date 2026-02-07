"""Tests for the DDP (Distributed Data Protocol) client."""

import asyncio
import json
from typing import Any

import pytest
import websockets
from websockets import ServerConnection

from docketeer_rocketchat.ddp import DDPClient


@pytest.fixture()
async def ddp_server():
    """Fixture providing a configurable fake DDP server.

    Returns a factory(handler) -> (server, url). Servers cleaned up after test.
    """
    servers: list[Any] = []
    clients: list[DDPClient] = []

    async def factory(handler: Any) -> tuple[DDPClient, str]:
        server = await websockets.serve(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        servers.append(server)
        url = f"ws://127.0.0.1:{port}"
        client = DDPClient(url=url)
        clients.append(client)
        return client, url

    yield factory

    for c in clients:
        await c.close()
    for s in servers:
        s.close()
        await s.wait_closed()


async def _ok_handler(ws: ServerConnection) -> None:
    """Standard handler: connect → connected, method → result, sub → ready."""
    try:
        async for raw in ws:
            msg = json.loads(raw)
            match msg.get("msg"):
                case "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "sess-1"}))
                case "method":
                    await ws.send(
                        json.dumps(
                            {"msg": "result", "id": msg["id"], "result": {"ok": True}}
                        )
                    )
                case "sub":
                    await ws.send(json.dumps({"msg": "ready", "subs": [msg["id"]]}))
    except websockets.ConnectionClosed:
        pass


async def test_connect_success(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    await client.connect()
    assert client._session == "sess-1"


async def test_connect_failed(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                if json.loads(raw).get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "failed", "version": "1"}))
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    with pytest.raises(ConnectionError, match="DDP connection failed"):
        await client.connect()


async def test_send_not_connected():
    client = DDPClient(url="ws://localhost:1")
    with pytest.raises(RuntimeError, match="Not connected"):
        await client._send({"msg": "test"})


async def test_receiver_ping_pong(ddp_server: Any):
    pong_seen = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    await ws.send(json.dumps({"msg": "ping"}))
                elif msg.get("msg") == "pong":
                    pong_seen.set()
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()
    await asyncio.wait_for(pong_seen.wait(), timeout=2)


async def test_receiver_result_dispatch(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    await client.connect()
    result = await client.call("test.method", [])
    assert result["result"]["ok"] is True


async def test_receiver_events(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    await ws.send(json.dumps({"msg": "changed", "id": "1"}))
                    return  # server handler exits → connection closes
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()

    events = []
    async for event in client.events():
        events.append(event)
    assert len(events) == 1
    assert events[0]["msg"] == "changed"


async def test_receiver_connection_closed(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                if json.loads(raw).get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    return  # server handler exits → connection closes
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()

    events = []
    async for event in client.events():
        events.append(event)
    assert events == []


async def test_call(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    await client.connect()
    result = await client.call("rpc", ["arg1"])
    assert "result" in result


async def test_subscribe(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    await client.connect()
    sub_id = await client.subscribe("coll", ["param"])
    assert sub_id is not None


async def test_unsubscribe(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    await client.connect()
    sub_id = await client.subscribe("coll", [])
    await client.unsubscribe(sub_id)


async def test_events_iterator(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    for i in range(3):
                        await ws.send(json.dumps({"msg": "changed", "id": str(i)}))
                    return  # server handler exits → connection closes
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()

    events = []
    async for event in client.events():
        events.append(event)
    assert len(events) == 3


async def test_close(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    await client.connect()
    await client.close()
    assert client._receiver_task is not None
    assert client._receiver_task.cancelled() or client._receiver_task.done()


async def test_close_no_task_or_ws():
    client = DDPClient(url="ws://localhost:1")
    await client.close()


async def test_receiver_no_ws():
    client = DDPClient(url="ws://localhost:1")
    assert client._ws is None
    await client._receiver()


async def test_receiver_connection_closed_exception(ddp_server: Any):
    """Exercise the except ConnectionClosed branch by aborting the connection."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    # Force-close the underlying transport to cause ConnectionClosed
                    ws.transport.abort()
                    return
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()
    # Wait for the receiver to process the connection abort
    events = []
    async for event in client.events():
        events.append(event)
    assert events == []


async def test_connect_ignores_unrelated_messages(ddp_server: Any):
    """Connect loop iterates past messages that aren't 'connected' or 'failed'."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    # Send a message that the receiver queues (not ping/result),
                    # so connect()'s while loop sees it and loops again.
                    await ws.send(json.dumps({"msg": "added", "collection": "x"}))
                    await ws.send(json.dumps({"msg": "connected", "session": "s2"}))
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()
    assert client._session == "s2"


async def test_receiver_drops_unknown_result_id(ddp_server: Any):
    """A 'result' message with an unknown ID is silently dropped."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    # Send a result with an ID nobody is waiting for
                    await ws.send(
                        json.dumps({"msg": "result", "id": "unknown-id", "result": {}})
                    )
                    # Then send a normal event so we can verify the receiver continued
                    await ws.send(json.dumps({"msg": "changed", "id": "ev1"}))
                    return
        except websockets.ConnectionClosed:
            pass

    client, _ = await ddp_server(handler)
    await client.connect()

    events = []
    async for event in client.events():
        events.append(event)
    assert any(e.get("id") == "ev1" for e in events)
