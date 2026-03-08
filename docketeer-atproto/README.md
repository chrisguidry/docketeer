# docketeer-atproto

ATProto Jetstream band plugin for
[Docketeer](https://pypi.org/project/docketeer/). Streams real-time ATProto
events from a [Jetstream](https://docs.bsky.app/blog/jetstream) relay via
WebSocket and produces `Signal` objects for the antenna system.

Install `docketeer-atproto` alongside `docketeer` and the band is
automatically available.

## Configuration

| Variable                       | Default                                                  | Description                        |
|--------------------------------|----------------------------------------------------------|------------------------------------|
| `DOCKETEER_ATPROTO_RELAY_URL`  | `wss://jetstream2.us-east.bsky.network/subscribe`        | Jetstream relay WebSocket URL.     |

## Server-side filtering

The band pushes compatible filters to the relay as query parameters:

- `collection` with `eq` or `startswith` op maps to `wantedCollections`
- `did` with `eq` op maps to `wantedDids`
