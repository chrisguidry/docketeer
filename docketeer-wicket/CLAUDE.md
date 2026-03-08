# docketeer-wicket

Wicket SSE band plugin. Registers a `docketeer.bands` entry point that
connects to Server-Sent Events endpoints and produces signals for the
antenna system.

## Structure

- **`band.py`** — `WicketBand` class: async context manager that holds an
  httpx client, streams SSE from `{base_url}/{topic}`, parses `data:`,
  `id:`, and `event:` fields into `Signal` objects.

## Testing

HTTP streaming is faked with mock context managers that yield pre-built
SSE lines. The `DOCKETEER_WICKET_URL` env var is set via `pytest-env` in
`pyproject.toml`.
