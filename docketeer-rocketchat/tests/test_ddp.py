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

    Returns a factory(handler) -> (client, url). Servers cleaned up after test.
    """
    servers: list[Any] = []

    async def factory(handler: Any) -> tuple[DDPClient, str]:
        server = await websockets.serve(handler, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        servers.append(server)
        url = f"ws://127.0.0.1:{port}"
        client = DDPClient(url=url)
        return client, url

    yield factory

    for s in servers:
        s.close()
        await s.wait_closed()


async def _ok_handler(ws: ServerConnection) -> None:
    """Standard handler: connect → connected, method → result, sub → ready."""
    try:
        async for raw in ws:  # pragma: no branch
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
    except websockets.ConnectionClosed:  # pragma: no cover
        pass


async def test_connect_success(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    async with client:
        assert client._session == "sess-1"


async def test_connect_failed(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                if json.loads(raw).get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "failed", "version": "1"}))
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    with pytest.raises(ConnectionError, match="DDP connection failed"):
        async with client:
            pass  # pragma: no cover - never reached, raises on __aenter__


async def test_send_not_connected():
    client = DDPClient(url="ws://localhost:1")
    with pytest.raises(RuntimeError, match="Not connected"):
        await client._send({"msg": "test"})


async def test_receiver_ping_pong(ddp_server: Any):
    pong_seen = asyncio.Event()

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    await ws.send(json.dumps({"msg": "ping"}))
                elif msg.get("msg") == "pong":  # pragma: no branch
                    pong_seen.set()
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        await asyncio.wait_for(pong_seen.wait(), timeout=2)


async def test_receiver_result_dispatch(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    async with client:
        result = await client.call("test.method", [])
        assert result["result"]["ok"] is True


async def test_receiver_events(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    await ws.send(json.dumps({"msg": "changed", "id": "1"}))
                    return  # server handler exits → connection closes
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        events = []
        async for event in client.events():
            events.append(event)
        assert len(events) == 1
        assert events[0]["msg"] == "changed"


async def test_receiver_connection_closed(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                if json.loads(raw).get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    return  # server handler exits → connection closes
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        events = []
        async for event in client.events():  # pragma: no branch - never iterates
            events.append(event)  # pragma: no cover - no events
        assert events == []


async def test_call(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    async with client:
        result = await client.call("rpc", ["arg1"])
        assert "result" in result


async def test_subscribe(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    async with client:
        sub_id = await client.subscribe("coll", ["param"])
        assert sub_id is not None


async def test_unsubscribe(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    async with client:
        sub_id = await client.subscribe("coll", [])
        await client.unsubscribe(sub_id)


async def test_events_iterator(ddp_server: Any):
    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    for i in range(3):
                        await ws.send(json.dumps({"msg": "changed", "id": str(i)}))
                    return  # server handler exits → connection closes
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        events = []
        async for event in client.events():
            events.append(event)
        assert len(events) == 3


async def test_aexit_cleans_up(ddp_server: Any):
    client, _ = await ddp_server(_ok_handler)
    async with client:
        pass
    assert client._receiver_task is not None
    assert client._receiver_task.cancelled() or client._receiver_task.done()


async def test_aexit_without_aenter():
    client = DDPClient(url="ws://localhost:1")
    await client.__aexit__(None, None, None)


async def test_receiver_no_ws():
    client = DDPClient(url="ws://localhost:1")
    assert client._ws is None
    await client._receiver()


async def test_receiver_connection_closed_exception(ddp_server: Any):
    """Exercise the except ConnectionClosed branch by aborting the connection."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    # Force-close the underlying transport to cause ConnectionClosed
                    ws.transport.abort()
                    return
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        # Wait for the receiver to process the connection abort
        events = []
        async for event in client.events():  # pragma: no branch - never iterates
            events.append(event)  # pragma: no cover - no events
        assert events == []


async def test_receiver_logs_ready(ddp_server: Any):
    """A 'ready' message is logged and not queued as an event."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    await ws.send(json.dumps({"msg": "ready", "subs": ["sub-1"]}))
                    await ws.send(json.dumps({"msg": "changed", "id": "ev1"}))
                    return
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        events = []
        async for event in client.events():
            events.append(event)
        # ready should not appear as an event; changed should
        assert all(e.get("msg") != "ready" for e in events)
        assert any(e.get("id") == "ev1" for e in events)


async def test_receiver_logs_nosub(ddp_server: Any):
    """A 'nosub' message is logged and not queued as an event."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    await ws.send(
                        json.dumps({"msg": "nosub", "id": "bad-sub", "error": "nope"})
                    )
                    await ws.send(json.dumps({"msg": "changed", "id": "ev1"}))
                    return
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        events = []
        async for event in client.events():
            events.append(event)
        assert all(e.get("msg") != "nosub" for e in events)
        assert any(e.get("id") == "ev1" for e in events)


async def test_connect_ignores_unrelated_messages(ddp_server: Any):
    """Connect loop iterates past messages that aren't 'connected' or 'failed'."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    # Send a message that the receiver queues (not ping/result),
                    # so connect()'s while loop sees it and loops again.
                    await ws.send(json.dumps({"msg": "added", "collection": "x"}))
                    await ws.send(json.dumps({"msg": "connected", "session": "s2"}))
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        assert client._session == "s2"


async def test_receiver_drops_unknown_result_id(ddp_server: Any):
    """A 'result' message with an unknown ID is silently dropped."""

    async def handler(ws: ServerConnection) -> None:
        try:
            async for raw in ws:  # pragma: no branch
                msg = json.loads(raw)
                if msg.get("msg") == "connect":  # pragma: no branch
                    await ws.send(json.dumps({"msg": "connected", "session": "s1"}))
                    # Send a result with an ID nobody is waiting for
                    await ws.send(
                        json.dumps({"msg": "result", "id": "unknown-id", "result": {}})
                    )
                    # Then send a normal event so we can verify the receiver continued
                    await ws.send(json.dumps({"msg": "changed", "id": "ev1"}))
                    return
        except websockets.ConnectionClosed:  # pragma: no cover
            pass

    client, _ = await ddp_server(handler)
    async with client:
        events = []
        async for event in client.events():
            events.append(event)
        assert any(e.get("id") == "ev1" for e in events)
