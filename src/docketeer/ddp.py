"""Minimal DDP (Distributed Data Protocol) client for Rocket Chat subscriptions."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets import ClientConnection


@dataclass
class DDPClient:
    """Minimal DDP client for real-time subscriptions."""

    url: str
    _ws: ClientConnection | None = field(default=None, repr=False)
    _session: str | None = field(default=None, repr=False)
    _msg_id: int = field(default=0, repr=False)
    _pending: dict[str, asyncio.Future[dict[str, Any]]] = field(
        default_factory=dict, repr=False
    )
    _events: asyncio.Queue[dict[str, Any]] = field(
        default_factory=asyncio.Queue, repr=False
    )
    _receiver_task: asyncio.Task[None] | None = field(default=None, repr=False)

    def _next_id(self) -> str:
        self._msg_id += 1
        return str(self._msg_id)

    async def connect(self) -> None:
        """Connect to DDP server and establish session."""
        self._ws = await websockets.connect(self.url)
        self._receiver_task = asyncio.create_task(self._receiver())

        await self._send({"msg": "connect", "version": "1", "support": ["1"]})

        while self._session is None:
            msg = await self._events.get()
            if msg.get("msg") == "connected":
                self._session = msg.get("session")
            elif msg.get("msg") == "failed":
                raise ConnectionError(f"DDP connection failed: {msg}")

    async def _send(self, data: dict[str, Any]) -> None:
        """Send a message to the server."""
        if self._ws is None:
            raise RuntimeError("Not connected")
        await self._ws.send(json.dumps(data))

    async def _receiver(self) -> None:
        """Background task to receive and dispatch messages."""
        if self._ws is None:
            return

        try:
            async for raw in self._ws:
                msg = json.loads(raw)
                msg_type = msg.get("msg")

                if msg_type == "ping":
                    await self._send({"msg": "pong"})
                elif msg_type == "result":
                    msg_id = msg.get("id")
                    if msg_id in self._pending:
                        self._pending[msg_id].set_result(msg)
                        del self._pending[msg_id]
                else:
                    await self._events.put(msg)
        except websockets.ConnectionClosed:
            await self._events.put({"msg": "disconnected"})

    async def call(self, method: str, params: list[Any]) -> dict[str, Any]:
        """Call a DDP method and wait for result."""
        msg_id = self._next_id()
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_event_loop().create_future()
        )
        self._pending[msg_id] = future

        await self._send(
            {"msg": "method", "method": method, "params": params, "id": msg_id}
        )
        return await future

    async def subscribe(self, name: str, params: list[Any]) -> str:
        """Subscribe to a publication. Returns subscription ID."""
        sub_id = self._next_id()
        await self._send({"msg": "sub", "id": sub_id, "name": name, "params": params})
        return sub_id

    async def unsubscribe(self, sub_id: str) -> None:
        """Unsubscribe from a publication."""
        await self._send({"msg": "unsub", "id": sub_id})

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield subscription events as they arrive."""
        while True:
            msg = await self._events.get()
            if msg.get("msg") == "disconnected":
                break
            yield msg

    async def close(self) -> None:
        """Close the connection."""
        if self._receiver_task:
            self._receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receiver_task
        if self._ws:
            await self._ws.close()
