# docketeer-monty

Sandboxed Python execution plugin for [Docketeer](../README.md). Lets the
agent write and run Python code using [Monty](https://github.com/pydantic/monty),
a minimal Python interpreter in Rust.

## Tools

- **`run_python`** — execute Python code in a sandbox with access to all
  registered workspace tools as async functions

## How it works

Code runs in Monty's sandbox with no filesystem, network, or import access.
Docketeer's workspace tools (read_file, write_file, journal_add, etc.) are
exposed as async functions the code can `await`. This lets the agent write
small scripts that compose multiple tool calls.

```python
a = await read_file("notes/project.md")
b = await read_file("notes/ideas.md")
f"Project has {len(a)} chars, ideas has {len(b)} chars"
```

## Setup

No additional configuration needed. Install `docketeer-monty` alongside
`docketeer` and the `run_python` tool is automatically available.
