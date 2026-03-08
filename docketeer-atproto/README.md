# docketeer-atproto

ATProto Jetstream band plugin for
[Docketeer](https://pypi.org/project/docketeer/). Streams real-time ATProto
events from a [Jetstream](https://docs.bsky.app/blog/jetstream) relay via
WebSocket and produces `Signal` objects for the antenna system.

Install `docketeer-atproto` alongside `docketeer` and the band is
automatically available.

## Configuration

| Variable                       | Default                              | Description                        |
|--------------------------------|--------------------------------------|------------------------------------|
| `DOCKETEER_ATPROTO_RELAY_URL`  | _(round-robin, see below)_           | Override with a single Jetstream relay URL. |

By default, the band round-robins between the two public Jetstream relays on
each reconnect:
- `wss://jetstream1.us-east.bsky.network/subscribe`
- `wss://jetstream2.us-east.bsky.network/subscribe`

Setting `DOCKETEER_ATPROTO_RELAY_URL` pins to a single relay.

## Event types

The band handles all three Jetstream event types:

- **commit** — record creates, updates, and deletes. Topic is the collection
  NSID (e.g. `app.bsky.feed.post`). This is the main event type for posts,
  likes, follows, etc.
- **identity** — handle or DID document changes. Topic is `identity`.
- **account** — account status changes (activation, deactivation, takedown).
  Topic is `account`.

## Server-side filtering

The band pushes compatible filters to the relay as query parameters:

- `collection` with `eq` or `startswith` op maps to `wantedCollections`
- `did` with `eq` op maps to `wantedDids`
