# docketeer-atproto

ATProto Jetstream band plugin. Registers a `docketeer.bands` entry point that
streams ATProto events from a Jetstream relay via WebSocket.

## Structure

- **`band.py`** — `JetstreamBand` implementation. Connects to a Jetstream
  relay WebSocket, parses JSON messages into `Signal` objects. Supports
  server-side filtering via `wantedCollections` and `wantedDids` query params.

## Testing

WebSocket connections are mocked with a `FakeWebSocket` async iterable.
Tests verify URL construction, cursor handling, filter hints, and signal
parsing without any network access.
