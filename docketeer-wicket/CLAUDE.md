# docketeer-wicket

Wicket SSE band plugin. Registers a `docketeer.bands` entry point that
connects to Wicket webhook relay endpoints and produces signals for the
antenna system.

## Structure

- **`band.py`** — `WicketBand` class: async context manager that holds an
  httpx client, streams SSE from `{base_url}/{topic}`, parses wicket
  envelope format (id, timestamp, path, payload) into `Signal` objects.
  Supports per-tuning Bearer token auth via the `secret` parameter, and
  sends `filter=path:value` query params for server-side filtering.

## Testing

HTTP streaming is faked with mock context managers that yield pre-built
SSE lines. Test data uses the wicket envelope format. The
`DOCKETEER_WICKET_URL` env var is set via `pytest-env` in `pyproject.toml`.
