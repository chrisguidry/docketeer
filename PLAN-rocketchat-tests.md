# Plan: Clean up docketeer-rocketchat test_reconnect.py

**This is a temporary plan file. Delete it when the work is done.**

## Problem summary

`test_reconnect.py` has moderate repetition in how it wires up fake DDP
connections. Each test manually constructs async generators for DDP events,
assigns them to the client, and patches internal methods. This is less
severe than the other packages but could still benefit from a fixture or
two.

## The repeated pattern

Most tests do some variation of:

```python
client = RocketChatClient()
client._user_id = "bot_uid"

ddp = AsyncMock()

async def fake_events() -> AsyncGenerator[dict[str, Any], None]:
    for e in events:
        yield e

ddp.events = fake_events
client._ddp = ddp
```

Followed by patching `_open_connections`, `_subscribe_to_messages`,
`set_status`, etc.

## Step 1: Add a helper or fixture for a wired-up client

A fixture that returns a `RocketChatClient` pre-wired with a fake DDP
and common method patches:

```python
@pytest.fixture()
def chat_client() -> RocketChatClient:
    client = RocketChatClient()
    client._user_id = "bot_uid"
    client._subscribe_to_messages = AsyncMock()
    client.set_status = AsyncMock()
    return client
```

And a helper to create a DDP mock from a list of events:

```python
def make_ddp(*event_lists: list[dict[str, Any]]) -> list[AsyncMock]:
    """Build DDP mocks that yield events from each list in sequence."""
    ddps = []
    for events in event_lists:
        ddp = AsyncMock()
        async def fake_events(evts=events):
            for e in evts:
                yield e
        ddp.events = fake_events
        ddps.append(ddp)
    return ddps
```

## Step 2: Simplify tests

With these, `test_incoming_messages_reconnects_on_disconnect` goes from
~35 lines of setup to something shorter. The test still has inherent
complexity (it needs two DDP instances and a reconnection callback) but
the boilerplate around async generator construction and method patching
goes away.

Don't over-abstract here — these tests are testing reconnection behavior,
and the setup IS the interesting part. The goal is to reduce noise, not
hide the wiring.

## Step 3: Check `_make_event` helper

The `_make_event` helper at the top of the file is good — it's used by
most tests. Leave it as-is.

## Step 4: Leave `_prime_history` tests alone

The `_prime_history` tests at the bottom of the file use `patch.object`
cleanly and are already focused. They don't share the DDP wiring pattern.
No changes needed.

## Validation

```sh
uv run --directory docketeer-rocketchat pytest
prek run loq --all-files
```

Coverage must stay at 100%.
