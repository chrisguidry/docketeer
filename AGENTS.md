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

The core package provides `MemoryChat`, `MemoryVault`, `MemorySearch`, and
related test doubles in `docketeer.testing`. These are purpose-built in-memory
implementations of the `ChatClient`, `Vault`, and `SearchIndex` protocols.
Use them instead of writing your own mocks for these interfaces.

### Every package is independent

Each package runs its own pytest with its own coverage. When working on a
plugin, run that plugin's tests from its directory. The plugin depends on the
core `docketeer` package, so changes to core types can break downstream — run
the affected plugin tests too.

## Resource management

Use context managers, not open/close pairs. If a class holds a resource
(DB connection, file handle, network session), it should implement
`__enter__`/`__exit__` (or the async equivalents) and be used with `with`.
Never write code that requires callers to remember to call `.close()`.

## Plugin patterns

All plugins register via entry points in their `pyproject.toml`. The patterns:

- **Single-select** (`docketeer.chat`, `docketeer.executor`,
  `docketeer.vault`, `docketeer.inference`, `docketeer.search`): one active
  at a time, auto-selected if only one is installed.
- **Multi-load** (`docketeer.tools`, `docketeer.prompt`, `docketeer.tasks`):
  everything installed gets loaded.

Tool plugins register by importing their tool-decorated functions in their
package's `__init__.py`. The `@registry.tool()` decorator on a function is
what makes it available to the agent.

## Adding a new workspace package

Every new `docketeer-*` package requires updates in several places. Miss one
and the package won't be discovered by the workspace, tested in CI, or
type-checked correctly. Here's the full list:

### 1. Create the package directory

```
docketeer-foo/
├── pyproject.toml
├── AGENTS.md
├── README.md
├── src/docketeer_foo/
│   ├── __init__.py
│   └── ...
└── tests/
    ├── __init__.py
    └── ...
```

The `pyproject.toml` must follow the conventions of existing packages:
hatch build system, `hatch-vcs` versioning with `raw-options.root = ".."`,
`requires-python = ">=3.12"`, and the standard pytest/coverage config
(`--cov-fail-under=100`, branch coverage, 1-second timeout, asyncio_mode).
Copy an existing package's `pyproject.toml` as a starting point.

Entry points go in `[project.entry-points."docketeer.<group>"]`. If the
package depends on docketeer core, add the workspace source:

```toml
[tool.uv.sources]
docketeer = { workspace = true }
```

### 2. Register in the root `pyproject.toml`

Three places need the new package name:

- **`[tool.uv.workspace] members`** — so uv knows about it
- **`[dependency-groups] dev`** — so `uv sync` installs it
- **`[tool.uv.sources]`** — so uv resolves it from the workspace
- **`[tool.ruff.lint.isort] known-first-party`** — add the Python package
  name (underscores, e.g. `docketeer_foo`) so ruff sorts imports correctly

### 3. Add a pre-commit hook in `.pre-commit-config.yaml`

Add a `pytest-docketeer-foo` hook following the pattern of the other
packages. The `files` pattern should trigger on changes to both
`docketeer/src/` (core changes can break plugins) and the package's own
directory:

```yaml
- id: pytest-docketeer-foo
  name: pytest (docketeer-foo)
  entry: uv run --no-sync --directory docketeer-foo pytest
  language: system
  types: [python]
  files: ^docketeer/src/|^docketeer-foo/
  pass_filenames: false
  require_serial: true
```

### 4. Run `uv sync` and verify

After all registration is done, run `uv sync` from the repo root so the
new package is installed into the shared venv. Then verify:

```sh
cd docketeer-foo && pytest       # tests pass with 100% coverage
prek run ruff --all-files        # linting passes
prek run ty                      # type checking passes
```

### Common mistakes

- Forgetting `known-first-party` in ruff config → isort puts your imports
  in the wrong section
- Forgetting the `[tool.uv.sources]` entry → uv can't resolve the workspace
  dependency
- Missing `__init__.py` in `tests/` → pytest can't discover tests
- Using `--cov-config` without pointing at the root `pyproject.toml` →
  coverage exclusions don't apply

### Documentation

- Always ensure that we are maintaining the most up-to-date information
  for each plugin in its own README.md, including all of its
  configuration variables.  Also, make sure that all plugins are
  mentioned and linked in the main README.md.
