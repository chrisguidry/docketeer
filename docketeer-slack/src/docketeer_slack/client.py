"""Slack client combining Socket Mode with async Web API calls."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import websockets
from websockets import ClientConnection

from docketeer import environment
from docketeer.chat import (
    ChatClient,
    IncomingMessage,
    OnHistoryCallback,
    RoomInfo,
    RoomKind,
    RoomMessage,
)
from docketeer_slack.parsing import (
    conversation_kind,
    decode_message_id,
    encode_message_id,
    parse_attachments,
    parse_slack_ts,
    should_ignore_message,
)

log = logging.getLogger(__name__)

API_BASE = "https://slack.com/api"


@dataclass
class SlackReplyStream:
    channel_id: str
    stream_ts: str
    thread_id: str
    user_id: str = ""


class SlackClient(ChatClient):
    """Socket Mode + Web API Slack client."""

    def __init__(self) -> None:
        self.bot_token = environment.get_str("SLACK_BOT_TOKEN")
        self.app_token = environment.get_str("SLACK_APP_TOKEN")
        self.username = environment.get_str("SLACK_BOT_NAME", "slackbot")
        self._allowlist = {
            c.strip()
            for c in environment.get_str("SLACK_CHANNELS", "").split(",")
            if c.strip()
        }
        self._http: httpx.AsyncClient | None = None
        self._conn_stack: AsyncExitStack | None = None
        self._ws: ClientConnection | None = None
        self._user_id: str | None = None
        self._team_id: str | None = None
        self._rooms: dict[str, RoomInfo] = {}
        self._high_water: datetime | None = None

    @property
    def user_id(self) -> str:
        return self._user_id or ""

    async def __aenter__(self) -> SlackClient:
        self._conn_stack = AsyncExitStack()
        self._http = httpx.AsyncClient(timeout=30)
        self._conn_stack.push_async_callback(self._http.aclose)
        await self._authenticate()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._conn_stack:
            await self._conn_stack.aclose()
            self._conn_stack = None
        self._http = None

    @property
    def _api(self) -> httpx.AsyncClient:
        assert self._http is not None, "Not connected"
        return self._http

    async def _authenticate(self) -> None:
        auth = await self._api_post("auth.test", token=self.bot_token)
        self._user_id = auth.get("user_id", "")
        self._team_id = auth.get("team_id", "")
        self.username = auth.get("user", self.username)

    async def _api_post(
        self,
        method: str,
        *,
        token: str,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        while True:
            resp = await self._api.post(
                f"{API_BASE}/{method}",
                headers=headers,
                json=json_body,
                data=data,
            )
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(retry)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("ok", False):
                raise httpx.HTTPError(f"Slack API error on {method}: {payload}")
            return payload

    async def _api_get(
        self,
        method: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.bot_token}"}
        while True:
            resp = await self._api.get(
                f"{API_BASE}/{method}", headers=headers, params=params
            )
            if resp.status_code == 429:
                retry = int(resp.headers.get("Retry-After", "1"))
                await asyncio.sleep(retry)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("ok", False):
                raise httpx.HTTPError(f"Slack API error on {method}: {payload}")
            return payload

    async def _socket_url(self) -> str:
        payload = await self._api_post("apps.connections.open", token=self.app_token)
        url = payload.get("url", "")
        if not url:
            raise ConnectionError("Slack apps.connections.open did not return a url")
        return url

    async def _open_socket(self) -> None:
        url = await self._socket_url()
        self._ws = await websockets.connect(url, open_timeout=30)

    async def _ack(self, envelope_id: str) -> None:
        if self._ws is None:
            return
        await self._ws.send(json.dumps({"envelope_id": envelope_id}))

    async def incoming_messages(
        self,
        on_history: OnHistoryCallback | None = None,
    ) -> AsyncGenerator[IncomingMessage, None]:
        seen: set[str] = set()
        backoff = 1

        while True:
            await self._open_socket()
            await self._prime_history(on_history, since=self._high_water)
            try:
                assert self._ws is not None
                async for raw in self._ws:
                    event = json.loads(raw)
                    envelope_id = event.get("envelope_id", "")
                    if envelope_id:
                        await self._ack(envelope_id)
                    msg = await self._parse_socket_event(event)
                    if not msg:
                        continue
                    if msg.message_id in seen:
                        continue
                    seen.add(msg.message_id)
                    if msg.timestamp and (
                        self._high_water is None or msg.timestamp > self._high_water
                    ):
                        self._high_water = msg.timestamp
                    yield msg
                log.warning("Slack socket closed, reconnecting")
            except websockets.ConnectionClosed:
                log.warning("Slack socket disconnected, reconnecting")
            finally:
                if self._ws:
                    await self._ws.close()
                    self._ws = None

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _parse_socket_event(
        self, envelope: dict[str, Any]
    ) -> IncomingMessage | None:
        payload = envelope.get("payload", {})
        event = payload.get("event", {})
        event_type = event.get("type")

        if event_type == "app_mention":
            return self._incoming_from_message(event, kind=RoomKind.public)

        if event_type != "message":
            return None

        channel_type = event.get("channel_type", "")
        kind = {
            "im": RoomKind.direct,
            "mpim": RoomKind.group,
            "channel": RoomKind.public,
            "group": RoomKind.private,
        }.get(channel_type, RoomKind.direct)

        if kind in {
            RoomKind.public,
            RoomKind.private,
        } and not self._should_handle_channel_message(event):
            return None

        return self._incoming_from_message(event, kind=kind)

    def _should_handle_channel_message(self, event: dict[str, Any]) -> bool:
        channel = event.get("channel", "")
        return channel in self._allowlist or (
            bool(self._user_id) and f"<@{self._user_id}>" in event.get("text", "")
        )

    def _incoming_from_message(
        self,
        event: dict[str, Any],
        *,
        kind: RoomKind,
    ) -> IncomingMessage | None:
        if should_ignore_message(event, bot_user_id=self.user_id):
            return None

        channel = event.get("channel", "")
        ts = event.get("ts", "")
        if not channel or not ts:
            return None

        text = event.get("text", "")
        attachments = parse_attachments(event.get("files"))
        if not text and not attachments:
            return None

        user_id = event.get("user", "")
        message_id = encode_message_id(channel, ts)
        return IncomingMessage(
            message_id=message_id,
            user_id=user_id,
            username=user_id or "unknown",
            display_name=user_id or "unknown",
            text=text,
            room_id=channel,
            kind=kind,
            timestamp=parse_slack_ts(ts),
            attachments=attachments,
            thread_id=event.get("thread_ts", "")
            if event.get("thread_ts") != ts
            else "",
            is_own=user_id == self.user_id,
        )

    async def send_message(
        self,
        room_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
        *,
        thread_id: str = "",
    ) -> None:
        body: dict[str, Any] = {"channel": room_id, "text": text}
        if attachments:
            body["attachments"] = attachments
        if thread_id:
            body["thread_ts"] = thread_id
        await self._api_post("chat.postMessage", token=self.bot_token, json_body=body)

    async def upload_file(
        self, room_id: str, file_path: str, message: str = "", *, thread_id: str = ""
    ) -> None:
        path = Path(file_path)
        upload = await self._api_post(
            "files.getUploadURLExternal",
            token=self.bot_token,
            data={"filename": path.name, "length": path.stat().st_size},
        )
        upload_url = upload["upload_url"]
        file_id = upload["file_id"]
        resp = await self._api.post(upload_url, content=path.read_bytes())
        resp.raise_for_status()

        data: dict[str, Any] = {
            "files": json.dumps([{"id": file_id, "title": path.name}]),
            "channel_id": room_id,
        }
        if message:
            data["initial_comment"] = message
        if thread_id:
            data["thread_ts"] = thread_id
        await self._api_post(
            "files.completeUploadExternal", token=self.bot_token, data=data
        )

    async def fetch_attachment(self, url: str) -> bytes:
        resp = await self._api.get(
            url,
            headers={"Authorization": f"Bearer {self.bot_token}"},
        )
        resp.raise_for_status()
        return resp.content

    async def fetch_message(self, message_id: str) -> dict[str, Any] | None:
        channel, ts = decode_message_id(message_id)
        thread = await self._api_get(
            "conversations.replies", params={"channel": channel, "ts": ts}
        )
        for message in thread.get("messages", []):
            if message.get("ts") == ts:
                return message
        return None

    async def fetch_messages(
        self,
        room_id: str,
        *,
        before: datetime | None = None,
        after: datetime | None = None,
        count: int = 50,
    ) -> list[RoomMessage]:
        params: dict[str, Any] = {"channel": room_id, "limit": count}
        if before:
            params["latest"] = before.timestamp()
        if after:
            params["oldest"] = after.timestamp()
        result = await self._api_get("conversations.history", params=params)
        raw_messages = list(reversed(result.get("messages", [])))

        messages: list[RoomMessage] = []
        for message in raw_messages:
            if should_ignore_message(message, bot_user_id=self.user_id):
                continue
            ts = message.get("ts", "")
            dt = parse_slack_ts(ts)
            if not dt:
                continue
            user_id = message.get("user", "")
            messages.append(
                RoomMessage(
                    message_id=encode_message_id(room_id, ts),
                    timestamp=dt,
                    username=user_id or "unknown",
                    display_name=user_id or "unknown",
                    text=message.get("text", ""),
                    attachments=parse_attachments(message.get("files")),
                    thread_id=message.get("thread_ts", "")
                    if message.get("thread_ts") != ts
                    else "",
                )
            )
        return messages

    async def list_rooms(self) -> list[RoomInfo]:
        rooms: list[RoomInfo] = []
        cursor = ""
        while True:
            params: dict[str, Any] = {
                "exclude_archived": True,
                "limit": 1000,
                "types": "public_channel,private_channel,im,mpim",
            }
            if cursor:
                params["cursor"] = cursor
            result = await self._api_get("conversations.list", params=params)
            for convo in result.get("channels", []):
                kind = conversation_kind(convo)
                room = RoomInfo(
                    room_id=convo.get("id", ""),
                    kind=kind,
                    members=[],
                    name=convo.get("name", ""),
                )
                rooms.append(room)
                self._rooms[room.room_id] = room
            cursor = result.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return rooms

    async def set_status(self, status: str, message: str = "") -> None:
        return None

    async def send_typing(self, room_id: str, typing: bool) -> None:
        return None

    async def reply_thread_id(self, msg: IncomingMessage) -> str:
        return msg.thread_id or decode_message_id(msg.message_id)[1]

    async def set_thread_status(
        self,
        room_id: str,
        thread_id: str,
        status: str,
    ) -> None:
        if not thread_id:
            return
        await self._api_post(
            "assistant.threads.setStatus",
            token=self.bot_token,
            data={
                "channel_id": room_id,
                "thread_ts": thread_id,
                "status": status,
            },
        )

    async def start_reply_stream(
        self,
        msg: IncomingMessage,
        thread_id: str,
        text: str,
    ) -> SlackReplyStream | None:
        if not thread_id or not text:
            return None
        data: dict[str, Any] = {
            "channel": msg.room_id,
            "thread_ts": thread_id,
            "markdown_text": text,
        }
        if self._team_id:
            data["recipient_team_id"] = self._team_id
        if msg.kind is RoomKind.direct and msg.user_id:
            data["recipient_user_id"] = msg.user_id
        payload = await self._api_post(
            "chat.startStream",
            token=self.bot_token,
            data=data,
        )
        stream_ts = payload.get("ts", "")
        if not stream_ts:
            raise httpx.HTTPError("Slack chat.startStream did not return ts")
        return SlackReplyStream(
            channel_id=msg.room_id,
            stream_ts=stream_ts,
            thread_id=thread_id,
            user_id=msg.user_id if msg.kind is RoomKind.direct else "",
        )

    async def append_reply_stream(self, stream: Any, text: str) -> None:
        if not isinstance(stream, SlackReplyStream) or not text:
            return
        await self._api_post(
            "chat.appendStream",
            token=self.bot_token,
            data={
                "channel": stream.channel_id,
                "ts": stream.stream_ts,
                "markdown_text": text,
            },
        )

    async def stop_reply_stream(self, stream: Any) -> None:
        if not isinstance(stream, SlackReplyStream):
            return
        data: dict[str, Any] = {
            "channel": stream.channel_id,
            "ts": stream.stream_ts,
        }
        if self._team_id:
            data["recipient_team_id"] = self._team_id
        if stream.user_id:
            data["recipient_user_id"] = stream.user_id
        await self._api_post(
            "chat.stopStream",
            token=self.bot_token,
            data=data,
        )

    async def react(self, message_id: str, emoji: str) -> None:
        channel, ts = decode_message_id(message_id)
        await self._api_post(
            "reactions.add",
            token=self.bot_token,
            data={"channel": channel, "timestamp": ts, "name": emoji.strip(":")},
        )

    async def unreact(self, message_id: str, emoji: str) -> None:
        channel, ts = decode_message_id(message_id)
        await self._api_post(
            "reactions.remove",
            token=self.bot_token,
            data={"channel": channel, "timestamp": ts, "name": emoji.strip(":")},
        )

    async def room_slug(self, room_id: str) -> str:
        room = self._rooms.get(room_id)
        return room.name if room and room.name else room_id

    async def room_context(self, room_id: str, username: str) -> str:
        room = self._rooms.get(room_id)
        if not room:
            try:
                result = await self._api_get(
                    "conversations.info", params={"channel": room_id}
                )
                convo = result.get("channel", {})
                room = RoomInfo(
                    room_id=room_id,
                    kind=conversation_kind(convo),
                    members=[],
                    name=convo.get("name", ""),
                )
                self._rooms[room_id] = room
                topic = convo.get("topic", {}).get("value", "")
                purpose = convo.get("purpose", {}).get("value", "")
            except httpx.HTTPError:
                return ""
        else:
            topic = purpose = ""

        if room.kind is RoomKind.direct:
            return f"Room: DM with @{username}"

        label = room.name or room_id
        visibility = "private" if room.kind is RoomKind.private else "public"
        parts = [f"Room: #{label} ({visibility})"]
        if topic:
            parts.append(f"Topic: {topic}")
        if purpose:
            parts.append(f"Purpose: {purpose}")
        return "\n".join(parts)

    async def _prime_history(
        self,
        on_history: OnHistoryCallback | None,
        since: datetime | None = None,
    ) -> None:
        if not on_history:
            return
        try:
            rooms = await self.list_rooms()
        except httpx.HTTPError:
            log.warning("Failed to list Slack rooms for history", exc_info=True)
            return
        dm_rooms = [r for r in rooms if r.kind.is_dm]
        for room in dm_rooms:
            try:
                messages = await self.fetch_messages(room.room_id, after=since)
            except httpx.HTTPError:
                log.warning(
                    "Failed to fetch history for %s", room.room_id, exc_info=True
                )
                continue
            if not messages:
                continue
            await on_history(room, messages)
            for msg in messages:
                if self._high_water is None or msg.timestamp > self._high_water:
                    self._high_water = msg.timestamp
