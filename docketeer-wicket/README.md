# docketeer-wicket

SSE (Server-Sent Events) band plugin for
[Docketeer](https://pypi.org/project/docketeer/). Connects to
[Wicket](https://github.com/chrisguidry/wicket) webhook relay endpoints
and feeds events into the antenna system as signals.

Install `docketeer-wicket` alongside `docketeer` and the band is automatically
available for tunings.

## Configuration

| Variable              | Default  | Description                          |
|-----------------------|----------|--------------------------------------|
| `DOCKETEER_WICKET_URL` | _(none)_ | Base URL of the Wicket server. Required. |

The band builds stream URLs as `{DOCKETEER_WICKET_URL}/{topic}` and appends
`filter=path:value` query parameters derived from `payload.*` equality filters.

## Envelope format

Wicket SSE `data:` payloads are full envelopes:

```json
{
  "id": "uuid",
  "timestamp": "2026-03-07T12:00:00+00:00",
  "method": "POST",
  "path": "github.com/chrisguidry/docketeer",
  "headers": {"X-GitHub-Event": "push"},
  "payload": {"action": "created"}
}
```

The band unwraps these into Signal fields: `signal_id` from envelope `id`,
`timestamp` from envelope `timestamp`, `topic` from envelope `path`, and
`payload` from the inner `payload` object.

## Authentication

Tunings can reference a vault secret via the `secret` field. When set, the
resolved secret value is sent as a `Bearer` token in the `Authorization`
header. This supports wicket's per-path subscriber secrets.
