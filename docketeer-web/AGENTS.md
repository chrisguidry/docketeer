# docketeer-web

Web tools plugin. Registers `docketeer.tools` for web search, HTTP requests,
and file downloads.

## Structure

- **`tools.py`** — all tool functions: `web_search` (Brave Search API),
  `web_request` (general HTTP with content-type-aware response handling),
  and `download_file`. Also has helpers for HTML-to-text conversion, header
  formatting, and content type detection.

## Testing

HTTP calls are faked with `respx`. The `conftest.py` wires up a workspace
and tool context. Tests are split between `test_tools.py` (helpers and
search) and `test_web_request.py` (the HTTP request tool).

The `DOCKETEER_BRAVE_API_KEY` env var is set to a test value via `pytest-env`
in `pyproject.toml`.
