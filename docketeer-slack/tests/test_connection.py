from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from docketeer.tools import ToolContext, registry
from docketeer_slack import create_client, register_tools
from docketeer_slack.client import SlackClient


def test_create_client():
    assert isinstance(create_client(), SlackClient)


async def test_aenter_calls_authenticate():
    client = SlackClient()
    with patch.object(client, "_authenticate", new_callable=AsyncMock) as auth:
        async with client:
            auth.assert_awaited_once()
            assert client._http is not None


async def test_aexit_cleans_up():
    client = SlackClient()
    client._http = httpx.AsyncClient()
    ws = AsyncMock()
    client._ws = ws
    stack = AsyncExitStack()
    stack.push_async_callback(client._http.aclose)
    client._conn_stack = stack
    await client.__aexit__(None, None, None)
    ws.close.assert_awaited_once()
    assert client._http is None
    assert client._conn_stack is None


async def test_aexit_without_resources():
    client = SlackClient()
    await client.__aexit__(None, None, None)
    assert client._http is None


@respx.mock
async def test_authenticate_sets_identity(slack_client: SlackClient):
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "user_id": "U1", "team_id": "T1", "user": "dobby"},
        )
    )
    await slack_client._authenticate()
    assert slack_client.user_id == "U1"
    assert slack_client.username == "dobby"


@respx.mock
async def test_api_post_retries_on_rate_limit(slack_client: SlackClient):
    route = respx.post("https://slack.com/api/chat.postMessage")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": True}),
    ]
    with patch("docketeer_slack.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
        payload = await slack_client._api_post(
            "chat.postMessage",
            token="xoxb-test",
            json_body={"channel": "C1", "text": "hi"},
        )
    assert payload == {"ok": True}
    sleep.assert_awaited_once()


@respx.mock
async def test_api_post_raises_on_slack_error(slack_client: SlackClient):
    respx.post("https://slack.com/api/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "boom"})
    )
    with pytest.raises(httpx.HTTPError):
        await slack_client._api_post("chat.postMessage", token="xoxb-test")


@respx.mock
async def test_api_get_retries_on_rate_limit(slack_client: SlackClient):
    route = respx.get("https://slack.com/api/conversations.list")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"ok": True, "channels": []}),
    ]
    with patch("docketeer_slack.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
        payload = await slack_client._api_get("conversations.list")
    assert payload == {"ok": True, "channels": []}
    sleep.assert_awaited_once()


@respx.mock
async def test_api_get_raises_on_slack_error(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.list").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "boom"})
    )
    with pytest.raises(httpx.HTTPError):
        await slack_client._api_get("conversations.list")


@respx.mock
async def test_socket_url(slack_client: SlackClient):
    respx.post("https://slack.com/api/apps.connections.open").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "url": "wss://example.test/socket"}
        )
    )
    assert await slack_client._socket_url() == "wss://example.test/socket"


@respx.mock
async def test_socket_url_missing_url(slack_client: SlackClient):
    respx.post("https://slack.com/api/apps.connections.open").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with pytest.raises(ConnectionError):
        await slack_client._socket_url()


async def test_ack_without_socket(slack_client: SlackClient):
    await slack_client._ack("env1")


async def test_ack_with_socket(slack_client: SlackClient):
    slack_client._ws = AsyncMock()
    await slack_client._ack("env1")
    slack_client._ws.send.assert_awaited_once()


async def test_register_tools_file_not_found(tool_context: ToolContext):
    chat = AsyncMock()
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "missing.txt"}, tool_context)
    assert result == "File not found: missing.txt"


async def test_register_tools_directory(tool_context: ToolContext):
    chat = AsyncMock()
    (tool_context.workspace / "dir").mkdir()
    register_tools(chat, tool_context)
    result = await registry.execute("send_file", {"path": "dir"}, tool_context)
    assert result == "Cannot send a directory: dir"
