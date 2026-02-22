# docketeer-monty

Sandboxed Python execution via [Monty](https://github.com/pydantic/monty).
Registers a `docketeer.tools` entry point that gives the agent a `python`
tool for running code snippets safely.

## Structure

- **`tools.py`** — the `python` tool function. Sends code to Monty for
  sandboxed execution and returns stdout/stderr.

## Testing

The `conftest.py` provides a mock Monty client. Tests verify the tool
wiring and result formatting without running real sandboxed code.
