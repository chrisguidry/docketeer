import httpx
import respx

from docketeer.chat import RoomInfo, RoomKind
from docketeer_slack.client import SlackClient


async def test_room_slug_from_cache(slack_client: SlackClient):
    slack_client._rooms["C1"] = RoomInfo(room_id="C1", kind=RoomKind.public, members=[], name="general")
    assert await slack_client.room_slug("C1") == "general"


async def test_room_slug_fallback(slack_client: SlackClient):
    assert await slack_client.room_slug("C1") == "C1"


async def test_room_context_from_cache_dm(slack_client: SlackClient):
    slack_client._rooms["D1"] = RoomInfo(room_id="D1", kind=RoomKind.direct, members=[])
    assert await slack_client.room_context("D1", "alice") == "Room: DM with @alice"


async def test_room_context_from_cache_channel(slack_client: SlackClient):
    slack_client._rooms["C1"] = RoomInfo(room_id="C1", kind=RoomKind.public, members=[], name="general")
    assert await slack_client.room_context("C1", "alice") == "Room: #general (public)"


@respx.mock
async def test_room_context_fetches_info(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.info").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "channel": {
                    "id": "C1",
                    "name": "general",
                    "topic": {"value": "Topical"},
                    "purpose": {"value": "Purposeful"},
                },
            },
        )
    )
    ctx = await slack_client.room_context("C1", "alice")
    assert "#general" in ctx
    assert "Topical" in ctx
    assert "Purposeful" in ctx


@respx.mock
async def test_room_context_fetch_failure(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.info").mock(return_value=httpx.Response(500))
    assert await slack_client.room_context("C1", "alice") == ""


@respx.mock
async def test_fetch_message_found(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.replies").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "messages": [{"ts": "1718", "text": "hello"}]},
        )
    )
    message = await slack_client.fetch_message("C1:1718")
    assert message == {"ts": "1718", "text": "hello"}


@respx.mock
async def test_fetch_message_not_found(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.replies").mock(
        return_value=httpx.Response(200, json={"ok": True, "messages": []})
    )
    assert await slack_client.fetch_message("C1:1718") is None


@respx.mock
async def test_fetch_message_nonmatching_message(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.replies").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "messages": [{"ts": "other", "text": "hello"}]},
        )
    )
    assert await slack_client.fetch_message("C1:1718") is None


async def test_send_typing_noop(slack_client: SlackClient):
    assert await slack_client.send_typing("C1", True) is None


async def test_set_status_noop(slack_client: SlackClient):
    assert await slack_client.set_status("online") is None
