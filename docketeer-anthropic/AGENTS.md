# docketeer-anthropic

Anthropic inference backend. Implements the `docketeer.inference` entry point
to connect the Brain to Claude via the Anthropic Python SDK.

This package contains **two** `InferenceBackend` implementations, selected by
the `DOCKETEER_ANTHROPIC_BACKEND` environment variable:

- `api` (default) — direct Anthropic Messages API
- `claude-code` — delegates to Claude Code as a subprocess

## Structure

- **`api_backend.py`** — the API backend. Builds Anthropic API requests,
  handles streaming responses, manages cache breakpoints.
- **`claude_code_backend.py`** — the Claude Code backend. Different execution
  model — launches Claude Code as a subprocess and parses its output.
- **`claude_code_output.py`** — output parsing for the Claude Code backend.
- **`loop.py`** — shared agentic loop logic: tool execution, reply
  construction, streaming coordination.

## Testing

Tests are split into focused files per concern (streaming, tool execution,
cache breakpoints, etc.). The `conftest.py` provides shared helpers:
`make_response`, `make_text_block`, `make_tool_block`, `FakeStream`, and
the `MODEL` constant. Use these rather than defining local copies in test
files.

All Anthropic API calls must be faked in tests — `respx` or direct mocking.
The 1-second timeout means no real HTTP.

The `DOCKETEER_ANTHROPIC_API_KEY` and `DOCKETEER_ANTHROPIC_BACKEND` env vars
are set to test values automatically via `pytest-env` in `pyproject.toml`.
