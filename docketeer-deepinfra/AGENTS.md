# docketeer-deepinfra

DeepInfra inference backend. Implements the `docketeer.inference` entry point
using the OpenAI Python SDK (DeepInfra's API is OpenAI-compatible).

## Structure

- **`api_backend.py`** — builds OpenAI-format requests, streams responses,
  and translates them into Docketeer's internal message format.
- **`loop.py`** — the agentic loop: tool execution, reply construction,
  streaming. Similar in shape to the Anthropic loop but speaks the OpenAI
  tool-call protocol.

## Testing

Tests are split by concern: serialization, streaming, tool execution, usage
tracking, callbacks, and the full agentic loop. All OpenAI API calls are
faked.

The `DOCKETEER_DEEPINFRA_API_KEY` and `DOCKETEER_DEEPINFRA_BASE_URL` env vars
are set to test values via `pytest-env` in `pyproject.toml`.
