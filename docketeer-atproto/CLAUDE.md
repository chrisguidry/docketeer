# docketeer-atproto

ATProto Jetstream band plugin. Registers a `docketeer.bands` entry point that
streams ATProto events from a Jetstream relay via WebSocket.

## Structure

- **`band.py`** — `JetstreamBand` implementation. Connects to a Jetstream
  relay's `/subscribe` WebSocket endpoint, parses JSON messages into `Signal`
  objects. Handles all three Jetstream event types (commit, identity, account)
  with per-type signal conversion. Supports server-side filtering via
  `wantedCollections` and `wantedDids` query params.

## Testing

WebSocket connections are mocked with a `FakeWebSocket` async iterable.
Tests verify URL construction, cursor handling, filter hints, and signal
parsing for all three event types without any network access.
