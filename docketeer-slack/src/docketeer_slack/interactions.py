from __future__ import annotations

from typing import TYPE_CHECKING

from docketeer_slack.parsing import decode_message_id

if TYPE_CHECKING:
    from docketeer_slack.client import SlackClient


async def set_status(_client: SlackClient, status: str, message: str = "") -> None:
    return None


async def send_typing(_client: SlackClient, room_id: str, typing: bool) -> None:
    return None


async def set_thread_status(
    client: SlackClient,
    room_id: str,
    thread_id: str,
    status: str,
) -> None:
    if not thread_id:
        return
    await client._api_post(
        "assistant.threads.setStatus",
        token=client.bot_token,
        data={"channel_id": room_id, "thread_ts": thread_id, "status": status},
    )


async def react(client: SlackClient, message_id: str, emoji: str) -> None:
    channel, ts = decode_message_id(message_id)
    await client._api_post(
        "reactions.add",
        token=client.bot_token,
        data={"channel": channel, "timestamp": ts, "name": emoji.strip(":")},
    )


async def unreact(client: SlackClient, message_id: str, emoji: str) -> None:
    channel, ts = decode_message_id(message_id)
    await client._api_post(
        "reactions.remove",
        token=client.bot_token,
        data={"channel": channel, "timestamp": ts, "name": emoji.strip(":")},
    )


async def fetch_attachment(client: SlackClient, url: str) -> bytes:
    resp = await client._api.get(
        url,
        headers={"Authorization": f"Bearer {client.bot_token}"},
    )
    resp.raise_for_status()
    return resp.content
