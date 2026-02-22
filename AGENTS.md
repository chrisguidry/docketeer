# Docketeer

Docketeer is a toolkit for building autonomous AI assistants. It's a
[uv workspace](https://docs.astral.sh/uv/concepts/workspaces/) of small,
focused packages that each contribute a piece of the agent: the core engine,
inference backends, chat backends, tool plugins, and task plugins. Everything
is discovered at runtime via standard Python entry points.

Read the [README](README.md) to understand the architecture before diving in.

**These AGENTS.md files are living documents.** If you learn something about
this repo that would have saved you time — a non-obvious pattern, a gotcha, a
convention that isn't written down yet — update the relevant AGENTS.md. They
represent our shared knowledge of how this codebase works.

## Repo structure

This is a flat uv workspace. Every `docketeer-*` directory at the repo root is
an independent Python package with its own `pyproject.toml`, `src/`, and
`tests/`. The `docketeer/` directory (no suffix) is the core package that all
others depend on. Each package has its own AGENTS.md with package-specific
guidance.

Run `uv sync` from the repo root to install everything into one shared venv.

## Quality standards

Everything below is enforced by tooling in pre-commit and CI. These are not
aspirational — they are hard gates. If you skip or work around them, the
commit will be rejected.

### 100% test coverage of both `src/` and `tests/`

Every package requires `--cov-fail-under=100` with branch coverage, measured
over **both** `src/` and `tests/`. This is not negotiable.

When you add production code, you write tests for it. When you delete
production code, you delete the tests that covered it.

### Type checking, linting, formatting, spelling

ty, ruff, and codespell all run in pre-commit. The configs are in the root
`pyproject.toml` and `.pre-commit-config.yaml` — read them if you're unsure
about a specific rule.

## How to run checks

We use **prek**, not pre-commit. prek is a drop-in replacement for
`pre-commit` that runs hooks in parallel. Do not try to use `pre-commit`
directly — it is not installed here.

```sh
# Run all checks (what `git commit` will trigger)
prek run --all-files

# Run a specific check while iterating
prek run ruff --all-files
prek run ty                   # very useful for fixing type errors
prek run loq --all-files
prek run pytest-docketeer     # run tests for just the core package
prek run pytest-docketeer-web # run tests for a specific plugin
```

Each package's tests can also be run directly — `cd` into the package
directory and run the tool:

```sh
cd docketeer-web && pytest              # run all tests for a package
cd docketeer-web && pytest -x           # stop on first failure
cd docketeer-web && pytest -k test_search
cd docketeer-web && ty check            # type-check a single package
```

The `./run-tests` script at the repo root is a shortcut that runs pytest
across all workspace packages sequentially.

## Testing

Tests have a **1-second timeout** per test. Every test. No exceptions. This
means all I/O must be faked — no network calls, no disk I/O outside of
`tmp_path`, no sleeping. If a test needs to wait for something, the design is
wrong.

If a protocol has a test double in `docketeer.testing`, use that instead of
`MagicMock`.

### Test doubles in `docketeer.testing`

The core package provides `MemoryChat`, `MemoryVault`, and related test
doubles in `docketeer.testing`. These are purpose-built in-memory
implementations of the `ChatClient` and `Vault` protocols. Use them instead
of writing your own mocks for these interfaces.

### Every package is independent

Each package runs its own pytest with its own coverage. When working on a
plugin, run that plugin's tests from its directory. The plugin depends on the
core `docketeer` package, so changes to core types can break downstream — run
the affected plugin tests too.

## Plugin patterns

All plugins register via entry points in their `pyproject.toml`. The patterns:

- **Single-select** (`docketeer.chat`, `docketeer.executor`,
  `docketeer.vault`, `docketeer.inference`): one active at a time, auto-selected
  if only one is installed.
- **Multi-load** (`docketeer.tools`, `docketeer.prompt`, `docketeer.tasks`):
  everything installed gets loaded.

Tool plugins register by importing their tool-decorated functions in their
package's `__init__.py`. The `@registry.tool()` decorator on a function is
what makes it available to the agent.
