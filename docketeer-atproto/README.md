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

By default, the band connects to `wss://jetstream.waow.tech/subscribe`.

Setting `DOCKETEER_ATPROTO_RELAY_URL` overrides with a different relay.

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
