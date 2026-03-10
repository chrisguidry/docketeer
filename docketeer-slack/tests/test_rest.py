import json
from pathlib import Path

import httpx
import respx

from docketeer.chat import RoomKind
from docketeer_slack.client import SlackClient


@respx.mock
async def test_send_message(slack_client: SlackClient):
    route = respx.post("https://slack.com/api/chat.postMessage")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))
    await slack_client.send_message("C1", "hello", thread_id="1718123456.123456")
    body = json.loads(route.calls[0].request.content)
    assert body["channel"] == "C1"
    assert body["text"] == "hello"
    assert body["thread_ts"] == "1718123456.123456"


@respx.mock
async def test_send_message_with_attachments(slack_client: SlackClient):
    route = respx.post("https://slack.com/api/chat.postMessage")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))
    await slack_client.send_message("C1", "hello", attachments=[{"color": "green"}])
    body = json.loads(route.calls[0].request.content)
    assert body["attachments"] == [{"color": "green"}]


@respx.mock
async def test_react(slack_client: SlackClient):
    route = respx.post("https://slack.com/api/reactions.add")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))
    await slack_client.react("C1:1718123456.123456", ":brain:")
    body = route.calls[0].request.content.decode()
    assert "channel=C1" in body
    assert "timestamp=1718123456.123456" in body
    assert "name=brain" in body


@respx.mock
async def test_unreact(slack_client: SlackClient):
    route = respx.post("https://slack.com/api/reactions.remove")
    route.mock(return_value=httpx.Response(200, json={"ok": True}))
    await slack_client.unreact("C1:1718123456.123456", ":brain:")
    body = route.calls[0].request.content.decode()
    assert "channel=C1" in body
    assert "timestamp=1718123456.123456" in body
    assert "name=brain" in body


@respx.mock
async def test_list_rooms(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.list").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [
                    {"id": "D1", "is_im": True},
                    {"id": "G1", "is_mpim": True},
                    {"id": "C1", "name": "general"},
                    {"id": "P1", "name": "secret", "is_private": True},
                ],
                "response_metadata": {"next_cursor": ""},
            },
        )
    )
    rooms = await slack_client.list_rooms()
    by_id = {r.room_id: r for r in rooms}
    assert by_id["D1"].kind is RoomKind.direct
    assert by_id["G1"].kind is RoomKind.group
    assert by_id["C1"].kind is RoomKind.public
    assert by_id["P1"].kind is RoomKind.private


@respx.mock
async def test_fetch_messages(slack_client: SlackClient):
    respx.get("https://slack.com/api/conversations.history").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {
                        "ts": "1718123457.000002",
                        "user": "U2",
                        "text": "second",
                    },
                    {
                        "ts": "1718123456.000001",
                        "user": "U1",
                        "text": "first",
                        "thread_ts": "1718123000.000001",
                    },
                ],
            },
        )
    )
    messages = await slack_client.fetch_messages("C1")
    assert len(messages) == 2
    assert messages[0].message_id == "C1:1718123456.000001"
    assert messages[0].thread_id == "1718123000.000001"
    assert messages[0].text == "first"
    assert messages[1].message_id == "C1:1718123457.000002"


@respx.mock
async def test_fetch_attachment(slack_client: SlackClient):
    respx.get("https://files.slack.test/a.png").mock(
        return_value=httpx.Response(200, content=b"img")
    )
    data = await slack_client.fetch_attachment("https://files.slack.test/a.png")
    assert data == b"img"


@respx.mock
async def test_upload_file(slack_client: SlackClient, tmp_path: Path):
    target = tmp_path / "note.txt"
    target.write_text("hello")

    get_url = respx.post("https://slack.com/api/files.getUploadURLExternal")
    get_url.mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "upload_url": "https://uploads.slack.test/abc",
                "file_id": "F1",
            },
        )
    )
    respx.post("https://uploads.slack.test/abc").mock(return_value=httpx.Response(200))
    complete = respx.post("https://slack.com/api/files.completeUploadExternal")
    complete.mock(return_value=httpx.Response(200, json={"ok": True}))

    await slack_client.upload_file("C1", str(target), message="here", thread_id="1718")

    get_url_body = get_url.calls[0].request.content.decode()
    assert "filename=note.txt" in get_url_body
    complete_body = complete.calls[0].request.content.decode()
    assert "channel_id=C1" in complete_body
    assert "initial_comment=here" in complete_body
    assert "thread_ts=1718" in complete_body
    assert "F1" in complete_body


@respx.mock
async def test_upload_file_without_optional_fields(
    slack_client: SlackClient, tmp_path: Path
):
    target = tmp_path / "note.txt"
    target.write_text("hello")

    respx.post("https://slack.com/api/files.getUploadURLExternal").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "upload_url": "https://uploads.slack.test/def",
                "file_id": "F2",
            },
        )
    )
    respx.post("https://uploads.slack.test/def").mock(return_value=httpx.Response(200))
    complete = respx.post("https://slack.com/api/files.completeUploadExternal")
    complete.mock(return_value=httpx.Response(200, json={"ok": True}))

    await slack_client.upload_file("C1", str(target))
    complete_body = complete.calls[0].request.content.decode()
    assert "initial_comment" not in complete_body
    assert "thread_ts" not in complete_body
