"""Tests for connect, close, subscribe, and user_id."""

from unittest.mock import AsyncMock, patch

import httpx
import respx

from docketeer_rocketchat.client import RocketChatClient


async def test_aexit_cleans_up():
    client = RocketChatClient()
    client._http = httpx.AsyncClient()
    ddp = AsyncMock()
    ddp.__aexit__ = AsyncMock(return_value=None)
    client._ddp = ddp
    # Simulate having a conn_stack that owns the resources
    from contextlib import AsyncExitStack

    stack = AsyncExitStack()
    stack.push_async_callback(ddp.__aexit__, None, None, None)
    stack.push_async_callback(client._http.aclose)
    client._conn_stack = stack
    await client.__aexit__(None, None, None)
    assert client._ddp is None
    assert client._http is None
    assert client._conn_stack is None


async def test_aexit_without_aenter():
    client = RocketChatClient()
    await client.__aexit__(None, None, None)
    assert client._ddp is None
    assert client._http is None


def test_user_id_property():
    client = RocketChatClient()
    assert client.user_id == ""
    client._user_id = "uid123"
    assert client.user_id == "uid123"


@respx.mock
async def test_aenter_authenticates():
    client = RocketChatClient()

    with patch("docketeer_rocketchat.client.DDPClient") as mock_ddp_cls:
        ddp = AsyncMock()
        ddp.__aenter__ = AsyncMock(return_value=ddp)
        ddp.__aexit__ = AsyncMock(return_value=None)
        mock_ddp_cls.return_value = ddp

        respx.post("http://localhost:3000/api/v1/login").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"authToken": "tok123", "userId": "uid_bot"}},
            )
        )
        respx.get("http://localhost:3000/api/v1/me").mock(
            return_value=httpx.Response(
                200,
                json={"username": "bot", "name": "Bot"},
            )
        )

        async with client:
            assert client._user_id == "uid_bot"
            assert client._ddp is ddp
            ddp.__aenter__.assert_called_once()
            ddp.call.assert_called_once()


async def test_subscribe_to_messages():
    client = RocketChatClient()
    client._user_id = "uid_bot"
    ddp = AsyncMock()
    client._ddp = ddp
    await client._subscribe_to_messages()
    ddp.subscribe.assert_called_once()


async def test_subscribe_to_messages_no_ddp():
    client = RocketChatClient()
    client._ddp = None
    await client._subscribe_to_messages()


async def test_subscribe_to_messages_no_user_id():
    client = RocketChatClient()
    client._ddp = AsyncMock()
    client._user_id = None
    await client._subscribe_to_messages()
    client._ddp.subscribe.assert_not_called()
