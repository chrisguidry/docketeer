# docketeer-wicket

SSE (Server-Sent Events) band plugin for
[Docketeer](https://pypi.org/project/docketeer/). Connects to SSE endpoints
and feeds events into the antenna system as signals.

Install `docketeer-wicket` alongside `docketeer` and the band is automatically
available for tunings.

## Configuration

| Variable              | Default  | Description                          |
|-----------------------|----------|--------------------------------------|
| `DOCKETEER_WICKET_URL` | _(none)_ | Base URL of the SSE server. Required. |

The band builds stream URLs as `{DOCKETEER_WICKET_URL}/{topic}` and appends
any remote-filterable query parameters derived from `payload.*` equality
filters.
