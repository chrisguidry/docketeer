"""Tests for connect, close, subscribe, and user_id."""

from unittest.mock import AsyncMock, patch

import httpx
import respx

from docketeer.chat import RocketChatClient


async def test_close():
    client = RocketChatClient()
    client._http = httpx.AsyncClient()
    client._ddp = AsyncMock()
    await client.close()
    client._ddp.close.assert_called_once()


async def test_close_no_connections():
    client = RocketChatClient()
    await client.close()


def test_user_id_property():
    client = RocketChatClient()
    assert client.user_id == ""
    client._user_id = "uid123"
    assert client.user_id == "uid123"


@respx.mock
async def test_connect():
    client = RocketChatClient()

    with patch("docketeer.chat.DDPClient") as mock_ddp_cls:
        ddp = AsyncMock()
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

        await client.connect()

    assert client._user_id == "uid_bot"
    assert client._ddp is ddp
    ddp.connect.assert_called_once()
    ddp.call.assert_called_once()
    await client.close()


async def test_subscribe_to_my_messages():
    client = RocketChatClient()
    client._user_id = "uid_bot"
    ddp = AsyncMock()
    client._ddp = ddp
    await client.subscribe_to_my_messages()
    ddp.subscribe.assert_called_once()


async def test_subscribe_to_my_messages_no_ddp():
    client = RocketChatClient()
    client._ddp = None
    await client.subscribe_to_my_messages()


async def test_subscribe_to_my_messages_no_user_id():
    client = RocketChatClient()
    client._ddp = AsyncMock()
    client._user_id = None
    await client.subscribe_to_my_messages()
    client._ddp.subscribe.assert_not_called()
