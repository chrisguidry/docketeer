# docketeer-rocketchat

Rocket Chat backend. Implements the `docketeer.chat` entry point so the agent
can send and receive messages through a Rocket.Chat server.

## Structure

- **`client.py`** — the `RocketChatClient`. Implements the `ChatClient` ABC.
  Manages connection lifecycle, message dispatch, room operations, and file
  uploads.
- **`ddp.py`** — low-level DDP (Distributed Data Protocol) client over
  websockets. Handles the Meteor-style realtime subscription protocol that
  Rocket.Chat uses.
- **`parsing.py`** — message parsing. Translates Rocket.Chat's message
  format into Docketeer's `IncomingMessage` and `RoomMessage` types.
- **`room_context.py`** — room metadata resolution: member lists, room kind,
  thread context.

## Testing

The `conftest.py` provides websocket and HTTP mocking fixtures. Tests cover
the DDP protocol, REST API calls, reconnection behavior, message parsing,
room context resolution, and thread handling.

Tests use `MemoryChat` from `docketeer.testing` where a full `ChatClient` is
needed but Rocket.Chat-specific behavior isn't being tested.

The Rocket.Chat env vars (`DOCKETEER_ROCKETCHAT_URL`, etc.) are set to test
values via `pytest-env` in `pyproject.toml`.
