# docketeer-monty

Sandboxed Python execution plugin for
[Docketeer](https://pypi.org/project/docketeer/). Lets the agent write and run
Python code using [Monty](https://github.com/pydantic/monty), a minimal Python
interpreter written in Rust with microsecond startup and no access to the
filesystem, network, or standard library imports.

All of Docketeer's registered workspace tools are exposed as async functions
inside the sandbox, so the agent can compose multi-step operations in a single
`run_python` call.

Install `docketeer-monty` alongside `docketeer` and the tool is automatically
available. No additional configuration needed.

## Tools

- **`run_python`** — execute Python code in a sandboxed interpreter

## Example

```python
a = await read_file("notes/project.md")
b = await read_file("notes/ideas.md")
f"Project has {len(a)} chars, ideas has {len(b)} chars"
```
